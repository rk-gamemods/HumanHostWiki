"""Bounded, read-only MediaWiki observations. No article bodies leave this adapter."""

from collections import deque
from html import unescape
import json
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .storage import ContractError, digest, json_bytes

MAX_RESPONSE = 1024 * 1024
MAX_TRANSFER = 8 * 1024 * 1024
MAX_REQUESTS = 256
MAX_PAGES = 4096
MAX_ARTICLE = 64 * 1024
USER_AGENT = "HumanHostWiki/1.0 (https://github.com/rk-gamemods/HumanHost-Wiki)"


class RemoteError(ValueError):
    """A remote observation failed; this never grants a missing-page conclusion."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RemoteError("api-redirect")


def validate(options):
    fields = {"api_url", "namespace", "namespace_name", "prefixes", "titles"}
    if type(options) is not dict or set(options) != fields:
        raise ContractError("MediaWiki options require api_url, namespace, namespace_name, prefixes and titles")
    if (not isinstance(options["api_url"], str) or len(options["api_url"]) > 2048
            or re.search(r"[\x00-\x20\x7f]", options["api_url"])):
        raise ContractError("MediaWiki API URL must be bounded text without whitespace or controls")
    try:
        url = urlsplit(options["api_url"])
        url.port
    except ValueError as exc:
        raise ContractError("Invalid MediaWiki API URL") from exc
    if (url.scheme != "https" or not url.hostname or url.username is not None or url.password is not None
            or url.query or url.fragment or not url.path.endswith("/api.php")):
        raise ContractError("MediaWiki API must be an absolute canonical HTTPS api.php URL")
    if type(options["namespace"]) is not int or options["namespace"] < 0:
        raise ContractError("MediaWiki namespace must be a nonnegative integer")
    if not isinstance(options["namespace_name"], str) or not re.fullmatch(r"[\w -]{1,100}", options["namespace_name"]):
        raise ContractError("MediaWiki namespace name is invalid")
    for field in ("prefixes", "titles"):
        values = options[field]
        if (type(values) is not list or len(values) > 64
                or any(not valid_title(value, options) for value in values) or len(set(values)) != len(values)):
            raise ContractError("MediaWiki selections must contain unique titles within the configured namespace")


def valid_title(value, options):
    return (isinstance(value, str) and value.startswith(options["namespace_name"] + ":")
            and bool(value[len(options["namespace_name"]) + 1:].strip())
            and len(value) <= 512 and value == value.strip() and not re.search(r"[\x00-\x1f\x7f|#\[\]{}]", value))


class Client:
    """One run's serial GET requests, with byte/count limits and no hidden retries."""

    def __init__(self, api_url):
        self.api_url = api_url
        self.opener = build_opener(NoRedirect())
        self.requests = self.bytes = 0

    def __call__(self, parameters):
        if self.requests >= MAX_REQUESTS or self.bytes >= MAX_TRANSFER:
            raise RemoteError("request-budget-exhausted")
        query = {**parameters, "action": "query", "format": "json", "formatversion": 2, "maxlag": 5}
        request = Request(self.api_url + "?" + urlencode(query), headers={
            "User-Agent": USER_AGENT, "Accept": "application/json", "Accept-Encoding": "identity"})
        self.requests += 1
        limit = min(MAX_RESPONSE, MAX_TRANSFER - self.bytes)
        try:
            with self.opener.open(request, timeout=30) as response:
                if response.status != 200 or response.headers.get_content_type() != "application/json":
                    raise RemoteError("unexpected-http-response")
                raw = response.read(limit + 1)
            self.bytes += len(raw)
            if len(raw) > limit:
                raise RemoteError("response-budget-exhausted")
            value = json.loads(raw)
        except (OSError, UnicodeError, ValueError, RecursionError) as exc:
            if isinstance(exc, RemoteError):
                raise
            raise RemoteError("request-failed") from exc
        if type(value) is not dict or "error" in value or "errors" in value or "warnings" in value:
            raise RemoteError("api-error-or-warning")
        return value


