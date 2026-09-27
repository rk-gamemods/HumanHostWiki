"""Read public branch metadata through a configured anonymous SteamCMD client."""

import json
import hashlib
import os
import re
import subprocess
from pathlib import Path

from .storage import ContractError, digest

MAX_OUTPUT = 1024 * 1024
TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[{}]')


def parse(text, app_id, branch):
    matches = list(re.finditer(r'(?m)^"' + re.escape(app_id) + r'"\s*\{', text))
    if len(matches) != 1:
        raise ContractError("SteamCMD did not return the requested application")

    def tokenize():
        position = matches[0].start()
        while position < len(text):
            if text[position].isspace():
                position += 1
                continue
            token = TOKEN.match(text, position)
            if not token:
                raise ContractError("Invalid Steam app metadata token")
            position = token.end()
            yield token.group()

    tokens = tokenize()

    def value(token, depth=0):
        if depth > 32:
            raise ContractError("Steam app metadata nesting exceeds the limit")
        if token != "{":
            if not token.startswith('"'):
                raise ContractError("Invalid Steam app metadata value")
            return json.loads(token)
        result = {}
        for key in tokens:
            if key == "}":
                return result
            key = value(key, depth + 1)
            if not isinstance(key, str) or key in result:
                raise ContractError("Duplicate or invalid Steam app metadata key")
            result[key] = value(next(tokens), depth + 1)
        raise ContractError("Incomplete Steam app metadata")

    try:
        if value(next(tokens)) != app_id:
            raise ContractError("Steam app identity differs")
        app = value(next(tokens))
        depots = app["depots"]
        selected = depots["branches"][branch]
        build = selected["buildid"]
        updated = selected["timeupdated"]
        if not re.fullmatch(r"[1-9][0-9]*", build) or not re.fullmatch(r"[0-9]+", updated):
            raise ContractError("Invalid Steam branch build or timestamp")
        manifests = {}
        for key, depot in depots.items():
            if key.isdecimal() and isinstance(depot, dict):
                item = depot.get("manifests", {}).get(branch)
                if item:
                    identity = item["gid"]
                    if not re.fullmatch(r"[1-9][0-9]*", identity):
                        raise ContractError("Invalid Steam depot manifest")
                    manifests[key] = identity
        return {"app_id": app_id, "branch": branch, "build_id": build,
                "branch_updated_at_unix": int(updated), "depot_manifests": manifests}
    except (KeyError, TypeError, StopIteration, ValueError) as exc:
        raise ContractError("Steam did not return valid public branch metadata") from exc


def fetch(executable, app_id, branch, progress=None):
    """No login credentials or game downloads. Caller owns retry/caching policy."""
    if not re.fullmatch(r"[1-9][0-9]*", app_id):
        raise ContractError("Invalid Steam app ID")
    executable = Path(executable).resolve(strict=True)
    if progress:
        progress("Querying Steam public branch metadata")
    # Preserve SteamCMD's network retry policy and bounded diagnostic progress.
    # Limit bytes while reading, before an unexpected response can consume RAM.
    output = bytearray()
    with subprocess.Popen([str(executable), "+login", "anonymous", "+app_info_update", "1",
                           "+app_info_print", app_id, "+quit"], cwd=executable.parent,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0) as process:
        try:
            while line := process.stdout.readline(MAX_OUTPUT - len(output) + 1):
                output.extend(line)
                if len(output) > MAX_OUTPUT:
                    raise ContractError("SteamCMD metadata response exceeds the limit")
                if progress and line.startswith((b"[", b"Connecting anonymously", b"Waiting for", b"Loading Steam API")):
                    progress(line.decode("utf-8", errors="replace").strip()[:240])
            status = process.wait()
        except BaseException:
            process.kill()
            raise
    if status:
        raise ContractError(f"SteamCMD metadata request exited with status {status}")
    text = output.decode("utf-8", errors="strict")
    if "Connecting anonymously to Steam Public...OK" not in text:
        raise ContractError("SteamCMD did not confirm a connected anonymous session")
    with executable.open("rb") as stream:
        client_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    return {**parse(text, app_id, branch), "source": "steamcmd-app-info",
            "source_url": "https://partner.steamgames.com/doc/sdk/api/debugging#console_commands",
            "response_sha256": digest(output), "client_sha256": client_hash}
