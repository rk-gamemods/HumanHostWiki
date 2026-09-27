"use strict";

// All imported text is rendered through textContent. No game text becomes HTML.
const siteBase = globalThis.humanHostReader ? new URL(globalThis.humanHostReader.base) : new URL(".", document.currentScript.src);
const routeBase = globalThis.humanHostReader?.routeBase ? new URL(globalThis.humanHostReader.routeBase) : siteBase;
const resolveURL = globalThis.humanHostReader?.resolve || ((value, base) => new URL(value, base));
const params = new URLSearchParams(location.search);
const content = document.getElementById("content");
const cache = new Map();
let config, snapshot, index, searchGeneration = 0;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

async function json(path, expected) {
  const url = resolveURL(path, siteBase).href;
  if (expected && new URL(url).origin !== siteBase.origin) throw new Error("Content leaves the configured namespace");
  const cacheKey = JSON.stringify([url, expected?.sha256, expected?.bytes]);
  if (!cache.has(cacheKey)) {
    const pending = (async () => {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`Cannot load ${path}: HTTP ${response.status}`);
      const bytes = await response.arrayBuffer();
      if (expected) {
        const sha = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), value => value.toString(16).padStart(2, "0")).join("");
        if (bytes.byteLength !== expected.bytes || sha !== expected.sha256) throw new Error(`Content verification failed for ${path}`);
      }
      return JSON.parse(new TextDecoder().decode(bytes));
    })();
    cache.set(cacheKey, pending);
    // Bound retained packs, including search. The browser HTTP cache handles revisits.
    if (cache.size > 24) cache.delete(cache.keys().next().value);
  }
  try { return await cache.get(cacheKey); } catch (error) { cache.delete(cacheKey); throw error; }
}

function url(topic, entity = null, selected = snapshot, group = null) {
  const owner = config.topics.find(value => value.id === topic);
  if (!owner) throw new Error(`Unknown topic ${topic}`);
  const path = entity ? `entry/${encodeURIComponent(entity)}/` : group ? `groups/${encodeURIComponent(group)}/` : "";
  const target = resolveURL(path, new URL(owner.base, location.origin));
  target.search = new URLSearchParams({snapshot: selected, release: config.release_id || config.candidate_id}).toString();
  return target.href;
}

function link(text, target) {
  const node = element("a", text);
  node.href = target;
  return node;
}

async function* shardReferences(refs, first = null, last = first, active = new Set(), reverse = false) {
  for (let offset = 0; offset < refs.length; offset++) {
    const ref = refs[reverse ? refs.length - offset - 1 : offset];
    if (first !== null && (ref.last < first || ref.first > last)) continue;
    if (!ref.kind) {yield ref; continue;}
    if (ref.kind !== "wiki-shard-directory") throw new Error("Unknown shard directory kind");
    const target = resolveURL(ref.path, siteBase);
    if (target.origin !== siteBase.origin) throw new Error("Shard directory leaves the configured namespace");
    if (active.has(target.href) || active.size >= 32) throw new Error("Shard directory cycle or depth exceeded");
    active.add(target.href);
    try {
      const value = await json(ref.path, ref);
      if (value.schema_version !== 1 || value.kind !== ref.kind || !Array.isArray(value.shards) || !value.shards.length) throw new Error("Invalid shard directory");
      let low = null, high = null, count = 0;
      for (const child of value.shards) {
        if (typeof child.first !== "string" || typeof child.last !== "string" || child.first > child.last || !Number.isSafeInteger(child.count) || child.count < 1) throw new Error("Invalid shard directory range");
        low = low === null || child.first < low ? child.first : low;
        high = high === null || child.last > high ? child.last : high;
        count += child.count;
      }
      if (low !== ref.first || high !== ref.last || count !== ref.count) throw new Error("Shard directory summary differs");
      yield* shardReferences(value.shards, first, last, active, reverse);
    } finally {active.delete(target.href);}
  }
}

async function keyed(shards, key) {
  for await (const shard of shardReferences(shards, key)) {
    const value = (await json(shard.path, shard))[key];
    if (value !== undefined) return value;
  }
  return undefined;
}