def literal_formatting(text):
    """Remove reviewed, attribute-free formatting, preserving line and word boundaries.

    This is a literal-content check, not an HTML renderer. Unknown markup,
    attributes and malformed nesting remain exceptions. In particular, a hidden
    element or a template cannot supply evidence of a populated destination.
    """
    stack = []

    def replace(match):
        token = match[0].lower()
        if re.fullmatch(r"<br\s*/?>", token):
            return "\n"
        found = re.fullmatch(r"<(/?)(u|code)>", token)
        if found is None:
            raise ValueError("unsupported markup")
        closing, tag = found.groups()
        if closing:
            if not stack or stack.pop() != tag:
                raise ValueError("mismatched formatting")
        else:
            stack.append(tag)
        return ""

    text = re.sub(r"</?[A-Za-z][^>]*>", replace, text)
    if stack or re.search(r"</?[A-Za-z]|<!|<\?", text):
        raise ValueError("unfinished markup")
    return text


def article_state(content):
    """Recognize literal prose, numeric properties or table data; never execute markup."""
    text = re.sub(r"<!--.*?-->", "", content, flags=re.S)
    if "<!--" in text or "{{" in text or "}}" in text:
        return "unavailable", "unsupported-markup"
    try:
        text = literal_formatting(text)
    except ValueError:
        return "unavailable", "unsupported-markup"
    text = re.sub(r"\[\[(?:File|Image|Category):[^\]]*\]\]", "", text, flags=re.I)
    body = []
    for line in text.splitlines():
        line = line.strip()
        if (not line or line.startswith("=") or re.match(r"(?i)return\s+to\s*:", line)
                or re.search(r"(?i)\b(under construction|coming soon|work in progress|to be added|to be written|placeholder|todo|tbd)\b", line)):
            continue
        # A list of destinations is navigation, even when its link labels are long.
        outside_links = re.sub(r"\[\[[^\]]*\]\]|\[https?://[^\]]*\]", "", line)
        if not outside_links.strip(" *#;:-'"):
            continue
        line = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: m[2] or m[1], line)
        line = re.sub(r"\[https?://\S+\s+([^\]]+)\]", r"\1", line)
        line = unescape(line).strip(" *#;'")
        if re.match(r"[A-Za-z][A-Za-z '()/%-]{1,64}:\s*(?:x\s*)?[+-]?\d", line):
            return "populated", "literal-property"
        if line.startswith("|") and not line.startswith(("|-", "|}", "|+")):
            cells = line[1:].split("||")
            if len(cells) >= 2 and any(re.search(r"\d", cell) for cell in cells):
                return "populated", "literal-table-row"
        elif not line.startswith(("{|", "!")):
            body.append(line)
    words = re.findall(r"\b[A-Za-z][A-Za-z'-]+\b", " ".join(body))
    return ("populated", "literal-prose") if len(words) >= 8 else ("empty", "no-recognized-article-body")


def metadata(page, options):
    if (type(page) is not dict or page.get("ns") != options["namespace"]
            or not valid_title(page.get("title"), options)):
        raise RemoteError("invalid-page-identity")
    for field in ("pageid", "lastrevid", "length"):
        if type(page.get(field)) is not int or page[field] < (0 if field == "length" else 1):
            raise RemoteError("invalid-page-metadata")
    if not isinstance(page.get("contentmodel"), str):
        raise RemoteError("invalid-content-model")
    return {"title": page["title"], "page_id": page["pageid"], "revision": page["lastrevid"],
            "bytes": page["length"], "content_model": page["contentmodel"], "redirect": "redirect" in page}


def selected(title, options):
    return title in options["titles"] or any(title == prefix or title.startswith(prefix + "/") for prefix in options["prefixes"])


