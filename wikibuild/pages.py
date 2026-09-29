"""Pure reader shells and bounded, readable Git reference pages."""

from html import escape
from urllib.parse import urlencode, quote


def entry(base, entity, snapshot, candidate):
    return f"{base}entry/{quote(entity, safe='')}/?{urlencode({'snapshot': snapshot, 'release': candidate})}"


def shell(title, base, project_name="Unofficial game reference", fonts_base=None):
    """Static page shell for every site. reader.js fills #content; the ids are its contract."""
    title, base, brand = escape(title), escape(base, quote=True), escape(project_name)
    head, sep, tail = brand.rpartition(" for ")
    mark = f"{head} <em>for {tail}</em>" if sep else brand
    fonts = f'<link rel="stylesheet" href="{escape(fonts_base, quote=True)}fonts/fonts.css">' if fonts_base else ""
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} | {brand}</title>'
            f'{fonts}<link rel="stylesheet" href="{base}reader.css"><script defer src="{base}reader.js"></script></head>'
            '<body><a class="skip" href="#content">Skip to content</a>'
            f'<header class="mast"><a class="brand" id="home">{mark}</a><div class="mast-r">'
            '<form id="search-form" role="search" aria-label="Search the wiki"><label class="sr-only" for="search">Search the wiki</label>'
            '<input id="search" type="search" placeholder="Search" autocomplete="off"><kbd aria-hidden="true">/</kbd></form>'
            '<nav id="topics" aria-label="Sections"></nav></div>'
            '<p class="aff">An unofficial community project. Not affiliated with or endorsed by Virtual Matrix Studio.</p></header>'
            '<div class="edition"><span id="status" role="status">Loading the selected game version...</span>'
            '<label>Game version <select id="version"></select></label></div>'
            '<main id="content" tabindex="-1"></main>'
            '<footer class="hh-footer"><p>Human Host is created by Virtual Matrix Studio. This community reference is free and ad-free.</p>'
            "<p>Values come from the game's files. The game's code or settings can change them in play.</p>"
            '<p id="credits"></p></footer><noscript>This wiki needs JavaScript. Generated Markdown reference pages '
            'remain available in each topic repository.</noscript></body></html>\n').encode("utf-8")


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