async function captureCatalog() {
  const root = await json(config.capture_catalog.path, config.capture_catalog);
  if (root.schema_version !== 1 || root.kind !== "wiki-capture-catalog" || !Number.isSafeInteger(root.count) || root.count < 1) throw new Error("Invalid capture catalog");
  for (const field of ["by_id", "by_order"]) {
    if (!Array.isArray(root[field])) throw new Error("Invalid capture catalog index");
    let previous = null, count = 0;
    for (const ref of root[field]) {
      if (typeof ref.first !== "string" || typeof ref.last !== "string" || ref.first > ref.last || (previous !== null && ref.first <= previous) || !Number.isSafeInteger(ref.count) || ref.count < 1) throw new Error("Invalid capture catalog range");
      previous = ref.last; count += ref.count;
    }
    if (count !== root.count) throw new Error("Capture catalog count differs");
  }
  return root;
}

function captureRecord(record, identity) {
  if (!record || record.version?.snapshot_id !== identity || !Number.isSafeInteger(record.ordinal) || record.ordinal < 0 || !record.index?.path || !/^[0-9a-f]{64}$/.test(record.index.sha256) || !Number.isSafeInteger(record.index.bytes) || record.index.bytes < 1) throw new Error("Invalid or missing capture record");
  return record;
}

async function captureFor(identity) {
  if (!config.capture_catalog) {
    const position = config.versions.findIndex(version => version.snapshot_id === identity);
    if (position < 0) throw new Error("The requested snapshot is unavailable in this reader revision");
    return {version: config.versions[position], index: config.snapshots?.[identity], ordinal: config.versions.length - position - 1};
  }
  if (identity === config.default_snapshot) return captureRecord(config.default_capture, identity);
  const root = await captureCatalog();
  const record = captureRecord(await keyed(root.by_id, identity), identity);
  if (record.ordinal >= root.count) throw new Error("Capture ordinal exceeds catalog");
  return record;
}

async function captureBatch(before = null, limit = 50) {
  if (!config.capture_catalog) {
    const count = config.versions.length, end = before === null ? count : before;
    return config.versions.slice(count - end, count - end + limit).map((version, position) => ({version, ordinal: end - position - 1}));
  }
  const root = await captureCatalog(), end = before === null ? root.count : before;
  if (!Number.isSafeInteger(end) || end < 0 || end > root.count) throw new Error("Invalid capture cursor");
  if (!end) return [];
  const rows = [], last = String(end - 1).padStart(16, "0");
  for await (const ref of shardReferences(root.by_order, "0000000000000000", last, new Set(), true)) {
    const values = await json(ref.path, ref), keys = Object.keys(values).sort().reverse();
    for (const key of keys) {
      if (key > last) continue;
      const ordinal = end - rows.length - 1;
      if (key !== String(ordinal).padStart(16, "0")) throw new Error("Capture chronology is incomplete");
      const record = await captureFor(values[key]);
      if (record.ordinal !== ordinal) throw new Error("Capture chronology differs from record");
      rows.push(record);
      if (rows.length === limit) return rows;
    }
  }
  if (rows.length !== end) throw new Error("Capture chronology is incomplete");
  return rows;
}

function capturePager(append) {
  const box = element("div"), more = element("button", "Load more captured versions"), message = element("p", "");
  let before = null, loading = false;
  message.setAttribute("role", "status");
  more.addEventListener("click", async () => {
    if (loading) return;
    loading = true; more.disabled = true; message.textContent = "";
    try {
      // Commit the cursor only after a complete batch. A failed fetch can retry
      // the same range without silently skipping versions or duplicating links.
      const rows = await captureBatch(before);
      for (const row of rows) append(row.version);
      before = rows.length ? rows.at(-1).ordinal : 0;
      more.hidden = before === 0;
    } catch (error) {message.textContent = error.message;}
    finally {loading = false; more.disabled = false;}
  });
  box.append(more, message);
  return box;
}

function notice(text) {
  return element("p", text, "notice");
}

function fieldLabel(field) {
  const text = field.replace(/^_+/, "").replace(/([a-z0-9])([A-Z])/g, "$1 $2").replaceAll("_", " ");
  return text ? text[0].toUpperCase() + text.slice(1) : field;
}

