"use strict";

// Human Host wiki reader. Design: study 11 "Longform, home first" (ADR-0002 §7).
// All imported text is rendered through textContent. No game text becomes HTML.
const siteBase = globalThis.humanHostReader ? new URL(globalThis.humanHostReader.base) : new URL(".", document.currentScript.src);
const routeBase = globalThis.humanHostReader?.routeBase ? new URL(globalThis.humanHostReader.routeBase) : siteBase;
const resolveURL = globalThis.humanHostReader?.resolve || ((value, base) => new URL(value, base));
const params = new URLSearchParams(location.search);
const content = document.getElementById("content");
const cache = new Map();
let config, snapshot, index, searchGeneration = 0, cleanup = null;

// ---------- DOM ----------
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

// el("a", {href, class}, child, "text", [more]) builds a node; strings become text nodes, never HTML.
function el(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = String(value);
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(typeof kid === "object" ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

function svg(tag, attrs, ...kids) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined) continue;
    if (key === "text") node.textContent = String(value); else node.setAttribute(key, value);
  }
  for (const kid of kids.flat(Infinity)) if (kid) node.append(kid);
  return node;
}

function show(...nodes) {content.replaceChildren(...nodes.flat(Infinity).filter(node => node !== null && node !== undefined && node !== false));}
const reduced = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
const count = value => Number(value).toLocaleString("en");
const store = {
  get(key) {try {return localStorage.getItem(key);} catch (error) {return null;}},
  set(key, value) {try {if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value);} catch (error) { /* storage blocked: the choice lasts for this page only */ }}
};

// ---------- Content-addressed packs ----------
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

function topicOf(id) {
  const owner = config.topics.find(value => value.id === id);
  if (!owner) throw new Error(`Unknown topic ${id}`);
  return owner;
}

// Every route keeps ?snapshot= and ?release= so a link always opens the same captured version.
function url(topic, entity = null, selected = snapshot, group = null, extra = null) {
  const owner = topicOf(topic);
  const path = entity ? `entry/${encodeURIComponent(entity)}/` : group ? `groups/${encodeURIComponent(group)}/` : "";
  return address(owner, path, selected, extra);
}

function address(owner, path, selected = snapshot, extra = null) {
  const target = resolveURL(path, new URL(owner.base, location.origin));
  const query = new URLSearchParams({snapshot: selected, release: config.release_id || config.candidate_id});
  for (const [key, value] of Object.entries(extra || {})) if (value) query.set(key, value);
  target.search = query.toString();
  return target.href;
}

const hubURL = (path, extra = null) => address(topicOf("hub"), path, snapshot, extra);
const guideURL = id => hubURL(`guide/${encodeURIComponent(id)}/`);
const searchURL = (query, topic = null) => hubURL("search/", {q: query, topic});

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
      let low = null, high = null, total = 0;
      for (const child of value.shards) {
        if (typeof child.first !== "string" || typeof child.last !== "string" || child.first > child.last || !Number.isSafeInteger(child.count) || child.count < 1) throw new Error("Invalid shard directory range");
        low = low === null || child.first < low ? child.first : low;
        high = high === null || child.last > high ? child.last : high;
        total += child.count;
      }
      if (low !== ref.first || high !== ref.last || total !== ref.count) throw new Error("Shard directory summary differs");
      yield* shardReferences(value.shards, first, last, active, reverse);
    } finally {active.delete(target.href);}
  }
}

async function keyed(shards, key) {
  for await (const shard of shardReferences(shards || [], key)) {
    const value = (await json(shard.path, shard))[key];
    if (value !== undefined) return value;
  }
  return undefined;
}

async function allRows(shards) {
  const rows = [];
  // Serial pack reads keep memory and peak bandwidth bounded on large topics.
  for await (const shard of shardReferences(shards || [])) rows.push(...Object.values(await json(shard.path, shard)));
  return rows;
}

// ---------- Captured versions ----------
async function captureCatalog() {
  const root = await json(config.capture_catalog.path, config.capture_catalog);
  if (root.schema_version !== 1 || root.kind !== "wiki-capture-catalog" || !Number.isSafeInteger(root.count) || root.count < 1) throw new Error("Invalid capture catalog");
  for (const field of ["by_id", "by_order"]) {
    if (!Array.isArray(root[field])) throw new Error("Invalid capture catalog index");
    let previous = null, total = 0;
    for (const ref of root[field]) {
      if (typeof ref.first !== "string" || typeof ref.last !== "string" || ref.first > ref.last || (previous !== null && ref.first <= previous) || !Number.isSafeInteger(ref.count) || ref.count < 1) throw new Error("Invalid capture catalog range");
      previous = ref.last; total += ref.count;
    }
    if (total !== root.count) throw new Error("Capture catalog count differs");
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
    const total = config.versions.length, end = before === null ? total : before;
    return config.versions.slice(total - end, total - end + limit).map((version, position) => ({version, ordinal: end - position - 1}));
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
  const box = element("div"), more = element("button", "Show more versions"), message = element("p", "");
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

function versionLabel(version) {
  return `${version.game_version ? `Version ${version.game_version}` : "Version unknown"} · Steam build ${version.build_id}`;
}

// ---------- Shared pieces ----------
function notice(text) {
  return element("p", text, "notice");
}

function failure(error) {
  content.replaceChildren(element("h2", "This page could not be loaded"), notice(error.message));
  document.getElementById("status").textContent = "Reader failure. No different captured version was substituted.";
}

const kindLabel = kind => {
  const text = String(kind || "").replaceAll("-", " ");
  return text ? text[0].toUpperCase() + text.slice(1) : text;
};
const site = () => config.site || {topics: {}, guides: [], home: {}};
const topicShort = id => site().topics?.[id]?.short || topicOf(id).title;
const topicColor = id => site().topics?.[id]?.color || "#1a1a1a";
const swatch = id => el("span", {class: "sw", style: `background:${topicColor(id)}`, "aria-hidden": "true"});

// Runs are guide and card text: plain strings, some linked to an entry. links maps entity -> {name, topic}.
function runsNode(runs, links = {}) {
  const node = document.createDocumentFragment ? document.createDocumentFragment() : element("span");
  for (const run of runs || []) {
    const target = run.entity && links[run.entity];
    node.append(target ? link(run.text, url(target.topic, run.entity)) : document.createTextNode(run.text));
  }
  return node;
}
const runsText = runs => (runs || []).map(run => run.text).join("");

// Ranked multi-word search from study 11: every word must match; exact, prefix and word-start matches rank first.
const norm = text => String(text || "").toLocaleLowerCase("en").normalize("NFKD").replace(/[̀-ͯ]/g, "");
function rank(rows, query, options = {}) {
  const words = norm(query).split(/\s+/).filter(Boolean), whole = norm(query).trim(), out = [];
  for (const row of rows) {
    if (options.topic && row.topic !== options.topic) continue;
    if (options.kind && row.kind !== options.kind) continue;
    const name = norm(row.name), hay = `${name} ${norm(row.source_name)} ${norm(row.kind)} ${row.entity_key}`;
    if (!words.every(word => hay.includes(word))) continue;
    let score = !whole ? 0 : name === whole ? 100 : name.startsWith(whole) ? 80
      : words.every(word => name.split(/[\s_().,-]+/).some(part => part.startsWith(word))) ? 60 : words.every(word => name.includes(word)) ? 40 : 10;
    if (whole && words.every(word => name.split(/[\s()]+/).includes(word))) score += 10;
    // Players look for things they can hold: items lead a tie, and game-file records come after every player entry.
    if (row.kind === "item") score += 5;
    const tier = row.topic === "technical-reference" || row.kind === "asset" || row.kind === "configuration" ? 1 : 0;
    out.push({...row, score, tier});
  }
  out.sort((a, b) => a.tier - b.tier || b.score - a.score || a.name.localeCompare(b.name, "en") || a.entity_key.localeCompare(b.entity_key));
  return out;
}

function highlight(text, query) {
  const words = norm(query).split(/\s+/).filter(Boolean), node = el("span");
  if (!words.length) {node.textContent = text; return node;}
  const low = norm(text), marks = new Array(text.length).fill(false);
  for (const word of words) {let at = low.indexOf(word); while (at >= 0) {for (let i = at; i < at + word.length; i++) marks[i] = true; at = low.indexOf(word, at + 1);}}
  for (let i = 0; i < text.length;) {
    const on = marks[i]; let j = i; while (j < text.length && marks[j] === on) j++;
    node.append(on ? el("mark", {}, text.slice(i, j)) : document.createTextNode(text.slice(i, j))); i = j;
  }
  return node;
}

// The top line says only what a player needs: when the wiki was updated, and which game it describes.
// The update date is the pipeline's last Steam check, the one date every release records.
function status() {
  const checked = Date.parse(config.availability?.checked_at || "");
  const updated = Number.isNaN(checked) ? null : new Date(checked).toLocaleDateString("en-US", {year: "numeric", month: "short", day: "numeric"});
  const latest = snapshot === config.default_snapshot;
  const lead = latest ? (updated ? `Updated ${updated}` : null) : "Older version";
  const node = document.getElementById("status");
  // No-break spaces keep each part whole when the line wraps on a phone.
  node.textContent = [lead, `Game version ${index.game_version || "unknown"}`, `Steam build ${index.steam.build_id}`]
    .filter(Boolean).map(part => part.replaceAll(" ", " ")).join(" · ");
  if (!latest) document.getElementById("version").closest?.("details")?.setAttribute("open", "");
  const versionEvidence = index.game_version_evidence?.[0];
  node.title = versionEvidence ? `${versionEvidence.source_path} · ${versionEvidence.object_id}${versionEvidence.field} · SHA-256 ${versionEvidence.source_sha256}` : "";
}

// ---------- Technical reference (raw fields, verbatim) ----------
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
    list.append(element("dt", Array.isArray(value) ? `[${key}]` : key));
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
    list.append(element("dt", field), description);
  }
  return list;
}

