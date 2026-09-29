"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
// Disable only automatic UI startup. All lookup/verification functions are the
// production source; tests supply HTTP bytes and the minimal unused DOM hooks.
const source = fs.readFileSync(path.join(__dirname, "../wikibuild/web/reader.js"), "utf8")
  .replace("start().catch(failure);", "");
const base = "https://wiki-fixture.github.io/Wiki-items/";
const encode = value => Buffer.from(JSON.stringify(value));
const hash = data => crypto.createHash("sha256").update(data).digest("hex");

function reader(fetchBytes, site = base) {
  const calls = [];
  const context = {URL, URLSearchParams, TextDecoder, crypto: crypto.webcrypto,
    location: {origin: new URL(site).origin, search: ""},
    document: {currentScript: {src: site + "reader.js"}, getElementById: () => ({})},
    fetch: async url => {
      calls.push(url);
      const bytes = fetchBytes(url);
      return {ok: !!bytes, status: bytes ? 200 : 404,
        arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)};
    }};
  vm.runInNewContext(source, context);
  return {context, calls};
}

function fixture() {
  const files = {};
  function store(value, extra) {
    const data = encode(value), name = "objects/" + hash(data) + ".json";
    files[base + name] = data;
    return {path: name, bytes: data.length, sha256: hash(data), ...extra};
  }
  function leaf(key) {return store({[key]: {name: key}}, {first: key, last: key, count: 1});}
  function directory(shards) {return store({schema_version: 1, kind: "wiki-shard-directory", shards},
    {kind: "wiki-shard-directory", first: shards.map(v => v.first).sort()[0],
      last: shards.map(v => v.last).sort().at(-1), count: shards.reduce((sum, v) => sum + v.count, 0)});}
  const left = directory([leaf("a"), leaf("b")]), right = directory([leaf("x"), leaf("z")]);
  return {files, root: directory([left, right]), left, right};
}

(async () => {
  let data = fixture(), subject = reader(url => data.files[url]);
  assert.equal((await subject.context.keyed([data.root], "b")).name, "b");
  assert.equal(subject.calls.length, 3); // root directory, matching directory, one pack
  assert.ok(!subject.calls.includes(base + data.right.path));
  const count = subject.calls.length;
  assert.equal(await subject.context.keyed([data.root], "zzzz"), undefined);
  assert.equal(subject.calls.length, count);
  const all = [];
  for await (const ref of subject.context.shardReferences([data.root])) all.push(ref.first);
  assert.deepEqual(all, ["a", "b", "x", "z"]);
  const range = [];
  for await (const ref of subject.context.shardReferences([data.root], "b", "x")) range.push(ref.first);
  assert.deepEqual(range, ["b", "x"]);
  // Cached bytes cannot bypass a different caller's pinned size/hash check.
  await assert.rejects(subject.context.keyed([{...data.root, sha256: "0".repeat(64)}], "a"), /verification failed/);

  data = fixture();
  data.files[base + data.left.path] = Buffer.concat([data.files[base + data.left.path], Buffer.from(" ")]);
  subject = reader(url => data.files[url]);
  await assert.rejects(subject.context.keyed([data.root], "a"), /verification failed/);

  data = fixture();
  subject = reader(url => data.files[url]);
  await assert.rejects(subject.context.keyed([{...data.root, count: 999}], "a"), /summary differs/);
  await assert.rejects(subject.context.keyed([{...data.root, path: "https://elsewhere.invalid/index.json"}], "a"), /namespace/);
  assert.equal(subject.calls.length, 1);
  subject = reader(() => null);
  await assert.rejects(subject.context.keyed([data.root], "a"), /HTTP 404/);
  // A snapshot can advertise paged cards without entry lookup fetching them.
  data = fixture();
  subject = reader(url => data.files[url]);
  const indexWithCards = {entries: [data.left], cards: [data.right]};
  assert.equal((await subject.context.keyed(indexWithCards.entries, "b")).name, "b");
  assert.ok(!subject.calls.includes(base + data.right.path));
  assert.equal((await subject.context.keyed(indexWithCards.cards, "z")).name, "z");
  console.log("Shard lookup, traversal and rejection checks passed");

  if (process.argv[2]) {
    const input = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
    const root = path.resolve(input.root);
    const disk = url => {
      const target = new URL(url);
      assert.equal(target.origin, new URL(input.base).origin);
      const file = path.resolve(root, "." + target.pathname);
      assert.ok(file.startsWith(root + path.sep));
      return fs.readFileSync(file);
    };
    subject = reader(disk, input.base);
    const config = JSON.parse(disk(new URL(input.configuration.path, input.base).href));
    const index = JSON.parse(disk(new URL(config.snapshots[input.snapshot].path, input.base).href));
    assert.ok(index.entries.some(ref => ref.kind === "wiki-shard-directory"));
    assert.ok(index.cards.some(ref => ref.kind === "wiki-shard-directory"));
    const record = await subject.context.keyed(index.entries, input.key);
    assert.equal(record.entity_key, input.key);
    const semantics = await subject.context.keyed(index.semantics, record.revision_id);
    assert.equal(semantics.name, "Item " + input.key);
    assert.ok(subject.calls.length < 10, "Entry lookup fetched unrelated directory branches");
    assert.ok(index.cards.every(ref => !subject.calls.includes(new URL(ref.path, input.base).href)),
      "Entry lookup fetched unused cards");
    const card = await subject.context.keyed(index.cards, record.card_id);
    assert.equal(card.stats[0].display, "3");
    let searchCount = 0;
    for await (const ref of subject.context.shardReferences(index.search)) {
      searchCount += Object.keys(await subject.context.json(ref.path, ref)).length;
    }
    assert.equal(searchCount, input.count);
    console.log("Generated multi-partition snapshot: entry lookup and all expected search records passed");
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
