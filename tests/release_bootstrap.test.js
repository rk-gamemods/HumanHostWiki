"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../wikibuild/release_bootstrap.js"), "utf8");
const origin = "https://wiki-fixture.github.io/";
const base = origin + "Wiki-items/";
const identity = "a".repeat(64), nextIdentity = "b".repeat(64);
const topics = [{id: "hub", base: origin + "Wiki-hub/"}, {id: "items", base}];
const config = id => ({schema_version: 1, release_id: id, topic: "items", topics,
  runtime: {js: origin + "Wiki-items-Part-0001/runtime/reader.js", css: "runtime/reader.css"}});
const encode = value => Buffer.from(JSON.stringify(value));
const reference = (id, target, data) => encode({schema_version: 1, kind: "wiki-release-reference", release_id: id,
  target: {path: target, sha256: crypto.createHash("sha256").update(data).digest("hex"), bytes: data.length}});

async function run(files, requested = identity, localBase = base) {
  const elements = {status: {}, content: {}, stylesheet: {}};
  const scripts = [], calls = [];
  const context = {URL, URLSearchParams, TextDecoder, crypto: crypto.webcrypto,
    location: {origin: new URL(localBase).origin, search: requested ? "?release=" + requested : ""},
    humanHostPreviewOrigin: localBase === base ? undefined : "https://wiki-fixture.github.io",
    document: {currentScript: {src: localBase + "reader.js"}, getElementById: id => elements[id],
      querySelector: () => elements.stylesheet, createElement: () => ({}), head: {append: script => scripts.push(script)}},
    fetch: async url => {
      calls.push(url.href);
      const bytes = files[url.href];
      return {ok: !!bytes, status: bytes ? 200 : 404,
        arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)};
    }};
  await vm.runInNewContext(source, context, {filename: "release_bootstrap.js"});
  return {context, elements, scripts, calls};
}

(async () => {
  const target = origin + "Wiki-items-Part-0001/releases/" + identity + ".json";
  const data = encode(config(identity));
  const pointer = reference(identity, target, data);
  let result = await run({[base + "releases/" + identity + ".json"]: pointer, [target]: data});
  assert.equal(result.context.humanHostReader.config.release_id, identity);
  assert.equal(result.context.humanHostReader.base, base);
  assert.equal(result.scripts[0].src, config(identity).runtime.js);
  assert.equal(result.elements.stylesheet.href, base + "runtime/reader.css");

  result = await run({[base + "releases/" + identity + ".json"]: pointer, [target]: Buffer.concat([data, Buffer.from(" ")])});
  assert.equal(result.scripts.length, 0);
  assert.match(result.elements.content.textContent, /content differs/);

  const another = encode(config(nextIdentity));
  result = await run({[base + "releases/" + identity + ".json"]: reference(identity, target, another), [target]: another});
  assert.equal(result.scripts.length, 0);
  assert.match(result.elements.content.textContent, /identity differs/);

  result = await run({[base + "releases/" + identity + ".json"]: reference(identity, "https://elsewhere.invalid/config.json", data)});
  assert.equal(result.calls.length, 1);
  assert.match(result.elements.content.textContent, /namespace/);

  // A directly visited topic still follows the hub's coordinated release while
  // its newer local reader pointer is waiting for hub promotion.
  result = await run({[base + "reader.json"]: encode(config(nextIdentity)),
    [origin + "Wiki-hub/reader.json"]: encode({release_id: identity}),
    [base + "releases/" + identity + ".json"]: pointer, [target]: data}, null);
  assert.equal(result.context.humanHostReader.config.release_id, identity);
  assert.equal(result.scripts.length, 1);
  const local = "http://127.0.0.1:8123/";
  result = await run({[local + "Wiki-items/releases/" + identity + ".json"]: pointer,
    [local + "Wiki-items-Part-0001/releases/" + identity + ".json"]: data}, identity, local + "Wiki-items/");
  assert.equal(result.context.humanHostReader.config.release_id, identity);
  assert.equal(result.scripts[0].src, local + "Wiki-items-Part-0001/runtime/reader.js");
  assert.equal(result.context.humanHostReader.resolve(target).href, target.replace(origin, local));
  console.log("6 release loader scenarios passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