def collect(options, previous=None, *, request=None, progress=None):
    """Return compact checks, not copied articles. Prior checks must be validated by the caller."""
    validate(options)
    client = Client(options["api_url"]) if request is None else request
    inventory, seen_tokens, seen_ids, seen_revisions = {}, set(), set(), set()
    complete, cursor, errors = False, {}, []
    while len(inventory) <= MAX_PAGES:
        try:
            response = client({"generator": "allpages", "gapnamespace": options["namespace"],
                               "gaplimit": 500, "prop": "info", **cursor})
            pages = response.get("query", {}).get("pages", [])
            if type(pages) is not list or (not pages and "batchcomplete" not in response and "continue" not in response):
                raise RemoteError("invalid-inventory-response")
            for page in pages:
                item = metadata(page, options)
                if (item["title"] in inventory or item["page_id"] in seen_ids
                        or item["revision"] in seen_revisions or len(inventory) >= MAX_PAGES):
                    raise RemoteError("duplicate-or-excessive-inventory")
                inventory[item["title"]] = item
                seen_ids.add(item["page_id"])
                seen_revisions.add(item["revision"])
            if "continue" not in response:
                complete = True
                break
            cursor = response["continue"]
            if (type(cursor) is not dict or set(cursor) != {"continue", "gapcontinue"}
                    or any(not isinstance(value, str) or len(value) > 1024 for value in cursor.values())):
                raise RemoteError("invalid-continuation")
            token = json_bytes(cursor)
            if token in seen_tokens or len(seen_tokens) >= MAX_PAGES:
                raise RemoteError("repeated-or-excessive-continuation")
            seen_tokens.add(token)
        except (RemoteError, OSError, AttributeError, TypeError):
            errors.append("inventory-unavailable")
            break
    checks, pending, reused = {}, deque(), 0
    for title, item in sorted(inventory.items()):
        if not selected(title, options):
            continue
        old = (previous or {}).get(title)
        if old and old["metadata"] == item and "content_sha256" in old:
            checks[title] = dict(old)
            reused += 1
            continue
        checks[title] = {"metadata": item, "status": "unavailable", "reason": "revision-unavailable"}
        if item["content_model"] != "wikitext":
            checks[title]["reason"] = "unsupported-content-model"
        elif item["bytes"] > MAX_ARTICLE:
            checks[title]["reason"] = "article-budget-exceeded"
        else:
            pending.append(title)
    # Small batches bound transient body storage. The metadata length also avoids
    # requesting a known oversized article alongside otherwise supported pages.
    while pending:
        batch, size = [], 0
        while pending and len(batch) < 10 and size + inventory[pending[0]]["bytes"] <= 128 * 1024:
            title = pending.popleft()
            size += inventory[title]["bytes"]
            batch.append(title)
        if progress:
            progress(f"Checking {len(batch)} changed community-wiki articles")
        expected = {inventory[title]["revision"]: title for title in batch}
        try:
            response = client({"prop": "revisions", "revids": "|".join(map(str, expected)),
                               "rvprop": "ids|content", "rvslots": "main"})
            pages = response.get("query", {}).get("pages", [])
            if type(pages) is not list or "continue" in response:
                raise RemoteError("invalid-revisions-response")
            found = set()
            for page in pages:
                for revision in page.get("revisions", []):
                    revision_id = revision.get("revid")
                    if revision_id not in expected or revision_id in found:
                        raise RemoteError("unexpected-revision")
                    found.add(revision_id)
                    title = expected[revision_id]
                    item = inventory[title]
                    if (page.get("pageid") != item["page_id"] or page.get("title") != title
                            or page.get("ns") != options["namespace"]):
                        continue
                    slot = revision.get("slots", {}).get("main", {})
                    content = slot.get("content")
                    if (slot.get("contentmodel") != "wikitext" or not isinstance(content, str)
                            or len(content.encode("utf-8")) != item["bytes"] or item["bytes"] > MAX_ARTICLE):
                        continue
                    check = checks[title]
                    check["content_sha256"] = digest(content.encode("utf-8"))
                    if item["redirect"]:
                        check["reason"] = "redirect-requires-destination-check"
                        target = re.fullmatch(r"\s*#redirect\s*\[\[([^\]|#]+)\]\]\s*", content, re.I)
                        if target:
                            check["redirect_target"] = target[1].replace("_", " ").strip()
                    else:
                        check["status"], check["reason"] = article_state(content)
        except (RemoteError, OSError, AttributeError, TypeError):
            # Keep independently checked pages; no negative result comes from a
            # transport or schema failure, and subsequent batches still run.
            errors.append("revision-batch-unavailable")
    for title, check in checks.items():
        if not check["metadata"]["redirect"]:
            continue
        check.pop("destination", None)
        check.update(status="unavailable", reason="redirect-destination-unavailable")
        seen, destination = {title}, check.get("redirect_target")
        while destination in checks and destination not in seen:
            seen.add(destination)
            target = checks[destination]
            if not target["metadata"]["redirect"]:
                check.update(status=target["status"], reason="redirect-" + target["status"])
                if target["status"] == "populated":
                    check["destination"] = destination
                break
            destination = target.get("redirect_target")
    return {"inventory_complete": complete, "inventory_count": len(inventory),
            "inventory_sha256": digest(json_bytes(inventory)), "pages": checks}, {
                "requests": getattr(client, "requests", None), "response_bytes": getattr(client, "bytes", None),
                "reused_articles": reused, "checked_articles": len(checks) - reused, "errors": errors}
