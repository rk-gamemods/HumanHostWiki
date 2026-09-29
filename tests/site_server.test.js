"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const {test} = require("node:test");
const {createStaticServer, staticTarget} = require("../tools/check_site.js");

test("reader server serves files and each site's fallback shell", async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "hhwiki-site-server-"));
  t.after(() => fs.rmSync(root, {recursive: true}));
  for (const site of ["hub", "items-equipment"]) fs.mkdirSync(path.join(root, site));
  fs.writeFileSync(path.join(root, "hub", "index.html"), "HUB HOME");
  fs.writeFileSync(path.join(root, "hub", "404.html"), "HUB FALLBACK");
  fs.writeFileSync(path.join(root, "hub", "reader.json"), '{"topic":"hub"}');
  fs.writeFileSync(path.join(root, "items-equipment", "404.html"), "ITEM FALLBACK");
  const server = createStaticServer(root);
  await new Promise((resolve, reject) => {server.once("error", reject); server.listen(0, "127.0.0.1", resolve);});
  t.after(() => new Promise(resolve => server.close(resolve)));
  const base = `http://127.0.0.1:${server.address().port}`;

  for (const [url, status, body, type] of [
    ["/hub/", 200, "HUB HOME", "text/html"],
    ["/hub/reader.json", 200, '{"topic":"hub"}', "application/json"],
    ["/hub/guide/getting-started/?snapshot=old", 404, "HUB FALLBACK", "text/html"],
    ["/hub/search/?q=axe", 404, "HUB FALLBACK", "text/html"],
    ["/items-equipment/entry/e-0123456789abcdef0123456789abcdef/", 404, "ITEM FALLBACK", "text/html"],
    ["/hub/missing.js", 404, "HUB FALLBACK", "text/html"],
    ["/unknown/missing", 404, "", null]
  ]) {
    const response = await fetch(base + url);
    assert.equal(response.status, status, url);
    assert.equal(await response.text(), body, url);
    if (type) assert.match(response.headers.get("content-type"), new RegExp(type), url);
  }

  const head = await fetch(base + "/hub/search/", {method: "HEAD"});
  assert.equal(head.status, 404);
  assert.equal(await head.text(), "");
  assert.equal(staticTarget(root, "/hub/%2e%2e%2fsecret").status, 400);
  assert.equal(staticTarget(root, "/hub/%2e%2e/reader.json").status, 400);
  assert.equal(staticTarget(root, "/hub/%5csecret").status, 400);

  const method = await new Promise((resolve, reject) => {
    const request = http.request(base + "/hub/", {method: "POST"}, response => {
      response.resume(); response.on("end", () => resolve(response));
    });
    request.on("error", reject); request.end();
  });
  assert.equal(method.statusCode, 405);
});
