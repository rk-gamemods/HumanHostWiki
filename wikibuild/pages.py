"""Pure reader shells and bounded, readable Git reference pages."""

from html import escape
from urllib.parse import urlencode, quote


def entry(base, entity, snapshot, candidate):
    return f"{base}entry/{quote(entity, safe='')}/?{urlencode({'snapshot': snapshot, 'release': candidate})}"


def shell(title, base, project_name="Unofficial game reference"):
    title, base, brand = escape(title), escape(base, quote=True), escape(project_name)
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} | {brand}</title>'
            f'<link rel="stylesheet" href="{base}reader.css"><script defer src="{base}reader.js"></script></head>'
            '<body><a class="skip" href="#content">Skip to content</a><header><div class="brand">'
            f'<a id="home">{brand}</a></div>'
            '<p>An unofficial community project. Not affiliated with or endorsed by Virtual Matrix Studio.</p>'
            f'<h1>{title}</h1><p id="status" role="status">Loading the selected snapshot...</p>'
            '<div class="controls"><label>Captured version <select id="version"></select></label>'
            '<form id="search-form" role="search"><label>Search this topic <input id="search" type="search" '
            'placeholder="Name, type or identifier"></label><button>Search</button></form></div></header>'
            '<div class="layout"><nav id="topics" aria-label="Topics"></nav><main id="content" tabindex="-1"></main></div>'
            '<footer><p>Human Host is created by Virtual Matrix Studio. This community reference is free and ad-free.</p>'
            '<p>Serialized facts may be modified by game code or settings. Unresolved interpretations remain labeled.</p>'
            '<p id="credits"></p></footer><noscript>This reader needs JavaScript. Generated Markdown reference pages '
            'remain available in the topic repository.</noscript></body></html>\n').encode("utf-8")


def markdown(kind, entries, snapshot, candidate, base):
    # HTML-escaped labels remain literal even when game text contains Markdown.
    lines = [f"# {escape(kind.replace('-', ' ').title())}", "", f"Snapshot: `{snapshot}`.", "",
             "Extracted reference. Gameplay verification has not been performed.", ""]
    for row in entries:
        name = escape(row["name"])
        href = escape(entry(base, row["entity_key"], snapshot, candidate), quote=True)
        lines += [f'<h2><a href="{href}">{name}</a></h2>', "", f'Wiki key: `{row["entity_key"]}`. Status: {row["status"]}.', ""]
        for note in row.get("explanations", []):
            lines += [f'<h3>{escape(note["title"])}</h3>', ""]
            if note["status"] == "passed":
                lines += [f'<p>{escape(note["text"])}</p>', f'<p>Declared {escape(note["scope"])} checks passed.</p>', ""]
            else:
                lines += [f'<p>Unverified explanation: {escape("; ".join(note["reasons"]))}</p>', ""]
            last = note.get("last_verified")
            if last:
                lines += [f'<p>Last successful check: Steam build {escape(last["build_id"])}; {escape(last["snapshot_id"])}.</p>', ""]
                if note["status"] != "passed":
                    lines += [f'<details><summary>Previously checked text</summary><p>{escape(last["text"])}</p></details>', ""]
        if row.get("preview"):
            lines += ["| Field | Extracted value |", "| --- | --- |"]
            for field, value in row["preview"].items():
                lines.append(f"| {escape(field).replace('|', '&#124;')} | {escape(str(value)).replace('|', '&#124;').replace(chr(10), '<br>')} |")
            lines.append("")
    return ("\n".join(lines) + "\n").encode("utf-8")
