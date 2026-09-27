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
    document: {getElementById: id => nodes[id], createElement: tag => new Node(tag), createTextNode: text => new Node(text)},
    fetch: async url => {
      calls.push(url); const data = fetchBytes(url);
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

  const availability = {status: "observed", checked_at: "2026-09-27T09:00:00+00:00",
    observation: {app_id: "2393970", branch: "public", build_id: data.records.at(-1).version.build_id}};
  subject = reader({...flat, availability}, url => data.files[url]); await subject.context.start();
  assert.match(subject.nodes.status.textContent, /Selected build matches that observation/);
  assert.match(subject.nodes.status.textContent, /Gameplay verification not performed/);
  assert.match(subject.nodes.status.textContent, /2026-09-27T09:00:00/);
  subject = reader({...flat, availability}, url => data.files[url], data.records[0].version.snapshot_id);
  await subject.context.start();
  assert.match(subject.nodes.status.textContent, /Selected build differs/);
  subject = reader({...flat, availability: {...availability, status: "unavailable"}}, url => data.files[url]);
  await subject.context.start();
  assert.match(subject.nodes.status.textContent, /Latest available build unknown/);
  assert.doesNotMatch(subject.nodes.status.textContent, /Selected build matches/);
  console.log("Availability evidence, historical comparison and unavailable state passed");

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
