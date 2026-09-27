"use strict";

// This small loader stays at the stable route. Each release selects its own
// immutable runtime and configuration; data packs remain shared by content hash.
(async () => {
  const base = new URL(".", document.currentScript.src);
  const requested = new URLSearchParams(location.search).get("release");
  if (requested && !/^[0-9a-f]{64}$/.test(requested)) throw new Error("Invalid release identity");
  function resolve(value, relative = base) {
    const url = new URL(value, relative);
    // The local preview maps origins at request time. Immutable JSON bytes and
    // their hashes remain identical to publication, including partition links.
    if (globalThis.humanHostPreviewOrigin === url.origin) {
      const local = new URL(location.origin);
      url.protocol = local.protocol;
      url.host = local.host;
    }
    return url;
  }
  async function read(url, missing = false) {
    url = resolve(url);
    let expected = null, identity = null;
    const seen = new Set();
    for (let depth = 0; depth < 4; depth++) {
      if (seen.has(url.href)) throw new Error("Release reference cycle");
      seen.add(url.href);
      const response = await fetch(url, {cache: "no-cache"});
      if (missing && !expected && response.status === 404) return null;
      if (!response.ok) throw new Error(`Release unavailable: HTTP ${response.status}`);
      const bytes = await response.arrayBuffer();
      if (expected) {
        const sha = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), value => value.toString(16).padStart(2, "0")).join("");
        if (bytes.byteLength !== expected.bytes || sha !== expected.sha256) throw new Error("Release reference content differs");
      }
      const value = JSON.parse(new TextDecoder().decode(bytes));
      if (identity && value.release_id !== identity) throw new Error("Release reference identity differs");
      if (value.kind !== "wiki-release-reference") return value;
      if (value.schema_version !== 1 || !/^[0-9a-f]{64}$/.test(value.release_id)) throw new Error("Invalid release reference");
      expected = value.target;
      identity = value.release_id;
      url = resolve(expected.path);
      if (url.origin !== base.origin) throw new Error("Release reference leaves the configured namespace");
    }
    throw new Error("Release reference depth exceeded");
  }
  function successor(value, current) {
    if (value.schema_version !== 1 || value.kind !== "wiki-entrypoint-successor" ||
        typeof value.topic !== "string" || typeof value.target !== "string" || typeof value.hub !== "string" ||
        !/^[0-9a-f]{64}$/.test(value.since_release)) throw new Error("Invalid entrypoint successor");
    const target = resolve(value.target, current);
    if (target.origin !== base.origin || !target.pathname.endsWith("/") || target.search || target.hash || target.username || target.password) throw new Error("Entrypoint successor leaves the configured namespace");
    return target;
  }
  async function entrypoint(start, selected = null, coordinate = false) {
    let current = resolve(start);
    let topic = null;
    const seen = new Set();
    for (let depth = 0; depth < 64; depth++) {
      if (seen.has(current.href)) throw new Error("Entrypoint successor cycle");
      seen.add(current.href);
      if (selected) {
        const value = await read(new URL(`releases/${selected}.json`, current), true);
        if (value) {
          if (topic && value.topic !== topic) throw new Error("Entrypoint topic differs");
          return value;
        }
      }
      const value = await read(new URL("reader.json", current));
      if (value.kind !== "wiki-entrypoint-successor") {
        if (selected) throw new Error("Requested release is unavailable in this entrypoint history");
        if (topic && value.topic !== topic) throw new Error("Entrypoint topic differs");
        return value;
      }
      const next = successor(value, current);
      if (topic && value.topic !== topic) throw new Error("Entrypoint topic differs");
      topic = value.topic;
      // Current topic reads use the hub's direct active-front map. They need
      // not traverse each retired topic generation before coordination.
      if (coordinate && value.topic !== "hub") return value;
      current = next;
    }
    throw new Error("Entrypoint successor depth exceeded");
  }
  let config = await entrypoint(base, requested, !requested);
  if (!requested && config.topic !== "hub") {
    const hub = config.kind === "wiki-entrypoint-successor" ? config.hub : config.topics.find(topic => topic.id === "hub").base;
    const hubURL = resolve(hub, new URL(location.origin));
    if (hubURL.origin !== base.origin) throw new Error("Hub leaves the configured namespace");
    const coordinated = await entrypoint(hubURL);
    if (!/^[0-9a-f]{64}$/.test(coordinated.release_id)) throw new Error("No coordinated release is available");
    const front = resolve(coordinated.entrypoints?.[config.topic] || base);
    if (front.origin !== base.origin) throw new Error("Coordinated entrypoint leaves the configured namespace");
    const topic = config.topic;
    config = await entrypoint(front, coordinated.release_id);
    if (config.topic !== topic) throw new Error("Coordinated topic differs");
    if (config.release_id !== coordinated.release_id) throw new Error("Coordinated release identity differs");
  }
  if (requested && requested !== config.release_id) throw new Error("Release identity differs");
  const logical = resolve(config.topics.find(topic => topic.id === config.topic).base, new URL(location.origin));
  if (logical.origin !== base.origin) throw new Error("Logical topic leaves the configured namespace");
  const relative = (value, root = logical) => resolve(value, root);
  globalThis.humanHostReader = {config, base: logical.href, routeBase: base.href, resolve: relative};
  document.querySelector('link[rel="stylesheet"]').href = relative(config.runtime.css).href;
  const script = document.createElement("script");
  script.src = relative(config.runtime.js).href;
  script.onerror = () => {document.getElementById("status").textContent = "The selected release runtime could not be loaded.";};
  document.head.append(script);
})().catch(error => {
  document.getElementById("status").textContent = "Release unavailable. No different release was substituted.";
  document.getElementById("content").textContent = error.message;
});
