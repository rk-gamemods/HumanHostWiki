"""Declarative authored text with typed scalar checks, never executable expressions."""

import json
import math
from pathlib import PurePosixPath
import re

from .storage import ContractError, digest, json_bytes
from . import code_dependencies

ENTITY = re.compile(r"e-[0-9a-f]{32}\Z")
NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
SNAPSHOT = re.compile(r"build-[0-9]+-[0-9a-f]{12}\Z")
TYPES = {"integer": int, "number": (int, float), "string": str, "boolean": bool}
MAX_TEXT_BYTES = 16 * 1024


def validate(value):
    required = {"schema_version", "entity", "title", "since", "scope", "text", "facts", "code"}
    if not isinstance(value, dict) or set(value) != required or value["schema_version"] != 1:
        raise ContractError("Expected curated explanation schema 1 and its declared fields")
    if not isinstance(value["entity"], str) or not ENTITY.fullmatch(value["entity"]):
        raise ContractError("Explanation needs a stable entry key")
    if not isinstance(value["since"], str) or not SNAPSHOT.fullmatch(value["since"]):
        raise ContractError("Explanation needs a starting captured snapshot")
    if not isinstance(value["title"], str) or not 1 <= len(value["title"]) <= 160:
        raise ContractError("Explanation title must contain 1 to 160 characters")
    if value["scope"] not in {"selected-data", "code-backed"}:
        raise ContractError("Unknown explanation check scope")
    facts = value["facts"]
    if not isinstance(facts, dict) or not 1 <= len(facts) <= 64:
        raise ContractError("Explanation needs 1 to 64 named fact dependencies")
    for name, spec in facts.items():
        if not NAME.fullmatch(name) or not isinstance(spec, dict):
            raise ContractError("Invalid fact dependency name or definition")
        if not {"path", "type"} <= set(spec) or set(spec) - {"path", "type", "entity", "equals", "min", "max"}:
            raise ContractError("Unknown or missing fact check fields")
        if spec["type"] not in TYPES or not isinstance(spec["path"], str) or not spec["path"].startswith("/"):
            raise ContractError("Fact check needs a JSON pointer and a supported scalar type")
        if re.search(r"~(?![01])", spec["path"]):
            raise ContractError("Invalid JSON pointer escape")
        if not ENTITY.fullmatch(spec.get("entity", value["entity"])):
            raise ContractError("Fact check names an invalid entry key")
        for bound in ("min", "max"):
            if bound in spec and (spec["type"] not in {"integer", "number"} or type(spec[bound]) not in {int, float}
                                  or not math.isfinite(spec[bound])):
                raise ContractError("Numeric bounds require finite numbers")
        if "min" in spec and "max" in spec and spec["min"] > spec["max"]:
            raise ContractError("Fact bounds are reversed")
        if "equals" in spec and not scalar_type(spec["equals"], spec["type"]):
            raise ContractError("Equality check differs from its declared scalar type")
    if not isinstance(value["text"], list) or not 1 <= len(value["text"]) <= 128:
        raise ContractError("Explanation needs 1 to 128 literal or fact segments")
    for part in value["text"]:
        if isinstance(part, str):
            if len(part) > 8192:
                raise ContractError("Explanation text segment exceeds 8192 characters")
        elif not isinstance(part, dict) or set(part) != {"fact"} or part["fact"] not in facts:
            raise ContractError("Text may insert only a declared fact dependency")
    if not isinstance(value["code"], list) or len(value["code"]) > 32:
        raise ContractError("Code dependencies must be a bounded list")
    if value["scope"] == "code-backed" and not value["code"]:
        raise ContractError("Code-backed explanations require code dependencies")
    if value["scope"] == "selected-data" and value["code"]:
        raise ContractError("Code dependencies require code-backed scope")
    seen = set()
    for dependency in value["code"]:
        if not isinstance(dependency, dict) or set(dependency) not in ({"path", "sha256"}, {"path", "sha256", "symbol"}):
            raise ContractError("Invalid code dependency fields")
        path = dependency["path"]
        if not isinstance(path, str) or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts or "\\" in path or ":" in path or not path.endswith(".cs"):
            raise ContractError("Code dependencies must name unique captured C# files")
        if not isinstance(dependency["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", dependency["sha256"]):
            raise ContractError("Code dependency needs its SHA-256")
        if "symbol" in dependency:
            code_dependencies.validate(dependency["symbol"])
        key = code_dependencies.key(dependency)
        if key in seen:
            raise ContractError("Code dependencies must name unique captured C# files or symbols")
        seen.add(key)
    return value


def scalar_type(value, kind):
    return type(value) in ((int, float) if kind == "number" else (TYPES[kind],)) and (
        not isinstance(value, float) or math.isfinite(value))


def pointer(facts, path):
    value = facts
    for part in path[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            value = value[part]
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", part):
            value = value[int(part)]
        else:
            raise KeyError(path)
    return value


def check(value, spec):
    if not scalar_type(value, spec["type"]):
        return "type-changed"
    if "equals" in spec and (type(value) != type(spec["equals"]) or value != spec["equals"]):
        return "value-changed"
    if "min" in spec and value < spec["min"]:
        return "below-minimum"
    if "max" in spec and value > spec["max"]:
        return "above-maximum"
    return None


def render(definition, facts):
    parts, size = [], 0
    for part in definition["text"]:
        value = part if isinstance(part, str) else facts[part["fact"]]
        value = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, allow_nan=False)
        # Check before joining: repeated insertions must not amplify a small definition.
        if len(value) > MAX_TEXT_BYTES:
            raise ContractError("rendered-text-exceeds-16-KiB")
        size += len(value.encode("utf-8"))
        if size > MAX_TEXT_BYTES:
            raise ContractError("rendered-text-exceeds-16-KiB")
        parts.append(value)
    return "".join(parts)


def value_hash(value):
    return digest(json_bytes(value))