function valueNode(value, context = null, pointer = "") {
  if (context && Object.hasOwn(context.semantic.fact_labels || {}, pointer)) {
    const label = context.semantic.fact_labels[pointer];
    const relation = context.semantic.relationships.find(row => row.predicate === "coded-value" && row.field === pointer);
    if (relation?.targets.length === 1) {
      const target = relation.targets[0], destination = context.record.links[target];
      if (destination) return link(label, url(destination.topic, target));
    }
    return element("span", label);
  }
  if (value === null) return element("span", "Not set", "muted");
  if (typeof value !== "object") return element("span", typeof value === "boolean" ? (value ? "Yes" : "No") : value);
  const entries = Object.entries(value);
  if (!entries.length) return element("span", "None recorded", "muted");
  const details = element("details");
  details.append(element("summary", `${entries.length} ${Array.isArray(value) ? "entries" : "fields"}`));
  const list = element("dl", undefined, "facts");
  for (const [key, child] of entries) {
    list.append(element("dt", Array.isArray(value) ? `Entry ${Number(key) + 1}` : context ? fieldLabel(key) : key));
    const description = element("dd");
    description.append(valueNode(child, context, pointer + "/" + key));
    list.append(description);
  }
  details.append(list);
  return details;
}

function factsTable(facts, context = null) {
  const list = element("dl", undefined, "facts");
  for (const [field, value] of Object.entries(facts)) {
    const description = element("dd");
    description.append(valueNode(value, context, "/" + field));
    list.append(element("dt", context ? fieldLabel(field) : field), description);
  }
  return list;
}

function failure(error) {
  content.replaceChildren(element("h2", "This view could not be loaded"), notice(error.message));
  document.getElementById("status").textContent = "Reader failure. No different snapshot was substituted.";
}

function displayResults(results, heading) {
  const section = element("section");
  section.append(element("h2", heading), element("p", `${results.length.toLocaleString()} entries`, "muted"));
  const table = element("table");
  const header = element("tr");
  for (const title of ["Name", "Kind", "Status"]) header.append(element("th", title));
  const head = element("thead"); head.append(header); table.append(head);
  const body = element("tbody"); table.append(body); section.append(table);
  let position = 0;
  const more = element("button", "Show more entries");
  function append() {
    for (const row of results.slice(position, position + 100)) {
      const tr = element("tr"), name = element("td");
      name.append(link(row.name, url(row.topic, row.entity_key)));
      tr.append(name, element("td", row.kind), element("td", row.status));
      body.append(tr);
    }
    position += 100;
    more.hidden = position >= results.length;
  }
  more.addEventListener("click", append); append(); section.append(more);
  content.replaceChildren(section);
}

async function search(query, group) {
  const generation = ++searchGeneration;
  const needle = query.trim().toLocaleLowerCase("en");
  document.getElementById("status").textContent = `Searching Steam build ${index.steam.build_id}...`;
  const found = [];
  // Serial pack reads keep memory and peak bandwidth bounded on large topics.
  for await (const shard of shardReferences(index.search)) {
    const values = await json(shard.path, shard);
    if (generation !== searchGeneration) return;
    for (const row of Object.values(values)) {
      if ((!group || row.kind === group) && (!needle || [row.name, row.kind, row.source_id || "", row.entity_key].join(" ").toLocaleLowerCase("en").includes(needle))) found.push(row);
    }
  }
  found.sort((a, b) => a.name.localeCompare(b.name, "en") || a.entity_key.localeCompare(b.entity_key));
  displayResults(found, group ? group.replaceAll("-", " ") : query ? `Search: ${query}` : "All entries");
  status();
}

