"""Independent checks for shared, content-addressed font sets."""

import hashlib
import json
import re
from urllib.parse import urljoin


def reachable(fonts, fetch):
    if fonts is None:
        return
    files = fonts["files"]
    canonical = (json.dumps(files, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    identity = hashlib.sha256(canonical).hexdigest()
    assert fonts["base"].endswith("/fonts/" + identity + "/")
    assert "fonts.css" in files
    for name, meta in files.items():
        assert re.fullmatch(r"[A-Za-z0-9-]+\.(?:woff2|css|txt)", name)
        data = fetch({"path": urljoin(fonts["base"], name), **meta})
        assert len(data) == meta["bytes"] and hashlib.sha256(data).hexdigest() == meta["sha256"]
        if name == "fonts.css":
            urls = re.findall(r"url\(([^)]+)\)", data.decode())
            assert urls
            assert all(url.strip("\"'") in files for url in urls)


def compare(original, actual, fetch):
    assert (original is None) == (actual is None)
    if original is not None:
        assert {k: v for k, v in original.items() if k != "base"} == {k: v for k, v in actual.items() if k != "base"}
    reachable(actual, fetch)
