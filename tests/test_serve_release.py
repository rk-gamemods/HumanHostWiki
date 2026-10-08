"""Preview routes match static host directory and historical fallback behavior."""

import http.client
from http.server import ThreadingHTTPServer
from pathlib import Path
import threading
import unittest

from tests._support import fixture_dir

from tools.serve_release import handler


class PreviewRouteTests(unittest.TestCase):
    def test_hub_search_and_guide_routes_use_the_frozen_shell(self):
        root = fixture_dir(self, "serve_hub")
        for topic in ("hub", "items"):
            site = root / topic / "site"
            site.mkdir(parents=True)
            (site / "404.html").write_bytes(b"<head></head>fallback")
        manifest = {"repositories": {
            topic: {"path": topic, "github_name": "Wiki-" + topic}
            for topic in ("hub", "items")},
            "routes": {"hub": "https://fixture.github.io/Wiki-hub/"}}
        with ThreadingHTTPServer(("127.0.0.1", 0), handler(root, manifest)) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
                for route in ("search/?q=Crude+Axe", "guide/getting-started/?snapshot=old"):
                    connection.request("GET", "/Wiki-hub/" + route)
                    response = connection.getresponse()
                    self.assertEqual(response.status, 404)
                    body = response.read()
                    self.assertTrue(body.endswith(b"fallback"))
                    self.assertIn(b"humanHostPreviewOrigin", body)
                for route in ("/Wiki-items/search/", "/Wiki-hub/releases/missing.json"):
                    connection.request("GET", route)
                    response = connection.getresponse()
                    self.assertEqual(response.status, 404)
                    self.assertNotIn(b"fallback", response.read())
                connection.close()
            finally:
                server.shutdown()
                thread.join()

    def test_existing_groups_and_new_groups_under_frozen_front_keep_the_shell(self):
        folder = str(fixture_dir(self, "serve_re"))
        root = Path(folder)
        site = root / "items/site"
        (site / "groups/item").mkdir(parents=True)
        (site / "groups/item/index.html").write_bytes(b"<head></head>group")
        (site / "404.html").write_bytes(b"<head></head>fallback")
        (site / "reader.json").write_bytes(b'{"unchanged":true}')
        manifest = {"repositories": {"items": {"path": "items", "github_name": "Wiki-items"}},
                    "routes": {"hub": "https://fixture.github.io/Wiki-hub/"}}
        with ThreadingHTTPServer(("127.0.0.1", 0), handler(root, manifest)) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
                for path, status, suffix in (("groups/item/?snapshot=old", 200, b"group"),
                                              ("groups/new/", 404, b"fallback"),
                                              ("entry/e-123/", 404, b"fallback"),
                                              ("reader.json", 200, b'{"unchanged":true}')):
                    connection.request("GET", "/Wiki-items/" + path)
                    response = connection.getresponse()
                    self.assertEqual(response.status, status)
                    self.assertTrue(response.read().endswith(suffix))
                connection.request("GET", "/Wiki-items/releases/missing.json")
                response = connection.getresponse()
                self.assertEqual(response.status, 404)
                self.assertNotIn(b"fallback", response.read())
                connection.close()
            finally:
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    unittest.main()
