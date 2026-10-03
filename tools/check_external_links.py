"""Opt-in live acceptance for external article checks, isolated from published releases."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
import tracemalloc
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wikibuild import external_links, mediawiki
from wikibuild.storage import json_bytes, write_changed, writer_lock

# A real-boundary acceptance fixture, not production topic/entry routing policy.
SOURCE = {"api_url": "https://wiki.nerdwerx.io/api.php", "namespace": 3000, "namespace_name": "Human Host",
          "prefixes": ["Human Host:Content/Game Content"],
          "titles": ["Human Host:Guides", "Human Host:Guides/Vehicle Building"]}
SAMPLES = {"Human Host:Content/Game Content/Weapons/Stone Axe": "populated",
           "Human Host:Content/Game Content/Biomes": "populated", "Human Host:Guides": "empty"}


def unresolved(value):
    return [{"title": title, "reason": check["reason"], "revision": check["metadata"]["revision"]}
            for title, check in value["catalog"]["pages"].items() if check["status"] == "unavailable"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--online", action="store_true", help="Allow read-only public API requests")
    parser.add_argument("--root", type=Path, required=True, help="Isolated local evidence directory")
    parser.add_argument("--report-only", action="store_true", help="Read saved acceptance evidence without network or writes")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.report_only:
        result = json.loads((root / "acceptance.json").read_bytes())
        value = external_links.read(root, result["observation_id"])
        print(json_bytes({**result, "unresolved": unresolved(value)}).decode())
        return
    if not args.online:
        parser.error("The live provider check requires --online")
    now = datetime.now(timezone.utc)
    tracemalloc.start()
    start = time.perf_counter()
    with writer_lock(root):
        value, first_metrics = external_links.refresh(root, SOURCE, now=now, progress=print)
        elapsed = time.perf_counter() - start
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        if not value["catalog"]["inventory_complete"]:
            raise RuntimeError("Live inventory was incomplete; inspect the saved observation")
        checks = {title: external_links.lookup(value, title) for title in SAMPLES}
        for title, expected in SAMPLES.items():
            if checks[title]["status"] != expected:
                raise RuntimeError(f"Live fixture changed or the classifier disagrees: {title}")
        pointer = root / "external-links/latest.json"
        before = pointer.read_bytes(), pointer.stat().st_mtime_ns
        repeat_start = time.perf_counter()
        repeat, repeat_metrics = external_links.refresh(root, SOURCE)
        repeat_elapsed = time.perf_counter() - repeat_start
        if repeat != value or before != (pointer.read_bytes(), pointer.stat().st_mtime_ns):
            raise RuntimeError("Immediate repeat was not byte- and timestamp-stable")
        # Exercise expiry with a one-second policy and actual UTC timestamps.
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(value["checked_at"])).total_seconds()
        if age < 1:
            time.sleep(1 - age)
        expired, expiry_metrics = external_links.refresh(root, SOURCE, cache_seconds=1)
    # Independently read the exact remote revisions, using hashlib directly.
    # This verifies captured identity and hashes, not just producer/reader agreement.
    revisions = [value["catalog"]["pages"][title]["metadata"]["revision"] for title in SAMPLES]
    parameters = {"action": "query", "format": "json", "formatversion": 2, "maxlag": 5,
                  "prop": "revisions", "rvprop": "ids|content", "rvslots": "main",
                  "revids": "|".join(map(str, revisions))}
    request = Request(SOURCE["api_url"] + "?" + urlencode(parameters), headers={
        "User-Agent": mediawiki.USER_AGENT, "Accept": "application/json", "Accept-Encoding": "identity"})
    with urlopen(request, timeout=30) as response:
        raw = response.read(256 * 1024 + 1)
        if response.status != 200 or len(raw) > 256 * 1024:
            raise RuntimeError("Independent revision response failed or exceeded its byte limit")
    data = json.loads(raw)
    found = set()
    for page in data["query"]["pages"]:
        title = page["title"]
        if title not in SAMPLES or title in found:
            raise RuntimeError("Independent revision response contains an unexpected page")
        found.add(title)
        revision = page["revisions"][0]
        body = revision["slots"]["main"]["content"].encode("utf-8")
        check = value["catalog"]["pages"][title]
        if (revision["revid"] != check["metadata"]["revision"] or page["pageid"] != check["metadata"]["page_id"]
                or len(body) != check["metadata"]["bytes"] or hashlib.sha256(body).hexdigest() != check["content_sha256"]):
            raise RuntimeError("Independent source revision differs from its saved observation")
    if found != set(SAMPLES):
        raise RuntimeError("Independent revision response is incomplete")
    result = {"checked_at": now.isoformat(), "source": SOURCE, "observation_id": hashlib.sha256(json_bytes(value)).hexdigest(),
              "first": {**first_metrics, "elapsed_seconds": round(elapsed, 4), "peak_python_bytes": peak},
              "repeat": {**repeat_metrics, "elapsed_seconds": round(repeat_elapsed, 4), "pointer_stable": True},
              "expiry": expiry_metrics, "inventory_count": value["catalog"]["inventory_count"],
              "checked_statuses": dict(Counter(check["status"] for check in value["catalog"]["pages"].values())),
              "unresolved": unresolved(value),
              "samples": checks, "independent_revision_bytes": len(raw), "independently_checked_pages": len(found),
              "observation_bytes": len(json_bytes(value)), "scope": "adapter acceptance; not integrated or published"}
    write_changed(root / "acceptance.json", json_bytes(result))
    print(json_bytes(result).decode())


if __name__ == "__main__":
    main()