function checkedExplanations(records) {
  const section = element("section");
  for (const note of records || []) {
    section.append(element("h3", note.title));
    if (note.status === "passed") section.append(element("p", note.text), element("p", `Declared ${note.scope} checks passed.`, "badge"));
    else section.append(notice(`Unverified explanation: ${note.reasons.join("; ")}`));
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
    section.append(element("p", `Checked ${view.checked_at.slice(0, 10)}. Community pages may describe a different game version; the wiki does not check them against this one.`, "muted"));
  } catch (error) {
    section.replaceChildren(notice(`Community article checks could not be loaded: ${error.message}`));
  }
  return section;
}

// ---------- Entry: the player card first, the technical record folded away ----------
function statValue(stat, links) {
  const value = stat.display;
  if (value === null || value === undefined) return el("dd", {}, "Yes");
  if (!Array.isArray(value)) return el("dd", {}, String(value));
  // Lists: recipe ingredients ({name, count, target}) or handmade ammo ({material, effects}).
  return el("dd", {}, el("ul", {}, value.map(item => {
    if (item && "material" in item) return el("li", {}, el("b", {}, item.material), item.effects.length ? `: ${item.effects.map(effect => `${effect.label} ${effect.value}`).join(", ")}` : ": no change");
    if (item && "count" in item) {
      const target = item.target && links[item.target];
      const name = item.name || "Unknown ingredient";
      return el("li", {}, `${item.count} × `, target ? link(name, url(target.topic, item.target)) : name);
    }
    return el("li", {}, String(item));
  })));
}

function playerCard(card, player, record) {
  const links = {...(record.links || {}), ...(player?.links || {})};
  const parts = [];
  if (card?.stats?.length) {
    parts.push(el("dl", {class: "stats"}, card.stats.map(stat => el("div", {class: Array.isArray(stat.display) ? "stat wide" : "stat"}, el("dt", {}, stat.label), statValue(stat, links)))));
  }
  const side = [];
  // Guide phrases start lowercase to sit mid-sentence; as standalone list items they start with a capital.
  const capitalized = runs => runs.map((run, i) => i ? run : {...run, text: run.text.charAt(0).toUpperCase() + run.text.slice(1)});
  if (player?.how?.length) side.push(el("section", {}, el("h2", {}, "How to get it"), el("ul", {class: "how"}, player.how.map(runs => el("li", {}, runsNode(capitalized(runs), links))))));
  if (player?.used_in?.count) {
    const more = player.used_in.count - player.used_in.items.length;
    side.push(el("section", {}, el("h2", {}, "Used to make ", el("small", {}, count(player.used_in.count))), el("ul", {class: "uses"}, player.used_in.items.map(runs => el("li", {}, runsNode(Array.isArray(runs) ? runs : [runs], links)))),
      more > 0 ? el("p", {class: "muted"}, `and ${count(more)} more`) : null));
  }
  if (card?.notes?.length) side.push(el("section", {}, card.notes.map(note => el("p", {class: "gamenote"}, el("b", {}, "In the game"), note.text))));
  if (!parts.length && !side.length) return null;
  return el("div", {class: "card"}, el("div", {}, parts), el("div", {class: "facts-side"}, side));
}

async function showEntry(key) {
  const record = await keyed(index.entries, key);
  if (!record) {
    show(el("div", {class: "entry"}, el("h1", {class: "hed"}, "Not in this version"), notice("Nothing with this wiki key was captured in the selected game version. That does not mean the game lacks it.")));
    return;
  }
  const semantic = record.status === "present" ? await keyed(index.semantics, record.revision_id) : null;
  if (record.status === "present" && !semantic) throw new Error("The selected semantic revision is missing");
  const [card, player] = await Promise.all([record.card_id ? keyed(index.cards, record.card_id) : null, record.player_id ? keyed(index.player, record.player_id) : null]);
  const name = player?.name || record.name;
  document.title = `${name} | ${config.project || "Unofficial game reference"}`;
  const head = el("header", {class: "entry-head"},
    el("p", {class: "kicker"}, link(topicOf(record.topic).title, url(record.topic)), ` · ${kindLabel(record.kind)}`),
    el("h1", {class: "hed"}, name),
    // The game's file name stays in the technical reference; the header says only that the wiki chose the name.
    player?.name_source === "wiki" ? el("p", {class: "note"}, el("span", {class: "wikiname"}, "Wiki name"), " The game shows no name for this, so the wiki named it.") : null,
    card?.eyebrow?.length ? el("ul", {class: "eyebrow", "aria-label": "Type"}, card.eyebrow.map(word => el("li", {}, word))) : null,
    player?.ring?.label ? el("p", {}, el("span", {class: "ringchip", title: "The first ring of the world where you can reliably get it"}, player.ring.label)) : null);
  const body = [head];
  if (record.status !== "present") {
    const messages = {"not-present": "This was not in the game files of the selected version.", uncaptured: "This part of the game files was not captured for the selected version.", unresolved: "This could not be matched safely with the selected version.", superseded: "A reviewed correction replaced this entry."};
    body.push(notice(messages[record.status] || "This entry has no data in the selected version."));
    if (record.superseded_by) body.push(el("p", {}, link("Go to the replacement", url(record.topic, record.superseded_by))));
    show(el("article", {class: "entry"}, body));
    return;
  }
  if (record.decision.status === "ambiguous") body.push(notice("This may be the same thing as another entry from an older version. The wiki keeps them apart until that is settled."));
  // A feature the game ships switched off (merchants in 0.8.316) is in the files but not in play.
  if (player?.unreleased) {
    const feature = String(player.unreleased).replace(/-/g, " ");
    body.push(notice(`Not in the game yet. ${feature[0].toUpperCase()}${feature.slice(1)} are in the game's files but switched off in this version, so you cannot get this in play.`));
  }
  body.push(playerCard(card, player, record));
  const reference = await technicalReference(record, semantic, card), view = el("article", {class: "entry"}, body, reference, reportLine(name));
  show(view);
  // Community article checks are optional: they never delay the page, and attach only while it is still shown.
  const external = await articleLinks(record);
  if (external && content.children[0] === view) reference.append(external);
}

// The accuracy form's fields (presentation/issue-templates/accuracy.yml) fill from the query string.
function reportLine(name) {
  const form = site().issues?.accuracy;
  if (!form) return null;
  const fields = new URLSearchParams({title: `Wrong on the wiki: ${name}`, page: location.href,
    version: `${index.game_version || "unknown"} (Steam build ${index.steam?.build_id || "unknown"})`});
  return el("p", {class: "report-line"}, "Something wrong or missing here? ", el("a", {href: `${form}&${fields}`, rel: "noopener"}, "Report it on GitHub"), " (needs a free GitHub account).");
}

