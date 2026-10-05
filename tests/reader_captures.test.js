"use strict";
// Execute the production reader with verified fixture bytes and a minimal DOM.
const assert = require("node:assert/strict"), crypto = require("node:crypto");
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../wikibuild/web/reader.js"), "utf8").replace("start().catch(failure);", "");
const base = "https://wiki-fixture.github.io/Wiki-items/";
const encode = value => Buffer.from(JSON.stringify(value));
const hash = data => crypto.createHash("sha256").update(data).digest("hex");

class Node {
  constructor(tag) {this.tag = tag; this.children = []; this.events = {}; this.textContent = ""; this.hidden = false; this.disabled = false; this.dataset = {};}
  append(...nodes) {for (const node of nodes) {node.parentElement = this; this.children.push(node);}}
  after(node) {this.parentElement.append(node);}
  replaceChildren(...nodes) {this.children = []; this.append(...nodes);}
  setAttribute() {}
  addEventListener(name, fn) {this.events[name] = fn;}
}

function reader(configuration, fetchBytes, selected = configuration.default_snapshot, site = base) {
  const calls = [], nodes = {};
  for (const id of ["content", "status", "version", "home", "topics", "credits", "search-form"]) nodes[id] = new Node(id);
  const controls = new Node("controls"), label = new Node("label"); controls.append(label); label.append(nodes.version);
  const context = {URL, URLSearchParams, TextDecoder, crypto: crypto.webcrypto,
    humanHostReader: {config: configuration, base: site},
    location: {origin: new URL(site).origin, pathname: new URL(site).pathname, href: site,
      search: "?" + new URLSearchParams({snapshot: selected, release: configuration.release_id})},
    document: {getElementById: id => nodes[id], createElement: tag => new Node(tag), createTextNode: text => Object.assign(new Node("#text"), {textContent: String(text)})},
    fetch: async url => {
      calls.push(url); const data = await fetchBytes(url);
      return {ok: !!data, status: data ? 200 : 404,
        arrayBuffer: async () => data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength)};
    }};
  vm.runInNewContext(source, context);
  return {context, nodes, controls, calls};
}

function fixture(count = 121) {
  const files = {};
  function store(value, extra) {
    const data = encode(value), name = "objects/" + hash(data) + ".json";
    files[base + name] = data;
    return {path: name, bytes: data.length, sha256: hash(data), ...extra};
  }
  function page(values) {
    const keys = Object.keys(values).sort();
    return store(values, {first: keys[0], last: keys.at(-1), count: keys.length});
  }
  function directory(shards) {
    return store({kind: "wiki-shard-directory", schema_version: 1, shards},
      {kind: "wiki-shard-directory", first: shards[0].first, last: shards.at(-1).last, count: shards.reduce((sum, row) => sum + row.count, 0)});
  }
  const records = [], ids = [], order = [];
  for (let i = 0; i < count; i++) {
    const id = `build-${1000 + i}-aaaaaaaaaaaa`;
    records.push({version: {snapshot_id: id, build_id: String(1000 + i)}, ordinal: i,
      index: store({snapshot_id: id, steam: {build_id: String(1000 + i)}, counts: {}})});
  }
  for (let offset = 0; offset < count; offset += 10) {
    const chunk = records.slice(offset, offset + 10);
    ids.push(page(Object.fromEntries(chunk.map(r => [r.version.snapshot_id, r]))));
    order.push(page(Object.fromEntries(chunk.map(r => [String(r.ordinal).padStart(16, "0"), r.version.snapshot_id]))));
  }
  const root = {schema_version: 1, kind: "wiki-capture-catalog", count,
    by_id: [directory(ids)], by_order: [directory(order)]};
  const configuration = {topic: "items", release_id: "a".repeat(64), default_snapshot: records.at(-1).version.snapshot_id,
    default_capture: records.at(-1), capture_catalog: store(root), official_links: [],
    topics: [{id: "hub", base, title: "Home"}, {id: "items", base, title: "Items", coverage: "Partial"}]};
  return {files, configuration, records, root, store};
}