function status() {
  const evidence = config.availability;
  let freshness = "Latest available build unknown";
  if (evidence?.status === "observed") {
    const observed = evidence.observation;
    const sameBranch = (index.steam.branch || "public") === observed.branch;
    const sameBuild = sameBranch && index.steam.build_id === observed.build_id;
    freshness = `Latest observed ${observed.branch} build ${observed.build_id} · Checked ${evidence.checked_at} via SteamCMD · ` +
      (sameBuild ? "Selected build matches that observation" : sameBranch ? "Selected build differs from that observation" : "Selected branch differs from that observation");
  } else if (evidence) freshness += ` · Steam check unavailable at ${evidence.checked_at}`;
  const version = index.game_version ? `Application version ${index.game_version}` : "Application version unknown";
  document.getElementById("status").textContent = `${version} · Steam build ${index.steam.build_id} · Partial coverage · Gameplay verification not performed · ${freshness}`;
  const versionEvidence = index.game_version_evidence?.[0];
  document.getElementById("status").title = versionEvidence ? `${versionEvidence.source_path} · ${versionEvidence.object_id}${versionEvidence.field} · SHA-256 ${versionEvidence.source_sha256}` : "";
}

function checkedExplanations(records) {
  const section = element("section");
  for (const note of records || []) {
    section.append(element("h3", note.title));
    if (note.status === "passed") {
      section.append(element("p", note.text), element("p", `Declared ${note.scope} checks passed.`, "badge"));
    } else {
      section.append(notice(`Unverified explanation: ${note.reasons.join("; ")}`));
    }
    if (note.last_verified) {
      const last = note.last_verified;
      section.append(element("p", `Last successful check: Steam build ${last.build_id} (${last.snapshot_id}).`, "muted"));
      if (note.status !== "passed") {
        const old = element("details");
        old.append(element("summary", "Previously checked text"), element("p", last.text));
        section.append(old);
      }
    }
    const evidence = element("details");
    evidence.append(element("summary", "Explanation checks and source evidence"), valueNode({
      definition: note.authored_source, scope: note.scope, checks: note.checks, last_successful_check: note.last_verified
    }));
    section.append(evidence);
  }
  return section;
}

