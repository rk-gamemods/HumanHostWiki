"""Verify indexed JSON records while decoding only requested component fields.

The producer records canonical member names and encoded value sizes for large
records. Every byte is hashed, and member boundaries/names are checked against
the original stream. Skipped values remain local; their names survive as null
placeholders so normal selection still reports new fields. Old indexes retain
full JSON decoding. This module owns no gameplay selection policy.
"""

import hashlib
import json

from .storage import ContractError


def read_record(read, location, selected_fields=None):
    remaining = location["bytes"]
    sha = hashlib.sha256()

    def take(size):
        nonlocal remaining
        if type(size) is not int or not 0 <= size <= remaining:
            raise ContractError("Invalid indexed member size")
        data = read(size)
        remaining -= len(data)
        sha.update(data)
        if len(data) != size:
            raise ContractError("Truncated source record")
        return data

    def expect(expected):
        if take(len(expected)) != expected:
            raise ContractError("Indexed member name or boundary differs from source")

    def skip(size):
        if type(size) is not int or not 1 <= size <= remaining:
            raise ContractError("Invalid indexed member size")
        while size:
            block = min(size, 64 * 1024)
            take(block)
            size -= block

    def members(plan, fields=False):
        if not isinstance(plan, dict) or any(not isinstance(key, str) for key in plan):
            raise ContractError("Invalid source member index")
        result = {}
        expect(b"{")
        for index, key in enumerate(sorted(plan)):
            if index:
                expect(b", ")
            expect(json.dumps(key, ensure_ascii=False).encode("utf-8", errors="backslashreplace") + b": ")
            size = plan[key]
            if not fields and key == "fields" and isinstance(size, dict):
                result[key] = members(size, fields=True)
            elif type(size) is not int or size < 1:
                raise ContractError("Invalid indexed member size")
            elif fields and selected_fields is not None and key not in selected_fields:
                skip(size)
                result[key] = None
            else:
                result[key] = json.loads(take(size))
        expect(b"}")
        return result

    error, row = None, None
    try:
        if selected_fields is not None and "members" in location:
            row = members(location["members"])
            expect(b"\n")
            if remaining:
                raise ContractError("Indexed members do not cover the source record")
        else:
            row = json.loads(take(remaining))
    except (ContractError, ValueError, UnicodeError) as exc:
        error = exc
    # Verify stale local data before interpreting parsing errors. A mismatched
    # hash requests immutable Git fallback; a matching hash with bad structure
    # is a broken index and must fail, never silently change the selection.
    while remaining:
        block = read(min(remaining, 64 * 1024))
        if not block:
            return None
        remaining -= len(block)
        sha.update(block)
    if sha.hexdigest() != location.get("sha256"):
        return None
    if error is not None:
        raise ContractError(f"Malformed source record location: {error}") from error
    if not isinstance(row, dict):
        raise ContractError("Expected source object record")
    return row
