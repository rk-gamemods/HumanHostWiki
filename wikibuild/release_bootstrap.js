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
  async function read(url) {
    url = resolve(url);
    let expected = null, identity = null;
    const seen = new Set();
    for (let depth = 0; depth < 4; depth++) {
      if (seen.has(url.href)) throw new Error("Release reference cycle");
      seen.add(url.href);
      const response = await fetch(url, {cache: "no-cache"});
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
  let config = await read(new URL(requested ? `releases/${requested}.json` : "reader.json", base));
  if (!requested && config.topic !== "hub") {
    const hub = config.topics.find(topic => topic.id === "hub");
    const coordinated = await read(new URL("reader.json", new URL(hub.base, location.origin)));
    if (!/^[0-9a-f]{64}$/.test(coordinated.release_id)) throw new Error("No coordinated release is available");
    config = await read(new URL(`releases/${coordinated.release_id}.json`, base));
    if (config.release_id !== coordinated.release_id) throw new Error("Coordinated release identity differs");
  }
  if (requested && requested !== config.release_id) throw new Error("Release identity differs");
  globalThis.humanHostReader = {config, base: base.href, resolve};
  document.querySelector('link[rel="stylesheet"]').href = resolve(config.runtime.css).href;
  const script = document.createElement("script");
  script.src = resolve(config.runtime.js).href;
  script.onerror = () => {document.getElementById("status").textContent = "The selected release runtime could not be loaded.";};
  document.head.append(script);
})().catch(error => {
  document.getElementById("status").textContent = "Release unavailable. No different release was substituted.";
  document.getElementById("content").textContent = error.message;
});
