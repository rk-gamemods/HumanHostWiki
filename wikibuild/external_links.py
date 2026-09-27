"""Immutable article checks and offline exact-title matching for external backlinks."""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlencode

from . import mediawiki
from .storage import ContractError, digest, json_bytes, within, write_changed

MAX_RECEIPT = 8 * 1024 * 1024


def contract():
    return {name: digest((Path(__file__).parent / name).read_bytes().replace(b"\r\n", b"\n"))
            for name in ("external_links.py", "mediawiki.py")}


def read(root, identity):
    if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{64}", identity):
        raise ContractError("Invalid external-link observation ID")
    path = within(root, f"external-links/{identity}.json")
    if path.stat().st_size > MAX_RECEIPT:
        raise ContractError("External-link observation exceeds its byte limit")
    value = json.loads(path.read_bytes())
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1 or digest(json_bytes(value)) != identity:
        raise ContractError("External-link observation was modified")
    mediawiki.validate(value["source"])
    catalog = value["catalog"]
    if type(catalog["inventory_complete"]) is not bool or len(catalog["pages"]) > mediawiki.MAX_PAGES:
        raise ContractError("Invalid external-link inventory")
    for title, check in catalog["pages"].items():
        if (not mediawiki.selected(title, value["source"]) or title != check["metadata"]["title"]
                or check["status"] not in {"populated", "empty", "unavailable"}):
            raise ContractError("Invalid external-link page check")
    return value


def latest(root):
    pointer = within(root, "external-links/latest.json")
    return read(root, json.loads(pointer.read_bytes())["observation_id"]) if pointer.exists() else None


def refresh(root, source, progress=None, *, now=None, request=None, cache_seconds=3600, retry_seconds=60):
    """Caller holds writer_lock. This is the only entrypoint allowed to contact the provider."""
    mediawiki.validate(source)
    source_bytes = json_bytes(source)
    if any(type(n) is not int or not 1 <= n <= 86400 for n in (cache_seconds, retry_seconds)):
        raise ContractError("External-link cache intervals must be between 1 and 86400 seconds")
    now = datetime.now(timezone.utc) if now is None else now
    if now.tzinfo is None or now.utcoffset() is None:
        raise ContractError("External-link check time requires a timezone")
    rules, current = contract(), latest(root)
    compatible = current and current["source"] == source and current["contract"] == rules
    if compatible:
        age = (now - datetime.fromisoformat(current["checked_at"])).total_seconds()
        if 0 <= age < (retry_seconds if current["retryable"] else cache_seconds):
            return current, {"reused": True, "requests": 0, "response_bytes": 0}
    previous, cache_base = {}, None
    if compatible:
        cache_base = digest(json_bytes(current)) if not current["retryable"] else current["cache_base"]
        if current["retryable"] and cache_base:
            cached = read(root, cache_base)
            if cached["source"] != source or cached["contract"] != rules or cached["retryable"]:
                raise ContractError("External-link cache base differs from the requested source and rules")
            previous.update(cached["catalog"]["pages"])
        for title, check in current["catalog"]["pages"].items():
            if "content_sha256" in check:
                previous[title] = check
    catalog, metrics = mediawiki.collect(json.loads(source_bytes), previous, request=request, progress=progress)
    value = {"schema_version": 1, "source": json.loads(source_bytes), "contract": rules,
             "checked_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"), "catalog": catalog,
             "cache_base": cache_base,
             "retryable": bool(metrics["errors"]) or any(check["reason"] == "revision-unavailable"
                 for check in catalog["pages"].values())}
    if contract() != rules or json_bytes(source) != source_bytes:
        raise ContractError("External-link rules or source changed during observation")
    data = json_bytes(value)
    if len(data) > MAX_RECEIPT:
        raise ContractError("External-link observation exceeds its byte limit")
    identity = digest(data)
    path = within(root, f"external-links/{identity}.json")
    if path.exists() and path.read_bytes() != data:
        raise ContractError("External-link observation collision")
    write_changed(path, data)
    read(root, identity)
    write_changed(within(root, "external-links/latest.json"), json_bytes({"observation_id": identity}))
    return value, {"reused": False, **metrics}


def lookup(observation, title):
    """A URL exists only for a checked, populated destination. No network or filesystem access."""
    source, catalog = observation["source"], observation["catalog"]
    result = {"title": title, "checked_at": observation["checked_at"], "status": "unavailable"}
    if not mediawiki.valid_title(title, source) or not mediawiki.selected(title, source):
        return {**result, "reason": "outside-selected-titles"}
    check = catalog["pages"].get(title)
    if check is None:
        return {**result, "status": "missing" if catalog["inventory_complete"] else "unavailable",
                "reason": "absent-from-complete-index" if catalog["inventory_complete"] else "incomplete-index"}
    result.update(status=check["status"], reason=check["reason"], revision=check["metadata"]["revision"])
    if check["status"] == "populated":
        destination = check.get("destination", title)
        revision = catalog["pages"][destination]["metadata"]["revision"]
        result.update(destination=destination, destination_revision=revision,
                      url=source["api_url"].removesuffix("api.php") + "index.php?" + urlencode({
                          "title": destination, "oldid": revision}))
    return result


def normalized_name(value):
    return " ".join(unicodedata.normalize("NFKC", value).replace("_", " ").split()).casefold()


class Matcher:
    """Build once per observation; look up entity names without scanning every page per entity."""

    def __init__(self, observation):
        self.observation, self.names = observation, {}
        for title in observation["catalog"]["pages"]:
            leaf = title.split(":", 1)[1].rsplit("/", 1)[-1]
            self.names.setdefault(normalized_name(leaf), []).append(title)

    def entity(self, name, prefixes):
        source = self.observation["source"]
        if any(prefix not in source["prefixes"] for prefix in prefixes):
            raise ContractError("Entity matching uses an unobserved title prefix")
        candidates = sorted(title for title in self.names.get(normalized_name(name), [])
                            if any(title.startswith(prefix + "/") for prefix in prefixes))
        complete = self.observation["catalog"]["inventory_complete"]
        if len(candidates) == 1 and complete:
            return lookup(self.observation, candidates[0])
        return {"status": "missing" if not candidates and complete else "unavailable",
                "reason": "incomplete-index" if not complete else "ambiguous-title" if candidates else "no-exact-title",
                "checked_at": self.observation["checked_at"], "candidates": candidates}