async function technicalReference(record, semantic, card) {
  const key = record.entity_key, box = el("details", {class: "techref"});
  const facts = Object.keys(semantic.facts).length;
  box.append(el("summary", {}, "Game file details", el("small", {}, `${count(facts)} game fields, links and sources`)));
  const stamps = el("dl", {class: "stamps"});
  for (const [label, value] of [["Wiki key", key], ["Game file name", record.name], ["Captured version", snapshot], ["Status", record.status], ["Last substantive change", record.last_changed], ["Last data check", record.last_data_checked], ["Checked in play", record.last_verified || "Not yet"], ["Evidence", semantic.evidence_level]]) {
    stamps.append(el("dt", {}, label), el("dd", {}, value || "Not recorded"));
  }
  box.append(stamps);
  if (record.explanations?.length) box.append(el("h3", {}, "Checked notes"), checkedExplanations(record.explanations));
  const notes = Array.isArray(semantic.notes) ? semantic.notes : semantic.notes ? [semantic.notes] : [];
  for (const note of notes) box.append(notice(note));
  if (semantic.fact_scope) box.append(el("p", {class: "muted"}, `Scope: ${semantic.fact_scope}`));
  box.append(el("h3", {}, "Game fields"), el("p", {class: "muted"}, "Field names exactly as the game files store them."), factsTable(semantic.facts, {semantic, record}));
  if (card?.hidden?.length) box.append(el("p", {class: "muted"}, `Not shown on the card because the game never reads them: ${card.hidden.map(field => field.slice(1)).join(", ")}.`));
  const relationships = el("ul", {class: "relations"});
  for (const relation of semantic.relationships) {
    const item = el("li", {}, el("b", {}, relation.predicate.replaceAll("-", " ") + ": "));
    for (const target of relation.targets) {const to = record.links[target]; if (to) item.append(link(to.name, url(to.topic, target)), document.createTextNode(" "));}
    for (const target of relation.technical_targets || []) {const to = record.links[target]; if (to) item.append(link(`Technical summary: ${to.name}`, url(to.topic, target)), document.createTextNode(" "));}
    if (!relation.targets.length && !relation.technical_targets?.length && !relation.gaps?.length) item.append(element("span", "No target recorded"));
    if (relation.gaps?.length) {const gaps = element("details"); gaps.append(element("summary", `${relation.gaps.length} unresolved or omitted targets`), valueNode(relation.gaps)); item.append(gaps);}
    item.append(element("small", relation.field, "field")); relationships.append(item);
  }
  if (semantic.relationships.length) box.append(el("h3", {}, "Links in the game files"), relationships);
  if (record.backlink_count) box.append(backlinks(key, record.backlink_count));
  const evidence = el("details", {}, el("summary", {}, "Source evidence and identity decision"));
  evidence.addEventListener("toggle", async () => {
    if (!evidence.open || evidence.dataset.loaded) return;
    evidence.dataset.loaded = "true";
    try {
      const provenance = await keyed(index.provenance, record.provenance_id);
      evidence.append(factsTable({wiki_key: key, semantic_revision: record.revision_id, source_commit: index.source_commit, ...provenance, identity_decision: record.decision}));
    } catch (error) {evidence.append(notice(error.message)); delete evidence.dataset.loaded;}
  });
  box.append(el("h3", {}, "Sources"), evidence);
  const history = el("details", {}, el("summary", {}, "Open this entry in another captured version")), historyList = el("ul");
  const appendHistory = version => historyList.append(el("li", {}, link(versionLabel(version), url(record.topic, key, version.snapshot_id))));
  history.append(historyList);
  if (config.capture_catalog) history.append(capturePager(appendHistory)); else config.versions.forEach(appendHistory);
  box.append(el("h3", {}, "Other versions"), history);
  return box;
}

function backlinks(key, total) {
  const details = el("details"), list = el("ul", {class: "relations"}), more = el("button", {class: "more"}, "Show more");
  details.append(el("summary", {}, `Referenced by ${count(total)} links`));
  const prefix = key + "/", end = prefix + "￿", shards = shardReferences(index.backlinks, prefix, end);
  let shown = 0, finished = false, pending = [], loading = false;
  async function add() {
    if (loading) return;
    loading = true; more.disabled = true;
    try {
      while (pending.length < 50 && !finished) {
        const step = await shards.next();
        if (step.done) {finished = true; break;}
        const values = await json(step.value.path, step.value);
        pending.push(...Object.entries(values).filter(([id]) => id.startsWith(prefix)).map(([, value]) => value));
      }
      for (const source of pending.splice(0, 50)) list.append(el("li", {}, link(source.name, url(source.topic, source.entity)), ` (${source.predicate.replaceAll("-", " ")})`));
      shown = list.children.length; more.hidden = shown >= total;
    } catch (error) {details.append(notice(error.message));}
    finally {loading = false; more.disabled = false;}
  }
  more.addEventListener("click", add); details.addEventListener("toggle", () => {if (details.open && !shown) add();});
  details.append(list, more);
  return details;
}

