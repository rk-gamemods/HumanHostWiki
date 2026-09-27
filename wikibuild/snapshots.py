"""Register a small receipt for an existing clean local catalog, read in place."""

import json
import re
from pathlib import Path

from .storage import ContractError, digest, git, json_bytes, within, write_changed

RECEIPT_ID = re.compile(r"^build-[0-9]+-[0-9a-f]{12}$")


def register(root, manifest, source):
    source = Path(source).resolve()
    if not (source / ".git").is_dir():
        raise ContractError("Source must be the independent local codebase repository")
    if source.is_relative_to(root.resolve()):
        raise ContractError("Raw codebase must remain outside the wiki umbrella")
    if git(source, "remote"):
        raise ContractError("Local codebase input must not have a remote")
    if git(source, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ContractError("Source snapshot is dirty; register a committed, clean snapshot")
    revision = git(source, "rev-parse", "HEAD")
    paths = ["Catalog/steam-build.json", "Catalog/generator.json", "Catalog/coverage.json"]
    blobs = {path: git(source, "show", f"{revision}:{path}") for path in paths}
    steam, generator, coverage = [json.loads(blobs[path]) for path in paths]
    if steam.get("app_id") != manifest["source"]["steam_app_id"]:
        raise ContractError("Snapshot belongs to a different Steam application")
    if generator.get("schema") != manifest["source"]["catalog_schema"]:
        raise ContractError("Unsupported catalog schema; adapt and test before refresh")
    if coverage.get("decode_failures"):
        raise ContractError("Catalog has decode failures; receipt not registered")
    if not re.fullmatch(r"[0-9]+", steam.get("build_id", "")):
        raise ContractError("Missing numeric Steam build identity")
    identity = f"build-{steam['build_id']}-{revision[:12]}"
    # File identities are Git blobs in the pinned commit; no large file is copied or read.
    input_blob = git(source, "rev-parse", f"{revision}:Catalog/inputs.jsonl")
    receipt = {"schema_version": 1, "snapshot_id": identity, "source_commit": revision,
               "steam": steam, "game_version": None,
               "game_version_status": "not-recorded-by-source-generator",
               "catalog_generator": generator,
               "input_inventory_git_blob": input_blob,
               "catalog_metadata_sha256": {path: digest(json_bytes(json.loads(data))) for path, data in blobs.items()},
               "metadata_hash_normalization": "canonical sorted UTF-8 JSON with LF",
               "coverage": {"objects": coverage.get("objects"), "decode_gaps": coverage.get("decode_gaps", [])},
               "status": "input-registered", "wiki_verification": "not-performed",
               "latest_available_game_build": None}
    if revision != git(source, "rev-parse", "HEAD") or git(source, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ContractError("Source changed during registration; retry with stable inputs")
    output = within(root, f"snapshots/{identity}.json")
    data = json_bytes(receipt)
    if output.exists() and output.read_bytes() != data:
        raise ContractError("Snapshot receipt collision; do not overwrite prior provenance")
    write_changed(output, data)
    return receipt


def read(root, identity):
    if not RECEIPT_ID.fullmatch(identity):
        raise ContractError("Invalid snapshot identifier")
    receipt = json.loads(within(root, f"snapshots/{identity}.json").read_text())
    if receipt.get("snapshot_id") != identity or receipt.get("schema_version") != 1:
        raise ContractError("Snapshot receipt identity or schema mismatch")
    if receipt.get("status") != "input-registered" or receipt.get("wiki_verification") != "not-performed":
        raise ContractError("Input registration must not claim wiki verification")
    return receipt
