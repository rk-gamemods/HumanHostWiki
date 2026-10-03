#!/usr/bin/env node
"use strict";

// Browser checks for a built reader candidate. No repository package install is needed.
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const DEFAULT_MODULES = "C:/Users/Admin/Documents/HumanHostWiki-DesignStudies/set-b/_tools/node_modules";
const TYPES = {
  ".css": "text/css; charset=utf-8", ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
  ".png": "image/png", ".svg": "image/svg+xml", ".webp": "image/webp",
  ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8"
};

function inside(root, file) {
  const relative = path.relative(root, file);
  return relative === "" || (relative !== ".." && !relative.startsWith(".." + path.sep) && !path.isAbsolute(relative));
}

function staticTarget(root, requestUrl) {
  let pathname;
  try { pathname = decodeURIComponent(requestUrl.split(/[?#]/, 1)[0]); }
  catch { return {status: 400}; }
  if (!pathname.startsWith("/") || pathname.includes("\0") || pathname.includes("\\")) return {status: 400};
  const parts = pathname.split("/").filter(Boolean);
  if (parts.some(part => part === "." || part === "..")) return {status: 400};
  const site = parts[0];
  let file = path.resolve(root, ...parts);
  if (!inside(root, file)) return {status: 400};
  if (fs.existsSync(file) && fs.statSync(file).isDirectory()) file = path.join(file, "index.html");
  if (fs.existsSync(file) && fs.statSync(file).isFile() && inside(root, fs.realpathSync(file))) {
    return {status: 200, file};
  }
  if (site) {
    const fallback = path.join(root, site, "404.html");
    if (fs.existsSync(fallback) && fs.statSync(fallback).isFile() && inside(root, fs.realpathSync(fallback))) {
      return {status: 404, file: fallback, fallback: true};
    }
  }
  return {status: 404};
}

function createStaticServer(root) {
  const resolved = path.resolve(root);
  return http.createServer((req, res) => {
    if (req.method !== "GET" && req.method !== "HEAD") {
      res.writeHead(405, {Allow: "GET, HEAD"}); res.end(); return;
    }
    const target = staticTarget(resolved, req.url);
    if (!target.file) { res.writeHead(target.status); res.end(); return; }
    const headers = {"content-type": TYPES[path.extname(target.file).toLowerCase()] || "application/octet-stream",
      "content-length": fs.statSync(target.file).size};
    res.writeHead(target.status, headers);
    if (req.method === "HEAD") { res.end(); return; }
    fs.createReadStream(target.file).pipe(res);
  });
}

function readJson(file) { return JSON.parse(fs.readFileSync(file, "utf8")); }

function parseArgs(argv) {
  const options = {modules: DEFAULT_MODULES};
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--help" || argv[i] === "-h") options.help = true;
    else if (argv[i] === "--candidate" || argv[i] === "--modules") {
      if (!argv[i + 1]) throw new Error(`${argv[i]} needs a path`);
      options[argv[i].slice(2)] = argv[++i];
    } else throw new Error(`Unknown argument: ${argv[i]}`);
  }
  return options;
}

function candidateDirectory(given) {
  if (given) return path.resolve(given);
  const id = readJson(path.join(ROOT, ".local", "reader-latest.json")).candidate_id;
  if (!/^[0-9a-f]{64}$/.test(id)) throw new Error("Invalid candidate_id in .local/reader-latest.json");
  const base = path.join(ROOT, ".local", "readers");
  const full = path.join(base, id), short = path.join(base, id.slice(0, 24));
  return fs.existsSync(full) ? full : short;
}

function rowsFromIndex(candidate, topic, index) {
  const base = path.join(candidate, topic);
  const rows = [];
  for (const ref of index.search || []) {
    if (!/^[a-z0-9/_-]+\.json$/i.test(ref.path)) throw new Error(`Unsafe search pack: ${ref.path}`);
    const data = readJson(path.join(base, ref.path));
    rows.push(...(Array.isArray(data) ? data : Object.values(data)));
  }
  return rows;
}

function snapshotIndex(candidate, topic, snapshot) {
  return readJson(path.join(candidate, topic, "snapshots", `${snapshot}.json`));
}

function chooseViews(candidate) {
  const config = readJson(path.join(candidate, "hub", "reader.json"));
  const current = config.default_snapshot, index = snapshotIndex(candidate, "hub", current);
  const rows = rowsFromIndex(candidate, "hub", index);
  const crude = rows.find(row => row.topic === "items-equipment" && row.name.toLowerCase() === "crude axe");
  const recipe = rows.find(row => row.topic === "crafting-processing" && row.kind === "recipe") || rows.find(row => row.topic === "crafting-processing");
  const combat = rows.find(row => row.topic === "combat");
  if (!crude || !recipe || !combat) throw new Error("Could not find Crude Axe, a recipe, and a combat entry in the hub search index");
  const oldest = config.versions?.at(-1)?.snapshot_id;
  if (!oldest || oldest === current) throw new Error("No older captured version in hub reader.json");
  const oldRows = rowsFromIndex(candidate, "hub", snapshotIndex(candidate, "hub", oldest));
  const older = oldRows.find(row => row.entity_key === crude.entity_key) || oldRows.find(row => row.topic === "items-equipment") || oldRows[0];
  if (!older) throw new Error("Oldest captured version has no search entries");
  const entry = row => `/${row.topic}/entry/${encodeURIComponent(row.entity_key)}/`;
  return {indexedEntries: new Map(rows.map(row => [row.entity_key, row.topic])), views: [
    {name: "hub-home", url: "/hub/"},
    {name: "hub-search", url: "/hub/search/?q=crude+axe"},
    ...(index.guides || []).map(guide => ({name: `guide-${guide.id}`, url: `/hub/guide/${guide.id}/`, guide: true})),
    {name: "items-equipment", url: "/items-equipment/"},
    {name: "crude-axe", url: entry(crude), entry: true},
    {name: "recipe", url: entry(recipe)},
    {name: "combat", url: entry(combat)},
    {name: "oldest-entry", url: `${entry(older)}?snapshot=${encodeURIComponent(oldest)}`, oldest}
  ]};
}

function seededSample(values, size, seed) {
  const copy = [...new Set(values)];
  let state = seed >>> 0;
  for (let i = copy.length - 1; i > 0; i--) {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    const j = state % (i + 1);
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy.slice(0, size);
}

async function inspectPage(page) {
  return page.evaluate(() => {
    const vw = document.documentElement.clientWidth, sw = document.documentElement.scrollWidth;
    const bad = [];
    if (sw > vw + 1) for (const node of document.querySelectorAll("body *")) {
      const rect = node.getBoundingClientRect();
      if (rect.width > 0 && rect.right > vw + 1 && getComputedStyle(node).position !== "fixed") {
        bad.push(`${node.tagName.toLowerCase()}.${[...node.classList].join(".")} right=${Math.round(rect.right)}`);
      }
      if (bad.length === 5) break;
    }
    return {heading: document.querySelector("#content h1")?.textContent?.trim() || "",
      overflow: {viewport: vw, page: sw, elements: bad}};
  });
}

async function focusCheck(page) {
  await page.keyboard.press("Tab"); await page.keyboard.press("Tab"); await page.keyboard.press("Tab");
  return page.evaluate(() => {
    const node = document.activeElement, focusVisible = node.matches(":focus-visible");
    const nodes = [node, node.parentElement, node.parentElement?.parentElement, ...node.querySelectorAll("*")].filter(Boolean).slice(0, 8);
    const styles = () => nodes.map(item => {
      const css = getComputedStyle(item);
      return [css.outlineStyle, css.outlineWidth, css.outlineColor, css.boxShadow,
        css.backgroundColor, css.color, css.borderColor, css.borderBottomColor,
        css.borderBottomWidth, css.textDecorationLine, css.stroke, css.strokeWidth].join("|");
    });
    const focused = styles(); node.blur(); const blurred = styles(); node.focus();
    return {target: node.outerHTML.slice(0, 180), focusVisible,
      changedElements: focused.map((value, i) => value === blurred[i] ? null : nodes[i].tagName.toLowerCase()).filter(Boolean),
      visible: focusVisible && focused.some((value, i) => value !== blurred[i])};
  });
}

async function axeCheck(page, axeSource) {
  await page.addScriptTag({content: axeSource});
  return page.evaluate(async () => {
    const result = await globalThis.axe.run(document, {resultTypes: ["violations"]});
    return result.violations.map(item => ({id: item.id, impact: item.impact, description: item.help,
      count: item.nodes.length, samples: item.nodes.slice(0, 3).map(node => node.target.join(" "))}));
  });
}

async function load(page, url) {
  const response = await page.goto(url, {waitUntil: "domcontentloaded"});
  await page.locator("#content h1").first().waitFor({state: "visible", timeout: 20000});
  await page.waitForLoadState("networkidle", {timeout: 15000});
  return response;
}

async function runView(browser, base, view, device, axeSource, indexedEntries, outDir, failures) {
  const context = await browser.newContext({viewport: {width: device.width, height: device.height},
    deviceScaleFactor: device.mobile ? 2 : 1, isMobile: device.mobile, hasTouch: device.mobile});
  const page = await context.newPage();
  const result = {device: device.name, view: view.name, path: view.url, consoleErrors: [], pageErrors: [],
    expectedFallbackConsole: [], failedRequests: [], httpErrors: [], axe: [], checks: {}, screenshot: null};
  let expectedFallbackResponses = 0;
  page.on("console", message => { if (message.type() === "error") result.consoleErrors.push(message.text()); });
  page.on("pageerror", error => result.pageErrors.push(error.message));
  page.on("requestfailed", request => result.failedRequests.push(`${request.url()} ${request.failure()?.errorText || ""}`));
  page.on("response", response => {
    if (response.status() < 400) return;
    if (response.status() === 404 && response.request().resourceType() === "document"
      && new URL(response.url()).pathname === new URL(view.url, base).pathname) expectedFallbackResponses++;
    else result.httpErrors.push(`${response.status()} ${response.url()}`);
  });
  try {
    const navigation = await load(page, new URL(view.url, base).href);
    result.navigationStatus = navigation.status();
    const inspection = await inspectPage(page);
    result.heading = inspection.heading; result.overflow = inspection.overflow;
    if (!result.heading) failures.push(`${device.name}/${view.name}: missing main heading`);
    if (result.overflow.page > result.overflow.viewport + 1) failures.push(`${device.name}/${view.name}: horizontal overflow ${result.overflow.page}>${result.overflow.viewport} ${result.overflow.elements.join(", ")}`);
    result.focus = await focusCheck(page);
    if (!result.focus.visible) failures.push(`${device.name}/${view.name}: no visible focus ring after three Tabs (${result.focus.target})`);
    result.axe = await axeCheck(page, axeSource);
    for (const violation of result.axe.filter(item => ["serious", "critical"].includes(item.impact))) {
      failures.push(`${device.name}/${view.name}: axe ${violation.impact} ${violation.id} x${violation.count} ${violation.samples[0] || ""}`);
    }
    if (view.entry) {
      result.checks.entry = await page.evaluate(() => {
        const article = document.querySelector("#content article.entry");
        const card = article?.querySelector(".card"), technical = article?.querySelector("details.techref");
        return {card: !!card, technical: !!technical, collapsed: technical?.open === false,
          order: !!card && !!technical && !!(card.compareDocumentPosition(technical) & Node.DOCUMENT_POSITION_FOLLOWING)};
      });
      if (!Object.values(result.checks.entry).every(Boolean)) failures.push(`${device.name}/${view.name}: player card missing, below technical reference, or reference expanded`);
    }
    if (view.oldest && new URL(page.url()).searchParams.get("snapshot") !== view.oldest) failures.push(`${device.name}/${view.name}: oldest snapshot query lost`);
    if (view.guide) {
      const links = await page.locator("#content a[href*='/entry/e-']").evaluateAll(nodes => nodes.map(node => node.href));
      result.checks.guideLinks = {total: links.length, indexed: 0, missing: [], sampled: []};
      if (!links.length) failures.push(`${device.name}/${view.name}: no entry links in guide`);
      for (const href of links) {
        const match = /^\/([^/]+)\/entry\/(e-[0-9a-f]{32})\/?$/.exec(new URL(href).pathname);
        if (match && indexedEntries.get(match[2]) === match[1]) result.checks.guideLinks.indexed++;
        else result.checks.guideLinks.missing.push(href);
      }
      if (result.checks.guideLinks.missing.length) failures.push(`${device.name}/${view.name}: ${result.checks.guideLinks.missing.length} guide entry links absent from the hub search index; first: ${result.checks.guideLinks.missing[0]}`);
      const seed = [...view.name].reduce((sum, char) => (Math.imul(sum, 31) + char.charCodeAt(0)) >>> 0, 11);
      for (const href of seededSample(links, 5, seed)) {
        const linked = await context.newPage();
        try {
          await load(linked, href);
          const heading = await linked.locator("#content h1").first().innerText();
          result.checks.guideLinks.sampled.push({href, heading});
          if (!heading.trim() || heading === "Not in this version") failures.push(`${device.name}/${view.name}: broken guide link ${href}: ${heading}`);
        } catch (error) { failures.push(`${device.name}/${view.name}: broken guide link ${href}: ${error.message}`); }
        finally { await linked.close(); }
      }
      const checkbox = page.locator("#content .gcheck input[type=checkbox]").first();
      if (await checkbox.count()) {
        const before = await checkbox.isChecked();
        await checkbox.setChecked(!before);
        await load(page, page.url());
        const after = await page.locator("#content .gcheck input[type=checkbox]").first().isChecked();
        result.checks.checklist = {before, after, survived: after === !before};
        if (after !== !before) failures.push(`${device.name}/${view.name}: checklist state lost on reload`);
      }
    }
    result.screenshot = `${device.name}-${view.name}.png`;
    await page.screenshot({path: path.join(outDir, result.screenshot), fullPage: true, animations: "disabled"});
  } catch (error) { failures.push(`${device.name}/${view.name}: ${error.message}`); result.error = error.stack || error.message; }
  result.consoleErrors = result.consoleErrors.filter(message => {
    if (expectedFallbackResponses && message === "Failed to load resource: the server responded with a status of 404 (Not Found)") {
      expectedFallbackResponses--;
      result.expectedFallbackConsole.push(message);
      return false;
    }
    return true;
  });
  for (const error of result.consoleErrors) failures.push(`${device.name}/${view.name}: console ${error}`);
  for (const error of result.pageErrors) failures.push(`${device.name}/${view.name}: page ${error}`);
  for (const error of result.failedRequests) failures.push(`${device.name}/${view.name}: request ${error}`);
  for (const error of result.httpErrors) failures.push(`${device.name}/${view.name}: HTTP ${error}`);
  await context.close();
  return result;
}

async function checkReducedMotion(browser, base, outDir, failures) {
  const context = await browser.newContext({viewport: {width: 1440, height: 900}, reducedMotion: "reduce"});
  const page = await context.newPage(), errors = [], failedRequests = [];
  page.on("console", message => {if (message.type() === "error") errors.push(message.text());});
  page.on("pageerror", error => errors.push(error.message));
  page.on("requestfailed", request => failedRequests.push(request.url()));
  let result = {errors, failedRequests};
  try {
    await load(page, new URL("/hub/", base).href);
    result = {...result, ...await page.evaluate(() => ({reduced: matchMedia("(prefers-reduced-motion: reduce)").matches,
      map: !!document.querySelector(".map canvas"), waffle: document.querySelectorAll(".scrolly svg rect.sq").length}))};
    await page.locator(".scrolly .step").last().scrollIntoViewIfNeeded();
    await page.waitForTimeout(250);
    await page.screenshot({path: path.join(outDir, "reduced-motion-home.png"), fullPage: true, animations: "disabled"});
    if (!result.reduced || !result.map || !result.waffle) failures.push(`reduced-motion/home: map or waffle did not render ${JSON.stringify(result)}`);
  } catch (error) {failures.push(`reduced-motion/home: ${error.message}`); result.error = error.message;}
  for (const error of [...errors, ...failedRequests]) failures.push(`reduced-motion/home: ${error}`);
  await context.close();
  return result;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    console.log("Usage: node tools/check_site.js [--candidate <directory>] [--modules <node_modules directory>]\n" +
      "Default candidate: .local/readers/<id> from this repository's .local/reader-latest.json.\n" +
      `Default modules: ${DEFAULT_MODULES}`);
    return;
  }
  const candidate = candidateDirectory(options.candidate);
  if (!fs.existsSync(path.join(candidate, "hub", "reader.json"))) throw new Error(`Not a reader candidate: ${candidate}`);
  const modules = path.resolve(options.modules);
  const {chromium} = require(path.join(modules, "playwright"));
  const axeSource = fs.readFileSync(path.join(modules, "axe-core", "axe.min.js"), "utf8");
  const {views, indexedEntries} = chooseViews(candidate), outDir = path.join(ROOT, ".local", "site-check");
  fs.mkdirSync(outDir, {recursive: true});
  const report = {candidate, modules, when: new Date().toISOString(), views: [], reducedMotion: null, failures: []};
  const server = createStaticServer(candidate);
  const originalCwd = process.cwd();
  let browser;
  try {
    await new Promise((resolve, reject) => {server.once("error", reject); server.listen(0, "127.0.0.1", resolve);});
    const base = `http://127.0.0.1:${server.address().port}/`;
    // Chromium may emit debug.log in its working directory on Windows.
    process.chdir(outDir);
    browser = await chromium.launch();
    for (const device of [{name: "desktop", width: 1440, height: 900, mobile: false},
      {name: "mobile", width: 390, height: 844, mobile: true}]) {
      for (const view of views) {
        const result = await runView(browser, base, view, device, axeSource, indexedEntries, outDir, report.failures);
        report.views.push(result);
        console.log(`${device.name}/${view.name}: ${result.error ? "ERROR" : "checked"}`);
      }
    }
    report.reducedMotion = await checkReducedMotion(browser, base, outDir, report.failures);
  } catch (error) {report.failures.push(`runner: ${error.stack || error.message}`);}
  finally {
    if (browser) await browser.close();
    if (server.listening) await new Promise(resolve => server.close(resolve));
    process.chdir(originalCwd);
    fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(report, null, 2) + "\n");
  }
  console.log(`Report: ${path.join(outDir, "report.json")}; failures=${report.failures.length}`);
  const advisory = new Map();
  for (const view of report.views) for (const item of view.axe.filter(item => ["moderate", "minor"].includes(item.impact))) {
    const key = `${item.impact} ${item.id}`;
    advisory.set(key, [...(advisory.get(key) || []), `${view.device}/${view.view}`]);
  }
  for (const [key, locations] of advisory) console.log(`axe ${key}: ${locations.join(", ")}`);
  for (const failure of report.failures) console.error(failure);
  if (report.failures.length) process.exitCode = 1;
}

module.exports = {createStaticServer, staticTarget};
if (require.main === module) main().catch(error => {console.error(error.stack || error.message); process.exitCode = 1;});
