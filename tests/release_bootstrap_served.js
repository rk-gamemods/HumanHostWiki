"use strict";

// Run the real loader against a served-file map written by a Python release test.
// Input JSON: {"files": {url: base64}, "pages": [route URL]}. Output JSON: one
// result per page with the selected configuration or the loader's error text.
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../wikibuild/release_bootstrap.js"), "utf8");

async function load(files, page) {
  const elements = {status: {}, content: {}, stylesheet: {}, "wiki-fonts": null};
  const scripts = [], calls = [];
  const context = {URL, URLSearchParams, TextDecoder, crypto: crypto.webcrypto,
    location: {origin: new URL(page).origin, search: ""},
    document: {currentScript: {src: page + "reader.js"}, getElementById: id => elements[id],
      querySelector: () => elements.stylesheet, createElement: tag => ({tag}),
      head: {append: element => {
        if (element.tag === "link") elements[element.id] = element;
        else scripts.push(element);
      }}},
    fetch: async url => {
      calls.push(url.href);
      const bytes = files.get(url.href);
      return {ok: !!bytes, status: bytes ? 200 : 404,
        arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)};
    }};
  await vm.runInNewContext(source, context, {filename: "release_bootstrap.js"});
  const reader = context.humanHostReader;
  return {page, calls, error: elements.content.textContent || null,
    config: reader ? reader.config : null, base: reader ? reader.base : null,
    script: scripts.length ? scripts[0].src : null, stylesheet: elements.stylesheet.href || null,
    fonts: elements["wiki-fonts"] ? elements["wiki-fonts"].href : null};
}

(async () => {
  const input = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  const files = new Map(Object.entries(input.files).map(([url, data]) => [url, Buffer.from(data, "base64")]));
  const results = [];
  for (const page of input.pages) results.push(await load(files, page));
  process.stdout.write(JSON.stringify(results));
})().catch(error => { console.error(error); process.exitCode = 1; });
