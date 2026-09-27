"""Deterministic local navigation preview; no gameplay content or release claims."""

from html import escape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import uuid
from urllib.parse import unquote, urlparse

from .storage import ContractError, digest, json_bytes, within, write_changed

CSS = """body{font:17px/1.6 system-ui,sans-serif;max-width:980px;margin:3rem auto;padding:0 1.5rem;color:#192532;background:#f5f7fa}a{color:#155ab0}header,article{background:white;padding:1.2rem 1.5rem;margin:1rem 0;border:1px solid #d8e0e8;border-radius:8px}h1,h2{line-height:1.2}.status{padding:.8rem;background:#fff3cd;border-left:4px solid #b58400}nav ul{columns:2}footer{font-size:.9rem;color:#435365}code{overflow-wrap:anywhere}@media(max-width:600px){nav ul{columns:1}body{margin:1rem auto}}"""


def render(manifest, receipt):
    repositories = manifest["repositories"]
    by_id = {repo["id"]: repo for repo in repositories}
    source = "No input snapshot selected."
    if receipt:
        source = (f"Input: Steam build {escape(receipt['steam']['build_id'])}; "
                  f"source commit {escape(receipt['source_commit'])}. "
                  f"Application version: {escape(receipt.get('game_version') or 'unknown')}. "
                  "Wiki verification not performed. Latest available build unknown.")
    official = " | ".join(f'<a href="{escape(link["url"], quote=True)}">{escape(link["title"])}</a>'
                          for link in manifest["official_links"])

    def shell(title, body, nested=False):
        home = "../index.html" if nested else "index.html"
        prefix = "" if nested else "topics/"
        nav = "".join(f'<li><a href="{prefix}{repo["id"]}.html">{escape(repo["title"])}</a></li>'
                      for repo in repositories if repo["role"] == "topic")
        return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)} | Human Host Wiki</title>'
                f'<style>{CSS}</style></head><body><header><a href="{home}">Human Host Wiki: start here</a>'
                f'<h1>{escape(title)}</h1><p class="status">Architecture preview. Gameplay articles are not generated.</p>'
                f'<p>{source}</p></header>{body}<nav aria-label="Topics"><h2>Explore topics</h2><ul>{nav}</ul></nav>'
                f'<footer><p>Independent community reference for players and modders. Free and ad-free.</p>'
                f'<p>{official}</p></footer></body></html>\n').encode("utf-8")

    cards = "".join(f'<article><h2><a href="topics/{repo["id"]}.html">{escape(repo["title"])}</a></h2>'
                    f'<p>{escape(repo["coverage"])}</p></article>' for repo in repositories if repo["role"] == "topic")
    files = {"index.html": shell("Start here", '<p>Choose a subject below. The hub will also host curated guides and version navigation.</p>' + cards)}
    for repo in repositories:
        if repo["role"] != "topic":
            continue
        relations = []
        for edge in manifest["relationships"]:
            if repo["id"] == edge["from"]:
                relations.append(f'<li>{escape(edge["kind"])}: <a href="{edge["to"]}.html">{escape(by_id[edge["to"]]["title"])}</a></li>')
            elif repo["id"] == edge["to"]:
                relations.append(f'<li>Referenced by <a href="{edge["from"]}.html">{escape(by_id[edge["from"]]["title"])}</a> ({escape(edge["kind"])})</li>')
        body = (f'<article><p>{escape(repo["coverage"])}</p><p>Local repository: <code>{escape(repo["path"])}</code>.</p>'
                f'<p>Intended GitHub name: <code>{escape(repo["github_name"])}</code>. Remote not created.</p>'
                '<p>Content status: planned. No claim of topic completeness or game-version verification.</p></article>'
                '<h2>Related subjects</h2><ul>' + "".join(relations) + '</ul>')
        files[f"topics/{repo['id']}.html"] = shell(repo["title"], body, nested=True)
    return files


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs.extend(value for key, value in attrs if key == "href")


def validate_links(files):
    base = Path.cwd().resolve() / "virtual-site"
    for name, data in files.items():
        parser = Links()
        parser.feed(data.decode("utf-8"))
        for href in parser.hrefs:
            parsed = urlparse(href)
            if parsed.scheme:
                if parsed.scheme != "https":
                    raise ContractError(f"Unexpected URL scheme in {name}: {href}")
                continue
            target = (base / name).parent / unquote(parsed.path)
            target = target.resolve()
            if not target.is_relative_to(base) or target.relative_to(base).as_posix() not in files:
                raise ContractError(f"Broken local link in {name}: {href}")


def build(root, manifest, receipt=None):
    files = render(manifest, receipt)
    validate_links(files)
    # Include source bytes so renderer/tool changes invalidate prior builds too.
    tool_hashes = {path.relative_to(root).as_posix(): digest(path.read_bytes().replace(b"\r\n", b"\n"))
                   for path in sorted((root / "wikibuild").glob("*.py"))}
    inputs = {"schema_version": 1, "project": manifest, "snapshot": receipt, "tools": tool_hashes,
              "kind": "architecture-preview"}
    build_id = digest(json_bytes(inputs))
    hashes = {name: digest(data) for name, data in sorted(files.items())}
    build_manifest = {"schema_version": 1, "build_id": build_id, "kind": "architecture-preview",
                      "files": hashes, "total_bytes": sum(len(data) for data in files.values())}
    files["build.json"] = json_bytes(build_manifest)
    destination = within(root, f".local/builds/{build_id}")
    if destination.exists():
        actual = {path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file()}
        if actual != set(files) or any(within(destination, name).read_bytes() != data for name, data in files.items()):
            raise ContractError("Existing preview was modified; preserve it and investigate before rebuilding")
    else:
        stage = within(root, f".local/build-stage/{uuid.uuid4().hex}")
        stage.mkdir(parents=True)
        for name, data in files.items():
            write_changed(within(stage, name), data)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.rename(stage, destination)
    # The previous preview remains selected until every output is complete.
    write_changed(within(root, ".local/preview.json"), json_bytes({"build_id": build_id, "entry": f".local/builds/{build_id}/index.html"}))
    return {"build_id": build_id, "entry": str(destination / "index.html"), "files": len(files),
            "bytes": build_manifest["total_bytes"], "kind": "architecture-preview"}
