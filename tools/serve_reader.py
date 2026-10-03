"""Serve a pinned local reader candidate, including static-host entry fallbacks."""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wikibuild import reader
from wikibuild.storage import within


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parts = unquote(urlsplit(self.path).path).strip("/").split("/")
        # Like a static host, reader routes that are not files are served by the site's 404.html.
        routed = (len(parts) == 3 and parts[1] == "entry" and reader.ENTITY.fullmatch(parts[2])
                  or len(parts) == 3 and parts[1] == "guide" and re.fullmatch(r"[a-z0-9-]+", parts[2])
                  or len(parts) == 2 and parts[1] == "search")
        if routed:
            fallback = within(Path(self.directory), f"{parts[0]}/404.html")
            if fallback.is_file():
                data = fallback.read_bytes()
                self.send_response(404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
        super().do_GET()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", help="Candidate ID; defaults to last successful reader")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    candidate = args.candidate or json.loads((root / ".local/reader-latest.json").read_text())["candidate_id"]
    site = reader.candidate_path(within(root, ".local"), candidate)
    reader.verify(site, candidate)
    with ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, directory=str(site))) as server:
        print(f"READY http://127.0.0.1:{server.server_port}/hub/ candidate={candidate}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