async function showEntry(key) {
  const record = await keyed(index.entries, key);
  if (!record) {
    content.replaceChildren(element("h2", "Entry not cataloged for this snapshot"), notice("No observation for this wiki key is available in the selected snapshot. This does not establish that the game content was absent."));
    return;
  }
  const article = element("article");
  article.append(element("p", record.kind.replaceAll("-", " "), "eyebrow"), element("h2", record.name));
  document.title = `${record.name} | ${config.project || "Unofficial game reference"}`;
  const stamps = element("dl", undefined, "stamps");
  for (const [label, value] of [["Snapshot", snapshot], ["Status", record.status], ["Last substantive change", record.last_changed], ["Last data check", record.last_data_checked], ["Last gameplay verification", record.last_verified || "Not performed"]]) {
    stamps.append(element("dt", label), element("dd", value || "Not recorded"));
  }
  article.append(stamps);
  const history = element("details"), historyList = element("ul");
  history.append(element("summary", "View this entry in another captured snapshot"));
  const appendHistory = version => {
    const item = element("li"); item.append(link(`${version.game_version || "Version unknown"} · Steam ${version.build_id} (${version.snapshot_id})`, url(record.topic, key, version.snapshot_id))); historyList.append(item);
  };
  history.append(historyList);
  if (config.capture_catalog) history.append(capturePager(appendHistory));
  else config.versions.forEach(appendHistory);
  article.append(history);
  if (record.explanations?.length) article.append(checkedExplanations(record.explanations));
  if (record.status !== "present") {
    const messages = {"not-present": "The source object was absent from this captured catalog.", uncaptured: "The required capture or extraction scope was unavailable.", unresolved: "The earlier observation could not be safely reconciled with this snapshot.", superseded: "A reviewed identity correction superseded this key. Earlier snapshots retain their original decisions."};
    article.append(notice(messages[record.status] || "This entry has no current observation."));
    if (record.superseded_by) article.append(link("Reviewed replacement", url(record.topic, record.superseded_by)));
    content.replaceChildren(article); return;
  }
  const semantic = await keyed(index.semantics, record.revision_id);
  if (!semantic) throw new Error("The selected semantic revision is missing");
  article.append(element("p", `Evidence: ${semantic.evidence_level}`, "badge"));
  if (record.decision.status === "ambiguous") article.append(notice("Identity continuity is unresolved. This observation retains a separate wiki key; it has not been merged with a candidate."));
  const notes = Array.isArray(semantic.notes) ? semantic.notes : semantic.notes ? [semantic.notes] : [];
  for (const note of notes) article.append(notice(note));
  if (semantic.fact_scope) article.append(element("p", `Scope: ${semantic.fact_scope}`, "muted"));
  article.append(element("h3", "Extracted facts"), factsTable(semantic.facts, {semantic, record}));
  article.append(element("h3", "Relationships"));
  const relationships = element("ul", undefined, "relations");
  for (const relation of semantic.relationships) {
    const item = element("li"); item.append(element("strong", relation.predicate.replaceAll("-", " ") + ": "));
    for (const target of relation.targets) {const to = record.links[target]; item.append(link(to.name, url(to.topic, target)), document.createTextNode(" "));}
    for (const target of relation.technical_targets || []) {const to = record.links[target]; item.append(link(`Technical summary: ${to.name}`, url(to.topic, target)), document.createTextNode(" "));}
    if (!relation.targets.length && !relation.technical_targets?.length && !relation.gaps?.length) item.append(element("span", "No target recorded"));
    if (relation.gaps?.length) {const gaps = element("details"); gaps.append(element("summary", `${relation.gaps.length} unresolved or omitted targets`), valueNode(relation.gaps)); item.append(gaps);}
    item.append(element("small", `Source field: ${relation.field}`, "field")); relationships.append(item);
  }
  article.append(relationships);
  if (record.backlink_count) {
    const details = element("details"), list = element("ul"), more = element("button", "Show more references");
    details.append(element("summary", `Referenced by ${record.backlink_count} relationships`));
    const prefix = key + "/", end = prefix + "\uffff";
    const shards = shardReferences(index.backlinks, prefix, end);
    let shown = 0, finished = false, pending = [], loading = false;
    async function add() {
      if (loading) return;
      loading = true; more.disabled = true;
      try {
        while (pending.length < 50 && !finished) {
          const step = await shards.next();
          if (step.done) {finished = true; break;}
          const shard = step.value;
          const values = await json(shard.path, shard);
          pending.push(...Object.entries(values).filter(([id]) => id.startsWith(prefix)).map(([, value]) => value));
        }
        const batch = pending.splice(0, 50);
        for (const source of batch) {const li = element("li"); li.append(link(source.name, url(source.topic, source.entity)), document.createTextNode(` (${source.predicate})`)); list.append(li);}
        shown += batch.length; more.hidden = shown >= record.backlink_count;
      } catch (error) {details.append(notice(error.message));}
      finally {loading = false; more.disabled = false;}
    }
    more.addEventListener("click", add); details.addEventListener("toggle", () => {if (details.open && !shown) add();});
    details.append(list, more); article.append(details);
  }
  const evidence = element("details"); evidence.append(element("summary", "Identifiers, source evidence and identity decision"));
  evidence.addEventListener("toggle", async () => {
    if (!evidence.open || evidence.dataset.loaded) return;
    evidence.dataset.loaded = "true";
    try {
      const provenance = await keyed(index.provenance, record.provenance_id);
      evidence.append(factsTable({wiki_key: key, semantic_revision: record.revision_id, source_commit: index.source_commit, ...provenance, identity_decision: record.decision}));
    } catch (error) {evidence.append(notice(error.message)); delete evidence.dataset.loaded;}
  });
  article.append(evidence); content.replaceChildren(article);
  const external = await articleLinks(record);
  if (external) article.append(external);
}

async function articleLinks(record = null) {
  if (!config.external_articles) return null;
  const section = element("section");
  try {
    const ref = config.external_articles;
    const view = ref.path ? await json(ref.path, ref) : ref;
    if (view.schema_version !== 1) throw new Error("Unsupported external article check format");
    if (record && (record.status !== "present" || !view.kinds.includes(record.kind))) return null;
    const rows = record ? [await keyed(view.entries, snapshot + "/" + record.entity_key) || {
      status: view.default_status, reason: view.default_status === "missing" ? "No exact article title matched" : "Article index unavailable"
    }] : view.topics;
    section.append(element("h3", "Community wiki articles"));
    for (const row of rows) {
      if (row.status === "populated") {
        const target = new URL(row.url);
        if (target.protocol !== "https:" || target.username || target.password) throw new Error("Invalid community article destination");
        const paragraph = element("p"); paragraph.append(link(row.title.split(":").slice(1).join(":"), target.href)); section.append(paragraph);
      } else section.append(element("p", `${row.title || "Matching article"}: ${row.status} (${row.reason}).`, "muted"));
    }
    section.append(element("p", `Article content checked ${view.checked_at}. Links open the checked revisions; game-build compatibility is not verified.`, "muted"));
  } catch (error) {
    section.replaceChildren(notice(`Community article checks could not be loaded: ${error.message}`));
  }
  return section;
}

