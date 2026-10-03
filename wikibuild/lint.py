"""Pure checks for jargon in player-facing card text."""

import re


_TOKEN = re.compile(r"[A-Za-z0-9_]+")
_CODE_UNDERSCORE = re.compile(r"^_+[A-Za-z0-9]|[A-Za-z0-9]_[A-Za-z0-9]")
# A lowercase-to-capital hump is code (BuildMat, MeleeWeapon). Digits between capitals are model names (M1A, M4A1, AK74M).
_CODE_CAPITALS = re.compile(r"[a-z][A-Z]|[A-Z][a-z]+[A-Z]")
# A hex run needs at least one letter a-f; plain numbers such as Steam build 25587699 are not keys.
_HEX = re.compile(r"(?<![A-Za-z0-9])(?:e-)?(?=[0-9a-f]*[a-f])[0-9a-f]{8,}(?![A-Za-z0-9])|(?<![A-Za-z0-9])e-[0-9a-f]+(?![A-Za-z0-9])", re.I)
_PATH = re.compile(
    r"(?<!\w)bundles/[^\s,;)}\]]+|::serialized|"
    r"(?<![\w.])(?:[\w.-]+[/\\])*[\w.-]+\.[A-Za-z][A-Za-z0-9]{0,7}(?!\w)", re.I)
_RAW_FLOAT = re.compile(r"(?<![\w.])[+-]?(?:\d+)?\.\d{5,}(?![\w.])")
_BARE_INTEGER = re.compile(r"\s*[+-]?\d+\s*\Z")


def jargon(text: str, *, coded: bool = False) -> list[dict]:
    """Return one finding for each identifier, path, hex run, or raw number."""
    if not isinstance(text, str):
        return []
    hits = []
    occupied = []
    for rule, pattern in (("path", _PATH), ("raw_float", _RAW_FLOAT), ("hex", _HEX)):
        for match in pattern.finditer(text):
            span = match.span()
            if any(span[0] < end and start < span[1] for start, end in occupied):
                continue
            hits.append((span[0], {"rule": rule, "match": match.group()}))
            occupied.append(span)
    for match in _TOKEN.finditer(text):
        token = match.group()
        if any(match.start() < end and start < match.end() for start, end in occupied):
            continue
        if _CODE_UNDERSCORE.search(token) or _CODE_CAPITALS.search(token):
            hits.append((match.start(), {"rule": "identifier", "match": token}))
    if coded and _BARE_INTEGER.fullmatch(text):
        hits.append((0, {"rule": "raw_enum", "match": text.strip()}))
    return [finding for _, finding in sorted(hits, key=lambda row: (row[0], row[1]["rule"]))]


def card_findings(card: dict, *, coded_fields=()) -> list[dict]:
    """Lint only strings displayed in a player card, with JSON pointer locations."""
    findings = []

    def check(value, pointer, *, coded=False):
        if isinstance(value, str):
            findings.extend({**finding, "field": pointer} for finding in jargon(value, coded=coded))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                check(child, f"{pointer}/{index}")
        elif isinstance(value, dict):
            for key, child in value.items():
                if key != "target":
                    escaped = str(key).replace("~", "~0").replace("/", "~1")
                    check(child, f"{pointer}/{escaped}")

    check(card.get("eyebrow", []), "/eyebrow")
    for index, stat in enumerate(card.get("stats", [])):
        check(stat.get("label"), f"/stats/{index}/label")
        check(stat.get("display"), f"/stats/{index}/display",
              coded=stat.get("coded", False) or stat.get("format") == "coded" or
              stat.get("field") in coded_fields)
    for index, note in enumerate(card.get("notes", [])):
        check(note.get("text"), f"/notes/{index}/text")
    return findings