// ---------- Topic index ----------
async function topicIndex(group) {
  const topic = topicOf(config.topic), query = params.get("q") || "", rows = await allRows(index.search);
  const all = rank(rows, query, {kind: group});
  const initial = row => {const c = (row.name || "#")[0].toUpperCase(); return /[A-Z]/.test(c) ? c : "#";};
  const present = new Set(all.map(initial)), letter = params.get("l") || (query || all.length <= 400 ? "" : [...present].sort()[0]);
  const shown = (letter ? all.filter(row => initial(row) === letter) : all).slice(0, 900);
  if (!query) shown.sort((a, b) => a.name.localeCompare(b.name, "en"));
  const input = el("input", {type: "search", value: query, "aria-label": `Search ${topic.title}`});
  const here = (extra = {}) => group ? url(config.topic, null, snapshot, group, extra) : address(topic, "", snapshot, extra);
  const columns = el("div", {class: "idx"});
  let current = null;
  for (const row of shown) {
    const head = query ? null : initial(row);
    if (head && head !== current) {current = head; columns.append(el("h2", {}, head));}
    columns.append(el("p", {}, el("a", {href: url(config.topic, row.entity_key)}, highlight(row.name, query)), " ", el("small", {}, kindLabel(row.kind))));
  }
  document.title = `${topic.title} | ${config.project || "Unofficial game reference"}`;
  const view = el("div", {class: "index"},
    el("p", {class: "kicker"}, "Topic"),
    el("h1", {class: "hed"}, group ? `${topic.title}: ${kindLabel(group).toLowerCase()}` : topic.title),
    el("p", {class: "dek"}, topic.coverage),
    el("ul", {class: "kinds", "aria-label": "Kinds"}, el("li", {}, el("a", {href: address(topic, "", snapshot), "aria-current": group ? null : "true"}, "Everything ", el("small", {}, count(Object.values(index.counts || {}).reduce((a, b) => a + b, 0))))),
      Object.entries(index.counts || {}).map(([kind, total]) => el("li", {}, el("a", {href: url(config.topic, null, snapshot, kind), "aria-current": kind === group ? "true" : null}, `${kindLabel(kind)} `, el("small", {}, count(total)))))),
    el("form", {role: "search", "aria-label": `Search ${topic.title}`, onsubmit: event => {event.preventDefault(); location.assign(here({q: input.value.trim()}));}}, input, el("button", {}, "Search")),
    query ? null : el("nav", {class: "letters", "aria-label": "Letters"}, ["#", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ"].map(c => present.has(c) ? el("a", {href: here({l: c}), "aria-current": c === letter ? "true" : null}, c) : el("span", {}, c)), letter ? el("a", {href: here({l: ""})}, "all") : null),
    el("p", {class: "note", role: "status"}, `${count(all.length)} ${query ? `matches for “${query}”` : "entries"}${letter ? `, ${count(shown.length)} under ${letter}` : ""}${shown.length === 900 ? " (first 900)" : ""}.`),
    columns);
  show(view);
  // Optional and slow: attach the topic's community wiki articles only while this view is still shown.
  const external = await articleLinks();
  if (external && content.children[0] === view) view.append(external);
}

// ---------- Hub: search across every topic ----------
async function hubSearch() {
  const query = params.get("q") || "", only = params.get("topic") || null, rows = await allRows(index.search);
  const found = rank(rows, query, {topic: only});
  const facets = {};
  for (const row of rank(rows, query)) facets[row.topic] = (facets[row.topic] || 0) + 1;
  const input = el("input", {type: "search", value: query, "aria-label": "Search the wiki"});
  const list = el("ol", {class: "results"});
  let shown = 0;
  const more = el("button", {class: "more"}, "Show more");
  const add = () => {
    for (const row of found.slice(shown, shown + 100)) list.append(el("li", {}, swatch(row.topic), " ", el("a", {href: url(row.topic, row.entity_key)}, highlight(row.name, query)), " ", el("small", {}, `${kindLabel(row.kind)} · ${topicShort(row.topic)}`)));
    shown += 100; more.hidden = shown >= found.length;
  };
  more.addEventListener("click", add); add();
  document.title = `${query ? `Search: ${query}` : "Search"} | ${config.project || "Unofficial game reference"}`;
  show(el("div", {class: "index"},
    el("p", {class: "kicker"}, "Search"),
    el("h1", {class: "hed"}, query ? `“${query}”` : "Search the wiki"),
    el("form", {role: "search", "aria-label": "Search again", onsubmit: event => {event.preventDefault(); location.assign(searchURL(input.value.trim(), only));}}, input, el("button", {}, "Search")),
    el("ul", {class: "kinds", "aria-label": "Topics"}, el("li", {}, el("a", {href: searchURL(query), "aria-current": only ? null : "true"}, "All topics ", el("small", {}, count(Object.values(facets).reduce((a, b) => a + b, 0))))),
      Object.entries(facets).sort((a, b) => b[1] - a[1]).map(([id, total]) => el("li", {}, el("a", {href: searchURL(query, id), "aria-current": id === only ? "true" : null}, swatch(id), ` ${topicShort(id)} `, el("small", {}, count(total)))))),
    el("p", {class: "note", role: "status"}, `${count(found.length)} ${found.length === 1 ? "match" : "matches"}.`),
    list, more));
}

// ---------- Hub: guides ----------
async function guidePage(id) {
  const row = (index.guides || []).find(value => value.id === id);
  if (!row) {show(el("div", {class: "intro"}, el("h1", {class: "hed"}, "Guide not found"), notice("This guide is not part of the selected game version.")));  return;}
  const pack = await json(row.path, row), doc = pack.document, links = pack.links || {};
  document.title = `${doc.title} | ${config.project || "Unofficial game reference"}`;
  const toc = el("ol");
  const sections = doc.sections.map(section => {
    const heading = runsText(section.heading), ring = /^ring-(\d+)$/.exec(section.id);
    const {number, place} = biomeHeading(heading, section.id);
    toc.append(el("li", {}, el("a", {href: `#${section.id}`, "data-section": section.id}, ring ? `Biome ${number}: ${place}` : heading)));
    return el("section", {class: "gsec", id: section.id, "data-ring": ring ? `Biome ${number}: ${place}` : null, "aria-labelledby": `${section.id}-h`},
      el("h2", {id: `${section.id}-h`}, ring ? [el("span", {class: "no", "aria-hidden": "true"}, number), place] : heading),
      section.blocks.map(block => guideBlock(block, links, `${doc.id}/${section.id}`)));
  });
  const rings = doc.sections.filter(section => /^ring-\d+$/.test(section.id));
  // Folded on phones so the guide itself starts on the first screen.
  const wide = typeof matchMedia !== "function" || matchMedia("(min-width: 861px)").matches;
  const aside = el("aside", {class: "guide-toc", "aria-label": "In this guide"},
    el("details", {open: wide}, el("summary", {}, el("h2", {}, "In this guide")), toc), rings.length ? ringDiagram(rings) : null);
  show(el("article", {},
    el("header", {class: "intro"}, el("p", {class: "kicker"}, link("Guides", hubURL("") + "#guides")), el("h1", {class: "hed"}, doc.title), doc.dek ? el("p", {class: "dek"}, doc.dek) : null,
      el("p", {class: "byline"}, `Written by the wiki from the game's files: version ${index.game_version || "unknown"}, Steam build ${index.steam.build_id}. It is rebuilt with every game update.`)),
    el("div", {class: "guide"}, el("div", {class: "guide-body"}, sections), aside)));
  trackSections(aside);
}

// A biome section's number and place name. The heading carries the game's 1-based biome number;
// section ids keep the 0-based index. Guides built before the renumbering say "Ring 0" and
// counted from 0, so those add one.
function biomeHeading(heading, id) {
  const named = /^(Ring|Biome) (\d+):\s*(.*)$/.exec(heading), ring = /^ring-(\d+)$/.exec(id);
  const number = named ? String(Number(named[2]) + (named[1] === "Ring" ? 1 : 0)) : ring ? String(Number(ring[1]) + 1) : "";
  return {number, place: named ? named[3] : heading};
}

function guideBlock(block, links, scope) {
  const title = block.title ? el("h3", {}, block.title) : null;
  if (block.runs && block.type !== "sentence" && block.type !== "sources") return [title, el("p", {class: "muted"}, runsNode(block.runs, links))];
  if (block.type === "sentence") return el("p", {}, runsNode(block.runs, links));
  if (block.type === "sources") return el("p", {class: "gsources"}, runsNode(block.runs, links));
  const groups = block.groups || [{items: block.items, rows: block.rows}];
  return [title, groups.map(group => [
    group.label ? el(title ? "h4" : "h3", {}, runsNode(group.label, links)) : null,
    block.type === "table"
      ? guideTable(block.columns, group.rows || [], links, [block.title, group.label && runsText(group.label)].filter(Boolean).join(": ") || block.columns.join(", "))
      : guideItems(block.type, group.items || [], links, scope),
    group.more?.length ? el("p", {class: "gmore"}, runsNode(group.more, links)) : null])];
}

function guideItems(type, items, links, scope) {
  if (type === "definitions") {
    return el("dl", {class: "gdefs"}, items.map(runs => {
      const text = runsText(runs), cut = text.indexOf(": ");
      return cut > 0 ? [el("dt", {}, text.slice(0, cut)), el("dd", {}, text.slice(cut + 2))] : [el("dt", {}, ""), el("dd", {}, runsNode(runs, links))];
    }));
  }
  if (type === "checklist") {
    return el("ul", {class: "gcheck"}, items.map((runs, position) => {
      const id = `c-${scope}-${position}`.replace(/[^a-z0-9-]/gi, "-"), memory = `hhw-check:${scope}:${runsText(runs)}`;
      const box = el("input", {type: "checkbox", id, checked: store.get(memory) === "1"});
      box.addEventListener("change", () => store.set(memory, box.checked ? "1" : null));
      return el("li", {}, box, el("label", {for: id}, runsNode(runs, links)));
    }));
  }
  // One span per item: a step is a two-column grid (number, text), so loose runs would each take a cell.
  return el(type === "steps" ? "ol" : "ul", {class: type === "steps" ? "gsteps" : "glist"}, items.map(runs => el("li", {}, el("span", {}, runsNode(runs, links)))));
}

function guideTable(columns, rows, links, label) {
  const numeric = columns.map(column => rows.length > 0 && rows.every(row => /^[\d.,%×+\- ]*$/.test(runsText(row[column]))));
  return el("div", {class: "tbl-wrap", tabindex: "0", role: "region", "aria-label": label || "Table"},
    el("table", {class: "tbl"}, el("thead", {}, el("tr", {}, columns.map((column, i) => el("th", {scope: "col", class: numeric[i] ? "num" : null}, column)))),
      el("tbody", {}, rows.map(row => el("tr", {}, columns.map((column, i) => el(i ? "td" : "th", {scope: i ? null : "row", class: numeric[i] ? "num" : null}, runsNode(row[column], links))))))));
}

// The progression guide's ring map: concentric bands, the band being read lights up.
function ringDiagram(rings) {
  const size = 220, center = size / 2, step = (center - 14) / rings.length, drawing = svg("svg", {viewBox: `0 0 ${size} ${size}`, role: "img", "aria-label": `${rings.length} rings around the spawn point`});
  rings.forEach((section, i) => {
    const band = svg("circle", {cx: center, cy: center, r: (14 + step * (i + .5)).toFixed(1), "stroke-width": (step - 2).toFixed(1), class: "ring-band", "data-section": section.id});
    drawing.append(band);
  });
  drawing.append(svg("circle", {cx: center, cy: center, r: 5, class: "ring-spawn"}));
  const caption = el("p", {class: "gcap"}, "Spawn point in the centre. Each band is one biome.");
  return el("figure", {class: "guide-rings"}, drawing, caption);
}

function trackSections(aside) {
  const links = [...aside.querySelectorAll("a[data-section]")], bands = [...aside.querySelectorAll("circle[data-section]")], caption = aside.querySelector(".gcap");
  const resting = caption ? caption.textContent : "";
  scrollSpy([...content.querySelectorAll(".gsec")], section => {
    const id = section.id;
    for (const a of links) a.setAttribute("aria-current", a.dataset.section === id ? "true" : "false");
    for (const band of bands) band.classList.toggle("on", band.dataset.section === id);
    // Outside the ring sections the map rests, so it never names a ring the reader has left.
    if (caption) caption.textContent = section.dataset.ring || resting;
  }, .3);
}

// The active target is the last one whose top has passed the reading line. It is recomputed on
// every scrolled frame, so a fast scroll cannot skip a section the way a threshold observer can.
// Several can run at once (one per chart); each stops itself once its targets leave the page.
function scrollSpy(targets, onActive, line) {
  if (!targets.length || typeof addEventListener !== "function" || typeof requestAnimationFrame !== "function") return;
  let frame = 0, current = null;
  const stop = () => {removeEventListener("scroll", queue); removeEventListener("resize", queue); if (frame) cancelAnimationFrame(frame); frame = 0;};
  const check = () => {
    frame = 0;
    if (!targets[0].isConnected) {stop(); return;}
    const reading = innerHeight * line;
    let active = targets[0];
    for (const target of targets) {if (target.getBoundingClientRect().top <= reading) active = target; else break;}
    if (active !== current) {current = active; onActive(active);}
  };
  const queue = () => {if (!frame) frame = requestAnimationFrame(check);};
  addEventListener("scroll", queue, {passive: true});
  addEventListener("resize", queue);
  queue();
}

// ---------- Hub: home (study 11) ----------
function quickSearch(rowsPromise) {
  const input = el("input", {type: "search", id: "hq", placeholder: "Search items, recipes, creatures…", autocomplete: "off", "aria-describedby": "hq-status"});
  const list = el("ul", {class: "suggest", id: "hq-list", hidden: true}), live = el("p", {class: "sr-only", id: "hq-status", role: "status"});
  const close = () => {list.hidden = true;};
  const update = async () => {
    const query = input.value.trim();
    if (!query) {close(); live.textContent = ""; return;}
    const found = rank(await rowsPromise, query), top = found.slice(0, 7);
    if (input.value.trim() !== query) return;
    list.replaceChildren(...(top.length ? top.map(row => el("li", {}, el("a", {href: url(row.topic, row.entity_key)}, swatch(row.topic), highlight(row.name, query), el("small", {}, `${kindLabel(row.kind)} · ${topicShort(row.topic)}`))))
      : [el("li", {class: "empty"}, "No matches.")]), el("li", {}, el("a", {class: "all", href: searchURL(query)}, el("span"), el("span", {}, `See all ${count(found.length)} →`), el("small"))));
    list.hidden = false;
    live.textContent = `${found.length} matches. Press the down arrow to browse them.`;
  };
  input.addEventListener("input", () => update().catch(failure));
  input.addEventListener("focus", () => update().catch(failure));
  const box = el("div", {class: "qs"});
  box.addEventListener("keydown", event => {
    const anchors = [...list.querySelectorAll("a")], at = anchors.indexOf(document.activeElement);
    if (event.key === "Escape") {close(); input.focus();}
    else if (event.key === "ArrowDown" && !list.hidden) {event.preventDefault(); (anchors[at + 1] || anchors[0]).focus();}
    else if (event.key === "ArrowUp" && at >= 0) {event.preventDefault(); (at ? anchors[at - 1] : input).focus();}
  });
  box.addEventListener("focusout", event => {if (!box.contains(event.relatedTarget)) close();});
  box.append(el("form", {role: "search", "aria-label": "Quick search", onsubmit: event => {event.preventDefault(); location.assign(searchURL(input.value.trim()));}},
    el("label", {class: "sr-only", for: "hq"}, "Search the wiki"), input, el("button", {}, "Search")), list, live);
  return box;
}

function home() {
  const design = site(), counts = index.topic_counts || {};
  const topics = config.topics.filter(topic => topic.id !== "hub").sort((a, b) => (counts[b.id]?.total || 0) - (counts[a.id]?.total || 0));
  const total = topics.reduce((sum, topic) => sum + (counts[topic.id]?.total || 0), 0);
  let loaded = null;
  const rowsPromise = {then: (ok, fail) => (loaded ||= allRows(index.search)).then(ok, fail)};
  const label = topic => `${topic.title}, ${count(counts[topic.id]?.total || 0)} entries`;
  const guides = index.guides || [];
  const tlist = el("ul", {class: "tlist", "aria-label": "Topics", id: "topics-list"}), rows = {};
  for (const topic of topics) tlist.append(el("li", {}, rows[topic.id] = el("a", {href: url(topic.id), "aria-label": label(topic)}, swatch(topic.id), el("span", {}, topicShort(topic.id)), el("small", {}, count(counts[topic.id]?.total || 0)))));
  const map = topicMap(topics, counts, rows);
  document.title = config.project || "Unofficial game reference";
  show(
    el("section", {class: "hero", "aria-labelledby": "home-h"},
      el("div", {},
        el("p", {class: "kicker"}, design.home?.kicker || "The catalogue"),
        el("h1", {id: "home-h"}, design.home?.title || config.project),
        el("p", {class: "lede"}, (design.home?.lede || "{records} records.").replace("{records}", count(total))),
        quickSearch(rowsPromise),
        design.home?.try?.length ? el("p", {class: "try"}, "Try", design.home.try.map(name => el("a", {href: searchURL(name)}, name))) : null,
        guides.length ? el("ol", {class: "starts", "aria-label": "Guides"}, guides.map((guide, i) => el("li", {}, el("a", {href: guideURL(guide.id)}, el("span", {class: "no"}, String(i + 1)), el("span", {}, el("b", {}, guide.title), el("span", {}, guide.dek)))))) : null,
        tlist,
        el("p", {class: "byline"}, `Game version ${index.game_version || "unknown"} · Steam build ${index.steam.build_id} · values from the game's files, not yet checked in play`)),
      map.node),
    el("div", {class: "cue"}, el("p", {class: "kicker"}, "The catalogue, explained"), el("h2", {}, "The shape of the data"), "Scroll on. Each square is about a hundred entries."),
    waffle(topics, counts, total),
    biomeChart(index.biomes || [], guides),
    versionChart(index.history || [], topics),
    guides.length ? el("section", {class: "reads", id: "guides", "aria-labelledby": "guides-h"}, el("h2", {id: "guides-h"}, "Guides"),
      el("ol", {}, guides.map((guide, i) => el("li", {}, el("span", {class: "no"}, String(i + 1)), el("div", {}, el("a", {href: guideURL(guide.id)}, guide.title), el("p", {}, guide.dek)))))) : null);
  map.start();
}

// Home chart: what each biome adds, from the hub index `biomes` (the same counts as the progression guide).
function biomeChart(biomes, guides) {
  if (!biomes.length) return null;
  const guide = guides.find(item => item.id === "progression-by-biome");
  const most = Math.max(1, ...biomes.map(row => Math.max(row.new_materials || 0, row.new_recipes || 0)));
  const bar = (n, kind, words) => el("span", {class: `bbar ${kind}`},
    el("i", {style: `width:${(100 * n / most).toFixed(2)}%`}), el("small", {}, `${count(n)} ${words}`));
  const rows = biomes.map(row => {
    const names = [].concat(row.biome || []).map(value => value.name || value.text).filter(Boolean).join(" and ");
    const body = [ringGlyph(biomes.length, row.index), el("span", {class: "bname"}, el("small", {}, `Biome ${row.number}`), names),
      el("span", {class: "bbars"}, bar(row.new_materials || 0, "mat", (row.new_materials || 0) === 1 ? "raw material" : "raw materials"),
        bar(row.new_recipes || 0, "rec", (row.new_recipes || 0) === 1 ? "new recipe" : "new recipes"))];
    return el("li", {}, guide ? el("a", {class: "brow", href: `${guideURL(guide.id)}#ring-${row.index}`}, body) : el("div", {class: "brow"}, body));
  });
  return el("section", {class: "biomes", "aria-labelledby": "biomes-h"},
    el("p", {class: "kicker"}, "Out from the spawn point"), el("h2", {id: "biomes-h"}, "What each biome adds"),
    el("p", {class: "dek"}, "The raw materials each biome is the best place for, and the recipes that open up there. Open a biome for its checklist."),
    el("ol", {class: "blist"}, rows));
}

// A small copy of the guide's ring map with one band lit.
function ringGlyph(total, lit) {
  const size = 34, center = size / 2, step = (center - 3) / total, drawing = svg("svg", {viewBox: `0 0 ${size} ${size}`, "aria-hidden": "true", class: "glyph"});
  for (let i = 0; i < total; i++) drawing.append(svg("circle", {cx: center, cy: center, r: (3 + step * (i + .5)).toFixed(2), "stroke-width": (step - .6).toFixed(2), class: i === lit ? "ring-band on" : "ring-band"}));
  return drawing;
}

// Home chart: the latest capture of each game version, newest first, at most four (hub index `history`).
function versionChart(history, topics) {
  if (!history.length) return null;
  const order = topics.map(topic => topic.id), widest = Math.max(1, ...history.map(row => row.total || 0));
  const rows = history.map((row, i) => {
    const bar = el("div", {class: "vbar", style: `width:${(100 * (row.total || 0) / widest).toFixed(2)}%`});
    for (const id of order) {
      const n = row.topics?.[id] || 0;
      if (n) bar.append(el("span", {style: `flex:${n} 0 0;background:${topicColor(id)}`, title: `${topicShort(id)}: ${count(n)}`}));
    }
    const change = row.changes, older = history[i + 1];
    let delta = el("p", {class: "vdelta"}, el("small", {}, "Oldest version shown."));
    if (change && older) {
      // The topics that moved most, so a reader sees where an update landed.
      const moved = Object.entries(change.topics || {}).map(([id, c]) => [id, (c.new || 0) + (c.changed || 0) + (c.removed || 0)])
        .filter(([, n]) => n).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 2);
      delta = el("p", {class: "vdelta"}, el("b", {}, `${count(change.new || 0)} new`), ", ", el("b", {}, `${count(change.changed || 0)} changed`), " and ",
        el("b", {}, `${count(change.removed || 0)} removed`), ` since ${older.game_version || "the version below"}`,
        moved.length ? el("small", {}, `Mostly ${moved.map(([id, n]) => `${topicShort(id)} (${count(n)})`).join(" and ")}.`) : null);
    }
    return el("li", {}, el("div", {class: "vlabel"}, el("b", {}, row.game_version || "Unknown version"),
      el("small", {}, `Steam build ${row.build_id}${row.captured ? ` · captured ${row.captured}` : ""}`)),
      el("div", {class: "vchart"}, bar, el("p", {class: "vtotal"}, `${count(row.total || 0)} entries`), delta));
  });
  return el("section", {class: "versions", "aria-labelledby": "versions-h"},
    el("p", {class: "kicker"}, "Update by update"), el("h2", {id: "versions-h"}, "How the game changed"),
    el("p", {class: "dek"}, "The latest capture of each game version, newest first. Each bar is every entry in that version, coloured by topic. The counts compare the wiki's records, so they also include improvements to how the wiki reads the game files."),
    el("ol", {class: "vlist"}, rows));
}

function waffle(topics, counts, total) {
  const units = topics.flatMap(topic => Array.from({length: Math.max(1, Math.round((counts[topic.id]?.total || 0) / 100))}, () => topic.id));
  const S = 20, G = 4, COLS = 17, drawing = svg("svg", {viewBox: "0 0 600 520"}), labels = svg("g"), caption = el("p", {class: "gcap"});
  const rects = units.map(() => {const r = svg("rect", {width: S, height: S, x: 0, y: 0, class: "sq", fill: "#1a1a1a"}); drawing.append(r); return r;});
  drawing.append(labels);
  const place = (r, x, y, fill) => {r.style.transform = `translate(${x}px, ${y}px)`; r.setAttribute("fill", fill);};
  const grid = colour => {rects.forEach(r => {r.setAttribute("width", S); r.setAttribute("height", S);}); units.forEach((id, i) => place(rects[i], 60 + (i % COLS) * (S + G), 60 + Math.floor(i / COLS) * (S + G), colour(id))); labels.replaceChildren();};
  const biggest = topics[0], versions = config.versions || [];
  const states = [
    () => {grid(() => "#1a1a1a"); caption.textContent = `${units.length} squares. One square is about 100 entries.`;},
    () => {grid(topicColor); caption.textContent = "Coloured by topic, largest first.";},
    () => {
      let y = 10, k = 0; labels.replaceChildren(); const per = 18, s2 = 12, g2 = 3;
      for (const topic of topics) {
        const n = units.filter(id => id === topic.id).length;
        labels.append(svg("text", {x: 0, y: y + 10, class: "glabel", text: topicShort(topic.id)}), svg("text", {x: 0, y: y + 22, class: "glabel small", text: count(counts[topic.id]?.total || 0)}));
        for (let j = 0; j < n; j++, k++) place(rects[k], 110 + (j % per) * (s2 + g2), y + Math.floor(j / per) * (s2 + g2), topicColor(topic.id));
        y += Math.max(28, Math.ceil(n / per) * (s2 + g2) + 8);
      }
      rects.forEach(r => {r.setAttribute("width", s2); r.setAttribute("height", s2);});
      caption.textContent = "Grouped by topic. Topics under 100 entries still get one square.";
    }
  ];
  const steps = [
    step(`${count(total)} entries`, el("p", {}, "That is how much of Human Host this wiki reads from the game's own files: items, recipes, creatures, rules and the files behind them.")),
    step(`${topics.length} topics`, el("p", {}, "Every entry belongs to exactly one topic. Other topics link to it rather than copying it.")),
    step(`${topicShort(biggest.id)} is the biggest`, el("p", {}, `${topicOf(biggest.id).title} holds ${count(counts[biggest.id]?.total || 0)} entries. ${topics[1] ? `Next comes ${topicOf(topics[1].id).title}, with ${count(counts[topics[1].id]?.total || 0)}.` : ""}`),
      versions.length > 1 ? el("p", {}, `The wiki keeps every captured version: ${count(versions.length)} so far. Each page can switch to an older one.`) : null)
  ];
  return scrolly(steps, drawing, caption, i => states[i]());
}

function step(title, ...body) {return el("div", {class: "step"}, el("h2", {}, title), ...body);}

function scrolly(steps, graphic, caption, onStep) {
  const box = el("section", {class: "scrolly"}, el("div", {class: "steps"}, steps), el("div", {class: "sticky", "aria-hidden": "true"}, graphic, caption));
  let current = -1;
  const activate = i => {if (i === current || i < 0) return; current = i; steps.forEach((node, k) => node.classList.toggle("is-active", k === i)); onStep(i);};
  activate(0);
  // Steps are attached after this returns; start tracking on the next frame.
  if (typeof requestAnimationFrame === "function") requestAnimationFrame(() => scrollSpy(steps, node => activate(steps.indexOf(node)), .5));
  return box;
}

// The topic map from study 02/11: streamlines through a noise field, one vortex per topic sized by its entries.
function topicMap(topics, counts, rows) {
  const box = el("div", {class: "map"}), canvas = el("canvas", {"aria-hidden": "true"}), over = svg("svg", {"aria-hidden": "true"});
  over.append(svg("defs", {}, svg("marker", {id: "arr", viewBox: "0 0 8 8", refX: 7, refY: 4, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse"}, svg("path", {d: "M0 0 L8 4 L0 8 z", fill: "#1a1a1a"}))));
  box.append(canvas, over);
  const nodes = {}, placed = topics.filter(topic => site().topics?.[topic.id]?.map);
  const rest = [el("span", {}, "Each topic bends the lines in proportion to its size. Point at a topic, here or in the list, to see what it links to.")];
  const caption = el("p", {class: "mapcap"}, rest);
  for (const topic of placed) {
    const [x, y] = site().topics[topic.id].map;
    nodes[topic.id] = el("a", {class: "tnode", href: url(topic.id), style: `left:${x * 100}%;top:${y * 100}%`, "aria-label": `${topic.title}, ${count(counts[topic.id]?.total || 0)} entries`}, swatch(topic.id), topicShort(topic.id), el("small", {}, count(counts[topic.id]?.total || 0)));
    box.append(nodes[topic.id]);
  }
  let field = null, lines = [];
  const build = () => {
    const W = box.clientWidth, H = box.clientHeight;
    const attractors = placed.map(topic => ({id: topic.id, x: site().topics[topic.id].map[0] * W, y: site().topics[topic.id].map[1] * H, w: .5 + Math.log10((counts[topic.id]?.total || 0) + 10) / 2.2, s: (hash(topic.id) & 1) ? 1.6 : -1.6}));
    field = flowField(W, H, attractors, 7, W < 600 ? 7 : 8); lines = field.lines;
    over.setAttribute("viewBox", `0 0 ${W} ${H}`);
  };
  const focus = id => {
    over.querySelectorAll("path.thread, text, rect.thread-plate").forEach(node => node.remove());
    for (const node of [...Object.values(nodes), ...Object.values(rows)]) node.classList.remove("on", "rel");
    if (!id || !field) {paint(canvas, lines); caption.replaceChildren(...rest); return;}
    const edges = (config.relationships || []).filter(edge => (edge.from === id || edge.to === id) && nodes[edge.from] && nodes[edge.to]);
    const related = new Set(edges.map(edge => edge.from === id ? edge.to : edge.from));
    paint(canvas, lines, {focus: id});
    nodes[id]?.classList.add("on"); rows[id]?.classList.add("on");
    for (const other of related) {nodes[other].classList.add("rel"); rows[other]?.classList.add("rel");}
    caption.replaceChildren(el("span", {}, el("b", {}, `${topicOf(id).title} · ${count(counts[id]?.total || 0)} entries. `), topicOf(id).coverage.replace(/([^.])$/, "$1."), related.size ? ` Linked to ${[...related].map(topicShort).join(", ")}.` : ""));
    threads(over, box, nodes, edges, field);
  };
  for (const id of new Set([...Object.keys(nodes), ...Object.keys(rows)])) for (const node of [nodes[id], rows[id]]) {
    if (!node) continue;
    node.addEventListener("pointerenter", () => focus(id)); node.addEventListener("focus", () => focus(id));
    node.addEventListener("pointerleave", () => focus(null)); node.addEventListener("blur", () => focus(null));
  }
  const start = () => {
    requestAnimationFrame(() => {build(); reveal(canvas, lines);});
    let timer = 0; const resized = () => {clearTimeout(timer); timer = setTimeout(() => {build(); paint(canvas, lines);}, 150);};
    addEventListener("resize", resized); cleanup = () => removeEventListener("resize", resized);
  };
  return {node: el("div", {}, box, caption), start};
}

function seeded(seed) {let s = seed >>> 0 || 1; return () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296;}
function hash(text) {let h = 2166136261; for (const c of text) h = Math.imul(h ^ c.charCodeAt(0), 16777619); return h >>> 0;}

function flowField(w, h, attractors, seed, separation) {
  const R = Math.min(w, h) * .2, phase = (seed % 1000) / 160;
  const dir = (x, y) => {
    const a = 1.3 * Math.sin(x * .0042 + y * .0018 + phase) + .9 * Math.cos(y * .0051 - x * .0027) + .5 * Math.sin((x + y) * .0071 + phase);
    let vx = Math.cos(a) * .7, vy = Math.sin(a) * .7;
    for (const t of attractors) {
      const dx = x - t.x, dy = y - t.y, d2 = dx * dx + dy * dy, d = Math.sqrt(d2) + 1e-3, f = t.w * Math.exp(-d2 / (2 * R * R));
      vx += (-dy / d) * f * t.s; vy += (dx / d) * f * t.s;
    }
    const m = Math.hypot(vx, vy) || 1; return [vx / m, vy / m];
  };
  const cell = separation, cols = Math.ceil(w / cell), rowsN = Math.ceil(h / cell), grid = new Uint8Array(cols * rowsN);
  const free = (x, y) => x >= 0 && y >= 0 && x < w && y < h && !grid[Math.floor(y / cell) * cols + Math.floor(x / cell)];
  const random = seeded(seed), seeds = [];
  for (let y = cell / 2; y < h; y += cell * 1.4) for (let x = cell / 2; x < w; x += cell * 1.4) seeds.push([x + (random() - .5) * cell, y + (random() - .5) * cell]);
  for (let i = seeds.length - 1; i > 0; i--) {const j = Math.floor(random() * (i + 1)); [seeds[i], seeds[j]] = [seeds[j], seeds[i]];}
  const lines = [];
  for (const [sx, sy] of seeds) {
    if (!free(sx, sy)) continue;
    const trace = sign => {const pts = []; let x = sx, y = sy; for (let k = 0; k < 110; k++) {const [dx, dy] = dir(x, y); x += dx * 2.2 * sign; y += dy * 2.2 * sign; if (!free(x, y)) break; pts.push([x, y]);} return pts;};
    const pts = [...trace(-1).reverse(), [sx, sy], ...trace(1)];
    if (pts.length < 14) continue;
    for (const [x, y] of pts) {const c = Math.floor(y / cell) * cols + Math.floor(x / cell); if (c >= 0 && c < grid.length) grid[c] = 1;}
    const [mx, my] = pts[Math.floor(pts.length / 2)];
    let owner = null, best = Infinity;
    for (const t of attractors) {const d = Math.hypot(mx - t.x, my - t.y); if (d < best) {best = d; owner = t.id;}}
    lines.push({pts, owner, d: best});
  }
  return {lines, dir};
}

const rgba = (hex, a) => `rgba(${parseInt(hex.slice(1, 3), 16)},${parseInt(hex.slice(3, 5), 16)},${parseInt(hex.slice(5, 7), 16)},${a})`;
function paint(canvas, lines, options = {}) {
  const ctx = canvas.getContext("2d"), dpr = devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = w * dpr; canvas.height = h * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h); ctx.lineCap = "round";
  const upto = options.upto === undefined ? lines.length : options.upto;
  for (let i = 0; i < upto; i++) {
    const line = lines[i], hot = options.focus && line.owner === options.focus;
    // One ink at rest. Only the topic being inspected takes its colour.
    ctx.strokeStyle = hot ? rgba(topicColor(line.owner), .95) : options.focus ? "rgba(26,26,26,.22)" : "rgba(26,26,26,.5)";
    ctx.lineWidth = hot ? 1.3 : .75;
    ctx.beginPath(); ctx.moveTo(line.pts[0][0], line.pts[0][1]);
    for (let k = 1; k < line.pts.length; k++) ctx.lineTo(line.pts[k][0], line.pts[k][1]);
    ctx.stroke();
  }
}

function reveal(canvas, lines) {
  if (reduced()) {paint(canvas, lines); return;}
  const order = lines.slice().sort((a, b) => a.d - b.d), begin = performance.now(), duration = 1400;
  const tick = now => {const t = Math.min(1, (now - begin) / duration); paint(canvas, order, {upto: Math.floor(order.length * (1 - Math.pow(1 - t, 3)))}); if (t < 1) requestAnimationFrame(tick); else lines.splice(0, lines.length, ...order);};
  requestAnimationFrame(tick);
}

// Draw the declared links of one topic as threads that bend with the field and steer around other topics' labels.
function threads(over, box, nodes, edges, field) {
  const origin = box.getBoundingClientRect(), W = box.clientWidth, H = box.clientHeight, rects = {};
  for (const [id, node] of Object.entries(nodes)) {const b = node.getBoundingClientRect(); rects[id] = {l: b.left - origin.left, t: b.top - origin.top, r: b.right - origin.left, b: b.bottom - origin.top};}
  const grow = (r, m) => ({l: r.l - m, t: r.t - m, r: r.r + m, b: r.b + m});
  const inside = (r, [x, y]) => x >= r.l && x <= r.r && y >= r.t && y <= r.b;
  const reach = W < 600 ? 14 : 24, clear = W < 600 ? 5 : 10, bend = W < 600 ? .75 : .35;
  const at = id => {const r = rects[id]; return {x: (r.l + r.r) / 2, y: (r.t + r.b) / 2};};
  const drawn = edges.map(edge => {
    const c = at(edge.from), to = at(edge.to), avoid = Object.keys(rects).filter(id => id !== edge.from && id !== edge.to).map(id => grow(rects[id], 8));
    const src = grow(rects[edge.from], 3), dst = grow(rects[edge.to], 4);
    const ux = to.x - c.x, uy = to.y - c.y, k0 = Math.min(ux ? ((ux > 0 ? src.r : src.l) - c.x) / ux : Infinity, uy ? ((uy > 0 ? src.b : src.t) - c.y) / uy : Infinity);
    const from = {x: c.x + ux * k0, y: c.y + uy * k0}, d0 = Math.hypot(to.x - from.x, to.y - from.y) || 1;
    const walk = dodge => {
      const pts = [[from.x, from.y]]; let x = from.x, y = from.y;
      for (let k = 0; k < 700; k++) {
        const dx = to.x - x, dy = to.y - y, d = Math.hypot(dx, dy); if (d < 4 || inside(dst, [x, y])) return pts;
        const progress = Math.min(1, Math.max(0, 1 - d / d0)), fw = Math.min(.45, (1 - bend) * .7) * Math.sin(Math.PI * progress) * Math.max(0, 1 - k / 500);
        const [fx, fy] = field.dir(x, y);
        let vx = fx * fw + dx / d * (1 - fw), vy = fy * fw + dy / d * (1 - fw);
        if (x < 12) vx += (12 - x) / 6; if (x > W - 12) vx -= (x - W + 12) / 6; if (y < 12) vy += (12 - y) / 6; if (y > H - 12) vy -= (y - H + 12) / 6;
        if (dodge) for (const r of avoid) {
          const cx = (r.l + r.r) / 2, cy = (r.t + r.b) / 2, nx = Math.min(Math.max(x, r.l), r.r), ny = Math.min(Math.max(y, r.t), r.b);
          let ex = x - nx, ey = y - ny, e = Math.hypot(ex, ey); const hit = e === 0;
          if (hit) {ex = x - cx; ey = y - cy; e = Math.hypot(ex, ey) || 1;}
          if (!hit && e > reach) continue;
          const w = hit ? 1.6 : Math.pow((reach - e) / reach, 2) * 1.4, side = Math.sign(-dy * (x - cx) + dx * (y - cy)) || 1;
          vx += ex / e * w - dy / d * side * w * .8; vy += ey / e * w + dx / d * side * w * .8;
        }
        const m = Math.hypot(vx, vy) || 1; x += vx / m * 4; y += vy / m * 4; pts.push([x, y]);
      }
      return null;
    };
    let pts = walk(true) || walk(false) || [[from.x, from.y], [to.x, to.y]];
    for (let i = 0; i < pts.length; i++) for (let j = pts.length - 1; j > i + 10; j--) if (Math.hypot(pts[j][0] - pts[i][0], pts[j][1] - pts[i][1]) < 6) {pts.splice(i + 1, j - i - 1); break;}
    if (edges.some(other => other.from === edge.to && other.to === edge.from)) pts = pts.map(([x, y], i) => {
      const a = pts[Math.max(0, i - 1)], b = pts[Math.min(pts.length - 1, i + 1)], len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1, t = i / (pts.length - 1), off = 10 + 8 * Math.sin(Math.PI * t);
      return [x - (b[1] - a[1]) / len * off, y + (b[0] - a[0]) / len * off];
    });
    let i0 = 0; while (i0 < pts.length - 2 && inside(src, pts[i0 + 1])) i0++;
    let i1 = i0; while (i1 < pts.length - 1 && !inside(dst, pts[i1 + 1])) i1++;
    let out = pts.slice(i0, i1 + 1);
    for (let pass = 0; pass < 3; pass++) out = out.map((q, i) => i < 2 || i > out.length - 3 ? q : [0, 1].map(c => (out[i - 2][c] + out[i - 1][c] + q[c] + out[i + 1][c] + out[i + 2][c]) / 5));
    return {edge, pts: out};
  }).filter(row => row.pts.length > 1);
  const placed = [], bounds = {l: 4, t: 4, r: W - 4, b: H - 4};
  const overlap = (a, b) => Math.max(0, Math.min(a.r, b.r) - Math.max(a.l, b.l)) * Math.max(0, Math.min(a.b, b.b) - Math.max(a.t, b.t));
  for (const {edge, pts} of drawn) {
    const otherPts = drawn.filter(row => row.pts !== pts).flatMap(row => row.pts);
    const path = svg("path", {d: "M" + pts.map(q => q.map(v => v.toFixed(1)).join(" ")).join(" L"), class: "thread"});
    const words = edge.kind.replaceAll("-", " "), rowsOf = [];
    for (const word of W < 600 && words.length > 10 ? words.split(/(?<= )/) : [words]) {
      if (rowsOf.length && (rowsOf[rowsOf.length - 1] + word).length <= 12) rowsOf[rowsOf.length - 1] += word; else rowsOf.push(word);
    }
    const hold = reduced() ? "" : " wait";
    const label = svg("text", {class: "thread-lbl" + hold, "text-anchor": "middle", "dominant-baseline": "central"});
    rowsOf.forEach((text, k) => label.append(svg("tspan", {x: 0, dy: k ? "1.1em" : `${-(rowsOf.length - 1) * .55}em`, text: text.trim()})));
    over.append(path, label);
    const bb = label.getBBox(), lw = bb.width + 6, lh = bb.height + 2;
    let best = null;
    for (const f of Array.from({length: 23}, (_, k) => .06 + k * .04).sort((a, b) => Math.abs(a - .5) - Math.abs(b - .5))) {
      const i = Math.round(f * (pts.length - 1)), a = pts[Math.max(0, i - 2)], b = pts[Math.min(pts.length - 1, i + 2)], len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
      for (const [sign, extra] of [[-1, 3], [1, 3], [-1, 8], [1, 8], [-1, 14], [1, 14], [1, null]]) {
        const on = extra === null, nx = -(b[1] - a[1]) / len * sign, ny = (b[0] - a[0]) / len * sign, gap = on ? 0 : Math.abs(nx) * (lw / 2) + Math.abs(ny) * (lh / 2) + extra;
        const cx = pts[i][0] + nx * gap, cy = pts[i][1] + ny * gap, r = {l: cx - lw / 2, t: cy - lh / 2, r: cx + lw / 2, b: cy + lh / 2};
        let score = Math.abs(f - .5) * 40 + (on ? 60 : (extra - 3) * 2) + (lw * lh - overlap(r, bounds)) * 50;
        for (const id in rects) score += overlap(r, grow(rects[id], 3)) * 20;
        for (const q of placed) score += overlap(r, grow(q, 2)) * 20;
        if (!on) for (const q of pts) if (inside(r, q)) score += 25;
        for (const q of otherPts) if (inside(grow(r, clear), q)) score += 25;
        const dist = list => list.reduce((m, q) => Math.min(m, Math.hypot(Math.max(r.l - q[0], 0, q[0] - r.r), Math.max(r.t - q[1], 0, q[1] - r.b))), Infinity);
        if (on ? dist(otherPts) < 3 : dist(otherPts) < dist(pts) + 6) score += 150;
        if (!best || score < best.score) best = {score, cx, cy, r, on};
      }
    }
    placed.push(best.r);
    label.setAttribute("y", best.cy.toFixed(1));
    label.querySelectorAll("tspan").forEach(t => t.setAttribute("x", best.cx.toFixed(1)));
    const plate = best.on ? svg("rect", {class: "thread-plate" + hold, x: best.r.l.toFixed(1), y: best.r.t.toFixed(1), width: lw.toFixed(1), height: lh.toFixed(1)}) : null;
    if (plate) label.before(plate);
    const arrive = () => {path.setAttribute("marker-end", "url(#arr)"); label.classList.remove("wait"); plate?.classList.remove("wait");};
    if (reduced()) arrive();
    else {path.style.setProperty("--len", path.getTotalLength()); path.addEventListener("animationend", arrive, {once: true}); path.classList.add("go");}
  }
}

// ---------- Start ----------
async function start() {
  config = globalThis.humanHostReader?.config || await json("reader.json");
  if (params.has("release") && params.get("release") !== (config.release_id || config.candidate_id)) throw new Error("This link names a different wiki release. Open that release's archived site; current content has not been substituted.");
  snapshot = params.get("snapshot") || config.default_snapshot;
  const selectedCapture = await captureFor(snapshot), pinned = selectedCapture.index;
  index = await json(pinned ? pinned.path : `snapshots/${snapshot}.json`, pinned);
  document.getElementById("home").href = url("hub");
  const selector = document.getElementById("version");
  let selectedShown = false;
  const appendVersion = version => {
    if (version.snapshot_id === snapshot) {if (selectedShown) return; selectedShown = true;}
    const option = element("option", `${versionLabel(version)} · ${version.snapshot_id.split("-").at(-1)}`);
    option.value = version.snapshot_id; option.selected = version.snapshot_id === snapshot; selector.append(option);
  };
  if (config.capture_catalog) {
    appendVersion(selectedCapture.version);
    selector.parentElement.after(capturePager(appendVersion));
  } else config.versions.forEach(appendVersion);
  selector.addEventListener("change", () => {const target = new URL(location.href); target.searchParams.set("snapshot", selector.value); target.searchParams.set("release", config.release_id || config.candidate_id); location.assign(target);});
  const nav = document.getElementById("topics");
  for (const [text, target] of [["Guides", hubURL("") + "#guides"], ["Topics", hubURL("") + "#topics-list"]]) nav.append(link(text, target));
  // Problems go to GitHub issue forms, so there is no form of our own to run.
  if (site().issues?.choose) nav.append(el("a", {href: site().issues.choose, class: "report", rel: "noopener"}, "Report a problem"));
  for (const official of config.official_links) {document.getElementById("credits").append(link(official.title, official.url), document.createTextNode(" · "));}
  const find = document.getElementById("search-form");
  find.addEventListener("submit", event => {event.preventDefault(); location.assign(searchURL(document.getElementById("search").value.trim()));});
  status();
  const path = decodeURIComponent(location.pathname.slice(routeBase.pathname.length));
  const entry = /^entry\/(e-[0-9a-f]{32})\/?$/.exec(path);
  const group = /^groups\/([a-z][a-z0-9-]*)\/(?:index\.html)?$/.exec(path);
  const guide = /^guide\/([a-z0-9-]+)\/?$/.exec(path);
  const hub = config.topic === "hub";
  if (typeof document.body?.classList === "object") document.body.classList.toggle("is-home", hub && (path === "" || path === "index.html"));
  if (entry) await showEntry(entry[1]);
  else if (group) await topicIndex(group[1]);
  else if (hub && guide) await guidePage(guide[1]);
  else if (hub && /^search\/?$/.test(path)) await hubSearch();
  else if (path === "" || path === "index.html") await (hub ? home() : topicIndex(null));
  else throw new Error("Unknown reader route");
  if (location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView?.();
}

// "/" focuses search, as in study 11.
if (typeof document.addEventListener === "function") document.addEventListener("keydown", event => {
  if (event.key !== "/" || /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || "")) return;
  event.preventDefault(); (document.getElementById("hq") || document.getElementById("search"))?.focus();
});

start().catch(failure);
