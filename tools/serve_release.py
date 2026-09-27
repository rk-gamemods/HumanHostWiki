"""Preview a committed release locally, substituting local origins in routes only."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wikibuild import release
from wikibuild.storage import within


def handler(root, manifest):
    routes = {urlsplit(base).path.strip('/'): root / manifest['repositories'][topic]['path'] / 'site'
              for topic, base in manifest['routes'].items()}
    replacements = {base.encode(): (urlsplit(base).path).encode() for base in manifest['routes'].values()}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parts = unquote(urlsplit(self.path).path).strip('/').split('/', 1)
            if parts[0] not in routes:
                self.send_error(404)
                return
            base = routes[parts[0]]
            name = parts[1] if len(parts) == 2 else ''
            if not name or name.endswith('/'):
                name += 'index.html'
            try:
                path = within(base, name)
            except ValueError:
                self.send_error(404)
                return
            status = 200
            if not path.is_file():
                if name.startswith('entry/'):
                    path, status = base / '404.html', 404
                else:
                    self.send_error(404)
                    return
            data = path.read_bytes()
            if path.suffix == '.html' or path.name == 'reader.json' or path.parent.name == 'releases':
                for origin, local in replacements.items():
                    data = data.replace(origin, local)
            self.send_response(status)
            self.send_header('Content-Type', mimetypes.guess_type(str(path))[0] or 'application/octet-stream')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    identity = json.loads((ROOT / 'releases/latest.json').read_text())['release_id']
    manifest = release.read(ROOT, identity)
    release.verify(ROOT, manifest)
    with ThreadingHTTPServer(('127.0.0.1', args.port), handler(ROOT, manifest)) as server:
        print(f"READY http://127.0.0.1:{server.server_port}{urlsplit(manifest['routes']['hub']).path} release={identity}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
