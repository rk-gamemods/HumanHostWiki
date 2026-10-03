"""Versioned availability evidence, separate from captures and gameplay checks."""

from datetime import datetime, timezone
import json
from pathlib import Path
import re

from . import steam_build
from .storage import ContractError, digest, json_bytes, within, write_changed


def contract():
    return {name: digest((Path(__file__).parent / name).read_bytes().replace(b"\r\n", b"\n"))
            for name in ("availability.py", "steam_build.py")}


def read(root, identity):
    if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{64}", identity):
        raise ContractError("Invalid availability observation ID")
    value = json.loads(within(root, f"availability/{identity}.json").read_bytes())
    if digest(json_bytes(value)) != identity or value.get("schema_version") != 1:
        raise ContractError("Availability observation was modified")
    return value


def latest(root, project):
    if not project.get("availability", {}).get("enabled", False):
        return None
    path = within(root, "availability/latest.json")
    return read(root, json.loads(path.read_bytes())["observation_id"]) if path.exists() else None


def refresh(root, project, steam, progress=None, *, now=None, fetch=None):
    """Caller holds writer_lock; unavailable remote evidence never blocks facts."""
    options = project.get("availability", {})
    if not options.get("enabled", False):
        return None, {"reused": True, "status": "not-configured"}
    now = datetime.now(timezone.utc) if now is None else now
    app_id, branch = steam["app_id"], steam.get("branch", "public")
    current = latest(root, project)
    rules = contract()
    if current and current["app_id"] == app_id and current["branch"] == branch and current["contract"] == rules:
        age = (now - datetime.fromisoformat(current["checked_at"])).total_seconds()
        lifetime = options.get("cache_seconds", 3600) if current["status"] == "observed" else options.get("retry_seconds", 60)
        if 0 <= age < lifetime:
            return current, {"reused": True, "status": current["status"]}
    result = {"schema_version": 1, "app_id": app_id, "branch": branch,
              "checked_at": now.isoformat(timespec="seconds"), "contract": rules}
    settings = within(root, ".local/steamcmd.json")
    try:
        executable = json.loads(settings.read_bytes())["executable"]
        observed = (fetch or steam_build.fetch)(executable, app_id, branch, progress)
        if observed["app_id"] != app_id or observed["branch"] != branch:
            raise ContractError("Availability provider returned another application or branch")
        result.update(status="observed", observation=observed)
    except (OSError, UnicodeError, ValueError, KeyError, ContractError) as exc:
        # Public output omits local paths and raw process output. Detailed local
        # errors remain in ignored operator state, separate from content issues.
        result.update(status="unavailable", reason="steam-metadata-unavailable")
        write_changed(within(root, ".local/availability-error.json"), json_bytes({
            "checked_at": result["checked_at"], "error": str(exc)}))
        if progress:
            progress("Steam availability check failed; supported wiki work continues")
    if contract() != rules:
        raise ContractError("Availability rules changed during observation")
    identity = digest(json_bytes(result))
    path = within(root, f"availability/{identity}.json")
    if path.exists() and path.read_bytes() != json_bytes(result):
        raise ContractError("Availability observation collision")
    write_changed(path, json_bytes(result))
    read(root, identity)
    write_changed(within(root, "availability/latest.json"), json_bytes({"observation_id": identity}))
    return result, {"reused": False, "status": result["status"]}


def describe(value, steam):
    if not value or value["status"] != "observed":
        return "Latest available build unknown; Steam metadata check unavailable."
    observed = value["observation"]
    same = steam.get("branch", "public") == observed["branch"] and steam["build_id"] == observed["build_id"]
    state = "Captured build matches" if same else "Captured build differs; awaiting matching local capture"
    return (f"Latest observed Steam {observed['branch']} build: {observed['build_id']} "
            f"at {value['checked_at']}. {state}. Gameplay verification is separate.")