(async () => {
  const data = fixture();
  let subject = reader(data.configuration, url => data.files[url]);
  await subject.context.start();
  assert.equal(subject.calls.length, 1, "Default startup fetched the history catalog");
  assert.equal(subject.nodes.version.children.length, 1);
  const controls = subject.controls.children.at(-1), more = controls.children[0];
  await more.events.click();
  assert.equal(subject.nodes.version.children.length, 50);
  assert.equal(subject.nodes.version.children.filter(row => row.selected).length, 1);
  const history = [];
  const pager = subject.context.capturePager(version => history.push(version.snapshot_id));
  const button = pager.children[0];
  await button.events.click(); await button.events.click(); await button.events.click();
  assert.equal(button.hidden, true);
  assert.deepEqual(history, data.records.map(row => row.version.snapshot_id).reverse());

  subject = reader(data.configuration, url => data.files[url], data.records[3].version.snapshot_id);
  await subject.context.start();
  assert.ok(subject.calls.length <= 4, "Exact historical startup fetched unrelated pages");
  assert.equal(subject.nodes.version.children[0].value, data.records[3].version.snapshot_id);
  const all = subject.controls.children.at(-1).children[0];
  await all.events.click(); await all.events.click(); await all.events.click();
  assert.equal(subject.nodes.version.children.length, data.records.length);
  assert.equal(subject.nodes.version.children.filter(row => row.selected).length, 1);
  await assert.rejects(subject.context.captureFor("build-missing"), /missing capture/);

  // A failed partial batch appends nothing and does not advance the cursor.
  let unavailable = true;
  const denied = base + data.root.by_id[0].path;
  subject = reader(data.configuration, url => unavailable && url === denied ? null : data.files[url]);
  await subject.context.start();
  const retryBox = subject.controls.children.at(-1), retry = retryBox.children[0];
  await retry.events.click();
  assert.match(retryBox.children[1].textContent, /HTTP 404/);
  assert.equal(subject.nodes.version.children.length, 1);
  unavailable = false;
  await retry.events.click();
  assert.equal(subject.nodes.version.children.length, 50);
  assert.equal(retryBox.children[1].textContent, "");

  const bad = {...data.configuration, capture_catalog: {...data.configuration.capture_catalog, sha256: "0".repeat(64)}};
  subject = reader(bad, url => data.files[url]); await subject.context.start();
  await assert.rejects(subject.context.captureBatch(), /verification failed/);
  const wrongOrder = {...data.root, by_order: data.root.by_id};
  subject = reader({...data.configuration, capture_catalog: data.store(wrongOrder)}, url => data.files[url]);
  await subject.context.start();
  await assert.rejects(subject.context.captureBatch(), /chronology/);

  const flat = {...data.configuration, versions: data.records.map(row => row.version).reverse(),
    snapshots: Object.fromEntries(data.records.map(row => [row.version.snapshot_id, row.index]))};
  delete flat.capture_catalog; delete flat.default_capture;
  subject = reader(flat, url => data.files[url]); await subject.context.start();
  assert.equal(subject.calls.length, 1);
  assert.equal(subject.nodes.version.children.length, data.records.length);
  console.log("Capture selection, bounded paging, retry and legacy checks passed");

  assert.match(subject.nodes.status.textContent.replaceAll("\u00a0", " "), /Game version unknown/);
  assert.match(subject.nodes.version.children[0].textContent, /Version unknown/);
  const latest = data.records.at(-1);
  latest.version.game_version = "0.8.315";
  const versionData = data.store({snapshot_id: latest.version.snapshot_id, steam: {build_id: latest.version.build_id},
    game_version: "0.8.315", game_version_evidence: [{source_path: "Human Host_Data/globalgamemanagers",
      object_id: "globalgamemanagers#1", field: "/bundleVersion", source_sha256: "e".repeat(64)}], counts: {}});
  flat.snapshots[latest.version.snapshot_id] = versionData;
  subject = reader(flat, url => data.files[url]); await subject.context.start();
  assert.match(subject.nodes.status.textContent.replaceAll("\u00a0", " "), /Game version 0.8.315/);
  assert.match(subject.nodes.status.title, /globalgamemanagers#1\/bundleVersion/);
  assert.match(subject.nodes.version.children[0].textContent, /0.8.315/);
  subject = reader(flat, url => data.files[url], data.records[0].version.snapshot_id); await subject.context.start();
  assert.match(subject.nodes.status.textContent.replaceAll("\u00a0", " "), /Game version unknown/);
  console.log("Captured application version, provenance and historical unknown passed");

  const availability = {status: "observed", checked_at: "2026-09-27T09:00:00+00:00",
    observation: {app_id: "2393970", branch: "public", build_id: data.records.at(-1).version.build_id}};
  // The top line is the update date, game version and Steam build, and nothing else.
  // Dates render in the viewer's timezone, so each case pins one.
  const line = () => subject.nodes.status.textContent.replaceAll("\u00a0", " ");
  process.env.TZ = "UTC";
  subject = reader({...flat, availability}, url => data.files[url]); await subject.context.start();
  assert.equal(line(), "Updated Sep 27, 2026 · Game version 0.8.315 · Steam build 1120");
  process.env.TZ = "Pacific/Honolulu";
  subject = reader({...flat, availability}, url => data.files[url]); await subject.context.start();
  assert.equal(line(), "Updated Sep 26, 2026 · Game version 0.8.315 · Steam build 1120");
  process.env.TZ = "UTC";
  subject = reader({...flat, availability}, url => data.files[url], data.records[0].version.snapshot_id);
  await subject.context.start();
  assert.equal(line(), "Older version · Game version unknown · Steam build 1000");
  // A failed Steam check is not an update, so no date is claimed.
  subject = reader({...flat, availability: {...availability, status: "unavailable"}}, url => data.files[url]);
  await subject.context.start();
  assert.equal(line(), "Game version 0.8.315 · Steam build 1120");
  subject = reader(flat, url => data.files[url]); await subject.context.start();
  assert.equal(line(), "Game version 0.8.315 · Steam build 1120");
  console.log("Update date, game version and build line passed");

  const checked = {status: "passed", title: "Configured limit", text: "<script>literal</script>",
    scope: "selected-data", checks: [], authored_source: {path: "curated/limit.json"},
    last_verified: {build_id: "100", snapshot_id: "build-100-aaaaaaaaaaaa", text: "Old checked text"}};
  const flattened = node => [node.textContent, ...node.children.flatMap(flattened)];
  const tags = node => [node.tag, ...node.children.flatMap(tags)];
  let explanation = subject.context.checkedExplanations([checked]);
  assert.ok(flattened(explanation).includes("<script>literal</script>"));
  assert.ok(!tags(explanation).includes("script"));
  assert.match(flattened(explanation).join(" "), /Declared selected-data checks passed/);
  explanation = subject.context.checkedExplanations([{...checked, status: "unverified", text: null,
    reasons: ["limit: above-maximum"]}]);
  const explanationText = flattened(explanation).join(" ");
  assert.match(explanationText, /Unverified explanation: limit: above-maximum/);
  assert.match(explanationText, /Last successful check: Steam build 100/);
  assert.match(explanationText, /Previously checked text.*Old checked text/);
  assert.doesNotMatch(explanationText, /checks passed/);
  console.log("Literal authored text, scoped checks and retained failed-check history passed");

  const entity = "e-" + "b".repeat(32), selected = flat.default_snapshot;
  const articleKey = selected + "/" + entity;
  const articleRecord = {status: "populated", title: "Human Host:<script>literal</script>",
    url: "https://wiki.example/index.php?oldid=10"};
  const articlePack = data.store({[articleKey]: articleRecord}, {first: articleKey, last: articleKey, count: 1});
  const articleView = {schema_version: 1, kinds: ["item"], default_status: "missing", checked_at: "2026-09-27T12:00:00Z",
    topics: [articleRecord, {status: "empty", title: "Human Host:Empty", reason: "no-body", url: "https://should-not-link.example/"}],
    entries: [articlePack]};
  subject = reader({...flat, external_articles: data.store(articleView)}, url => data.files[url]);
  await subject.context.start();
  let articles = await subject.context.articleLinks({entity_key: entity, kind: "item", status: "present"});
  assert.ok(tags(articles).includes("a"));
  assert.ok(!tags(articles).includes("script"));
  assert.match(flattened(articles).join(" "), /<script>literal<\/script>/);
  assert.match(flattened(articles).join(" "), /does not check them against this one/);
  articles = await subject.context.articleLinks();
  assert.equal(tags(articles).filter(tag => tag === "a").length, 1, "Empty article emitted a link");
  articles = await subject.context.articleLinks({entity_key: "e-" + "c".repeat(32), kind: "item", status: "present"});
  assert.match(flattened(articles).join(" "), /missing/);
  assert.ok(!tags(articles).includes("a"));
  assert.equal(await subject.context.articleLinks({entity_key: entity, kind: "item", status: "not-present"}), null);
  const badArticles = data.store(articleView); badArticles.sha256 = "f".repeat(64);
  subject = reader({...flat, external_articles: badArticles}, url => data.files[url]); await subject.context.start();
  assert.match(flattened(subject.nodes.content).join(" "), /Community article checks could not be loaded/);
  assert.ok(!flattened(subject.nodes.content).includes("This view could not be loaded"), "Optional article failure replaced the topic");
  subject = reader({...flat, external_articles: {...articleView, topics: [{...articleRecord, url: "javascript:alert(1)"}]}}, url => data.files[url]);
  await subject.context.start();
  assert.match(flattened(subject.nodes.content).join(" "), /Invalid community article destination/);
  console.log("External article hashes, literal labels, missing/empty states and isolated failure passed");

  // A slow optional control must not delay topic navigation or selected facts.
  const entry = {entity_key: entity, topic: "items", kind: "item", name: "Axe", status: "present",
    revision_id: "revision-1", decision: {status: "same"}, links: {}};
  const entryRef = data.store({[entity]: entry}, {first: entity, last: entity, count: 1});
  const semanticRef = data.store({"revision-1": {evidence_level: "selected-data", facts: {MaxStack: 1}, relationships: []}},
    {first: "revision-1", last: "revision-1", count: 1});
  const entryIndex = data.store({snapshot_id: selected, steam: {build_id: latest.version.build_id},
    counts: {item: 1}, entries: [entryRef], semantics: [semanticRef], provenance: [], backlinks: []});
  const published = "e-" + "d".repeat(32), historicalSnapshot = data.records[0].version.snapshot_id;
  const redirectedIndex = data.store({snapshot_id: historicalSnapshot, steam: {build_id: "1000"},
    redirects: {[published]: entity}, counts: {item: 1}, entries: [entryRef], semantics: [semanticRef], provenance: [], backlinks: []});
  subject = reader({...flat, snapshots: {...flat.snapshots, [historicalSnapshot]: redirectedIndex}},
    url => data.files[url], historicalSnapshot);
  subject.context.location.pathname += "entry/" + published + "/";
  await subject.context.start();
  assert.match(flattened(subject.nodes.content).join(" "), /Axe.*Game fields.*MaxStack.*1/);
  assert.equal(subject.nodes.version.children.find(row => row.selected).value, historicalSnapshot);
  assert.match(subject.nodes.status.textContent.replaceAll("\u00a0", " "), /Steam build 1000/);
  assert.ok(!subject.calls.includes(base + entryIndex.path), "Redirect changed the selected capture");
  // Immutable older packs may still have their data only under the redirect source.
  const historicalRef = data.store({[published]: {...entry, entity_key: published}}, {first: published, last: published, count: 1});
  const legacyRedirectIndex = data.store({snapshot_id: historicalSnapshot, steam: {build_id: "1000"},
    redirects: {[published]: entity}, entries: [historicalRef], semantics: [semanticRef], provenance: [], backlinks: []});
  subject = reader({...flat, snapshots: {...flat.snapshots, [historicalSnapshot]: legacyRedirectIndex}},
    url => data.files[url], historicalSnapshot);
  subject.context.location.pathname += "entry/" + published + "/";
  await subject.context.start();
  assert.match(flattened(subject.nodes.content).join(" "), /Axe.*MaxStack.*1/);
  console.log("Published-key redirects retain selected capture and frozen historical data");
  const articleControl = data.store(articleView);
  for (const route of ["overview", "entry"]) {
    let requested, finish;
    const requestStarted = new Promise(resolve => {requested = resolve;});
    const response = new Promise(resolve => {finish = resolve;});
    subject = reader({...flat, snapshots: {...flat.snapshots, [selected]: entryIndex}, external_articles: articleControl},
      url => {if (url === base + articleControl.path) {requested(); return response;} return data.files[url];});
    if (route === "entry") subject.context.location.pathname += "entry/" + entity + "/";
    const loaded = subject.context.start();
    await requestStarted;
    try {
      assert.match(flattened(subject.nodes.content).join(" "), route === "entry" ? /Game fields.*MaxStack.*1/ : /Everything.*Item.*1/,
        "Core " + route + " content waited for optional article metadata");
      if (route === "overview") subject.nodes.content.replaceChildren(new Node("new-search-view"));
    } finally {finish(data.files[base + articleControl.path]);}
    await loaded;
    if (route === "overview") assert.deepEqual(tags(subject.nodes.content), ["content", "new-search-view"],
      "Delayed topic links were appended to the replacement search view");
    else assert.match(flattened(subject.nodes.content).join(" "), /Community wiki articles/);
  }
  console.log("Core topic and entry content renders before optional article requests finish");

  const wikiPlayer = {name: "Stone Axe combat", name_source: "wiki", name_rule: "combat-user"};
  const wikiPlayerId = "player-wiki-name";
  const wikiPlayerRef = data.store({[wikiPlayerId]: wikiPlayer}, {first: wikiPlayerId, last: wikiPlayerId, count: 1});
  const wikiEntryRef = data.store({[entity]: {...entry, name: "Axe_Combo_2", player_id: wikiPlayerId}},
    {first: entity, last: entity, count: 1});
  const wikiIndex = data.store({snapshot_id: selected, steam: {build_id: latest.version.build_id},
    counts: {item: 1}, entries: [wikiEntryRef], semantics: [semanticRef], provenance: [], backlinks: [],
    player: [wikiPlayerRef]});
  subject = reader({...flat, snapshots: {...flat.snapshots, [selected]: wikiIndex}}, url => data.files[url]);
  subject.context.location.pathname += "entry/" + entity + "/";
  await subject.context.start();
  const entryView = subject.nodes.content.children[0];
  const header = entryView.children.find(node => node.tag === "header" && node.className === "entry-head");
  const reference = entryView.children.find(node => node.tag === "details" && node.className === "techref");
  assert.ok(header);
  assert.ok(reference);
  assert.doesNotMatch(flattened(header).join(" "), /Axe_Combo_2/);
  assert.match(flattened(reference).join(" "), /Game file name.*Axe_Combo_2/);
  // Guides built before biomes were numbered from 1 still load with their old "Ring 0" headings.
  assert.deepEqual({...subject.context.biomeHeading("Ring 0: Mountain Forest", "ring-0")}, {number: "1", place: "Mountain Forest"});
  assert.deepEqual({...subject.context.biomeHeading("Biome 10: Winter Forest", "ring-9")}, {number: "10", place: "Winter Forest"});
  assert.deepEqual({...subject.context.biomeHeading("How the world is laid out", "world")}, {number: "", place: "How the world is laid out"});
  console.log("Wiki-named entry header hides the game file name; technical reference retains it");

  const codedSemantic = {facts: {_AmmoType: 5, nested: [{_SlotType: 4}]},
    fact_labels: {"/_AmmoType": "7.62x54mm", "/nested/0/_SlotType": "Ammo"},
    relationships: [{predicate: "coded-value", field: "/_AmmoType", targets: ["caliber"]},
      {predicate: "coded-value", field: "/nested/0/_SlotType", targets: ["slot"]}]};
  const codedRecord = {links: {caliber: {topic: "items", name: "Ammo type: 7.62x54mm"}, slot: {topic: "items", name: "Ammo"}}};
  const readableFacts = subject.context.factsTable(codedSemantic.facts, {semantic: codedSemantic, record: codedRecord});
  // ADR-0002: the technical reference keeps raw field names verbatim; coded values still read as labels.
  assert.ok(flattened(readableFacts).includes("_AmmoType"));
  assert.ok(flattened(readableFacts).includes("7.62x54mm"));
  assert.ok(!flattened(readableFacts).includes("5"));
  const descendants = node => [node, ...node.children.flatMap(descendants)];
  const codeLinks = descendants(readableFacts).filter(node => node.tag === "a");
  assert.equal(codeLinks.length, 2);
  assert.match(codeLinks[0].href, /entry\/caliber\//);
  assert.ok(new URL(codeLinks[0].href).searchParams.has("snapshot"));
  assert.ok(new URL(codeLinks[0].href).searchParams.has("release"));
  const rawFacts = subject.context.factsTable(codedSemantic.facts);
  assert.ok(flattened(rawFacts).includes("_AmmoType"));
  assert.ok(flattened(rawFacts).includes("5"));
  codedSemantic.fact_labels['/_AmmoType'] = 'Unresolved code (99)';
  codedSemantic.relationships = [];
  const unresolvedFacts = subject.context.factsTable(codedSemantic.facts, {semantic: codedSemantic, record: codedRecord});
  assert.ok(flattened(unresolvedFacts).includes('Unresolved code (99)'));
  assert.equal(descendants(unresolvedFacts).filter(node => node.tag === 'a').length, 0);
  console.log('Readable enum labels, nested graph links, pinned routes and raw provenance passed');

  const player = {name: "Iron Ore", name_source: "game", name_rule: null,
    how: [[{text: "mined in "}, {text: "War Zone", entity: "biome"}, {text: " (20% of dig hits)"}],
      [{text: "crafted by hand"}]], used_in: {count: 13, items: [{text: "Stone Axe", entity: "recipe"}]},
    links: {biome: {name: "War Zone", topic: "items"}, recipe: {name: "Stone Axe", topic: "items"}}};
  const playerView = subject.context.playerCard(null, player, {links: {}});
  assert.match(flattened(playerView).join(" "), /Mined in.*War Zone.*20% of dig hits/);
  assert.ok(flattened(playerView).includes("Crafted by hand"));
  const playerLinks = descendants(playerView).filter(node => node.tag === "a");
  assert.equal(playerLinks.length, 2);
  assert.match(playerLinks[0].href, /entry\/biome\//);
  assert.match(playerLinks[1].href, /entry\/recipe\//);
  for (const link of playerLinks) {
    assert.ok(new URL(link.href).searchParams.has("snapshot"));
    assert.ok(new URL(link.href).searchParams.has("release"));
  }
  const names = [{entity_key: "combat", name: "Stone Axe combat", source_name: "Axe_Combo_2", kind: "combat-rule"}];
  assert.equal(subject.context.rank(names, "Stone Axe")[0].entity_key, "combat");
  assert.equal(subject.context.rank(names, "Axe_Combo_2")[0].entity_key, "combat");
  console.log("Player phrases, route-complete links and source-name search passed");

  if (process.argv[2]) {
    const input = JSON.parse(fs.readFileSync(process.argv[2], "utf8")), root = path.resolve(input.root);
    const disk = url => {
      const target = new URL(url); assert.equal(target.origin, new URL(input.base).origin);
      const file = path.resolve(root, "." + target.pathname); assert.ok(file.startsWith(root + path.sep));
      return fs.readFileSync(file);
    };
    const configuration = JSON.parse(disk(new URL(input.configuration.path, input.base).href));
    assert.ok(configuration.capture_catalog);
    subject = reader(configuration, disk, input.selected, input.base);
    await subject.context.start();
    assert.equal(subject.nodes.version.children[0].value, input.selected);
    assert.ok(subject.calls.length <= 6);
    const found = [], button = subject.context.capturePager(version => found.push(version.snapshot_id)).children[0];
    while (!button.hidden) {await button.events.click(); assert.ok(!button.parentElement.children[1].textContent);}
    assert.deepEqual(found, input.expected);
    console.log("Generated physical catalog: exact selection and complete chronological browsing passed");
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
