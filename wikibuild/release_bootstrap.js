"use strict";

// This small loader stays at the stable route. Each release selects its own
// immutable runtime and configuration; data packs remain shared by content hash.
(async () => {
  const base = new URL(".", document.currentScript.src);
  const requested = new URLSearchParams(location.search).get("release");
  if (requested && !/^[0-9a-f]{64}$/.test(requested)) throw new Error("Invalid release identity");
  const response = await fetch(new URL(requested ? `releases/${requested}.json` : "reader.json", base));
  if (!response.ok) throw new Error(`Release unavailable: HTTP ${response.status}`);
  const config = await response.json();
  if (requested && requested !== config.release_id) throw new Error("Release identity differs");
  globalThis.humanHostReader = {config, base: base.href};
  document.querySelector('link[rel="stylesheet"]').href = new URL(config.runtime.css, base).href;
  const script = document.createElement("script");
  script.src = new URL(config.runtime.js, base).href;
  script.onerror = () => {document.getElementById("status").textContent = "The selected release runtime could not be loaded.";};
  document.head.append(script);
})().catch(error => {
  document.getElementById("status").textContent = "Release unavailable. No different release was substituted.";
  document.getElementById("content").textContent = error.message;
});