async function overview() {
  const title = config.topics.find(topic => topic.id === config.topic);
  const view = element("section");
  content.append(view);
  view.append(element("h2", title.title), element("p", title.coverage));
  if (config.topic === "hub") {
    view.append(notice("Choose a topic to browse its extracted reference. Coverage is partial; unresolved content remains visible in the relevant entries."));
    const cards = element("div", undefined, "cards");
    for (const topic of config.topics.filter(topic => topic.id !== "hub")) {
      const card = element("section"); card.append(link(topic.title, url(topic.id)), element("p", topic.coverage)); cards.append(card);
    }
    view.append(cards);
  } else {
    const groups = element("ul", undefined, "groups");
    for (const [kind, count] of Object.entries(index.counts)) {
      const item = element("li"); item.append(link(`${kind.replaceAll("-", " ")} (${count.toLocaleString()})`, url(config.topic, null, snapshot, kind))); groups.append(item);
    }
    view.append(groups);
    if (!groups.children.length) view.append(notice("No supported observations are available in this topic for the selected snapshot."));
  }
  const external = await articleLinks();
  if (external) view.append(external);
}

async function start() {
  config = globalThis.humanHostReader?.config || await json("reader.json");
  if (params.has("release") && params.get("release") !== (config.release_id || config.candidate_id)) throw new Error("This URL names a different reader revision. Use that revision's archived site; current content has not been substituted.");
  snapshot = params.get("snapshot") || config.default_snapshot;
  const selectedCapture = await captureFor(snapshot), pinned = selectedCapture.index;
  index = await json(pinned ? pinned.path : `snapshots/${snapshot}.json`, pinned);
  document.getElementById("home").href = url("hub");
  const selector = document.getElementById("version");
  let selectedShown = false;
  const appendVersion = version => {
    if (version.snapshot_id === snapshot) {if (selectedShown) return; selectedShown = true;}
    const option = element("option", `${version.game_version || "Version unknown"} · Steam ${version.build_id} · ${version.snapshot_id.split("-").at(-1)}`);
    option.value = version.snapshot_id; option.selected = version.snapshot_id === snapshot; selector.append(option);
  };
  if (config.capture_catalog) {
    appendVersion(selectedCapture.version);
    selector.parentElement.after(capturePager(appendVersion));
  } else config.versions.forEach(appendVersion);
  selector.addEventListener("change", () => {const target = new URL(location.href); target.searchParams.set("snapshot", selector.value); target.searchParams.set("release", config.release_id || config.candidate_id); location.assign(target);});
  for (const topic of config.topics) {const a = link(topic.title, url(topic.id)); if (topic.id === config.topic) a.setAttribute("aria-current", "page"); document.getElementById("topics").append(a);}
  for (const official of config.official_links) {document.getElementById("credits").append(link(official.title, official.url), document.createTextNode(" · "));}
  document.getElementById("search-form").addEventListener("submit", event => {event.preventDefault(); search(document.getElementById("search").value).catch(failure);});
  status();
  const path = decodeURIComponent(location.pathname.slice(routeBase.pathname.length));
  const entry = /^entry\/(e-[0-9a-f]{32})\/?$/.exec(path);
  const group = /^groups\/([a-z][a-z0-9-]*)\/(?:index\.html)?$/.exec(path);
  if (entry) await showEntry(entry[1]);
  else if (group) await search("", group[1]);
  else if (path === "" || path === "index.html") await overview();
  else throw new Error("Unknown reader route");
}

start().catch(failure);
