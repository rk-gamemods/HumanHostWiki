"""Pure reader shells and bounded, readable Git reference pages."""

from html import escape
from urllib.parse import urlencode, quote


def entry(base, entity, snapshot, candidate):
    return f"{base}entry/{quote(entity, safe='')}/?{urlencode({'snapshot': snapshot, 'release': candidate})}"


def shell(title, base):
    title, base = escape(title), escape(base, quote=True)
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} | Human Host Wiki</title>'
            f'<link rel="stylesheet" href="{base}reader.css"><script defer src="{base}reader.js"></script></head>'
            '<body><a class="skip" href="#content">Skip to content</a><header><div class="brand">'
            '<a id="home">Human Host Wiki</a><span>Independent community reference</span></div>'
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
        if row.get("preview"):
            lines += ["| Field | Extracted value |", "| --- | --- |"]
            for field, value in row["preview"].items():
                lines.append(f"| {escape(field).replace('|', '&#124;')} | {escape(str(value)).replace('|', '&#124;').replace(chr(10), '<br>')} |")
            lines.append("")
    return ("\n".join(lines) + "\n").encode("utf-8")
