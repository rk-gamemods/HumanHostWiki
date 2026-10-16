"""Read reviewed topic confirmations without treating failed journals as receipts."""

import json
import re

from . import bounded, physical
from .storage import digest, json_bytes, within


def committed_bytes(root, path):
    data = path.read_bytes()
    result = bounded.run(["git", "-C", str(root), "cat-file", "blob",
                          "HEAD:" + path.relative_to(root).as_posix()], timeout=120)
    return data if result.returncode == 0 and result.stdout == data else None


def confirmations(root):
    """Only exact HEAD blobs, bound to a committed release and destination, qualify."""
    commits, errors = {}, []
    for path in sorted((root / "topic-confirmations").glob("*.json")):
        try:
            data = committed_bytes(root, within(root, path.relative_to(root)))
            if data is None:
                continue
            envelope = json.loads(data)
            value = envelope["payload"]
            identity = digest(json_bytes(value))
            if envelope["sha256"] != identity or path.stem != identity:
                raise ValueError("confirmation content hash differs")
            if (value["schema_version"] != 1 or value["kind"] != "topic-publication-confirmation"
                    or value["status"] != "verified"
                    or not re.fullmatch(r"[0-9a-f]{64}", value["release_id"])):
                raise ValueError("invalid topic confirmation")
            release_path = within(root, f"releases/{value['release_id']}.json")
            release_data = committed_bytes(root, release_path)
            project_data = committed_bytes(root, root / "project.json")
            if release_data is None or project_data is None:
                continue
            selected, project = json.loads(release_data), json.loads(project_data)
            if digest(release_data) != value["release_file_sha256"] or project["github_owner"] != value["owner"]:
                raise ValueError("confirmation release or owner differs")
            if (not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value["workspace_commit"])
                    or bounded.run(["git", "-C", str(root), "merge-base", "--is-ancestor",
                                    value["workspace_commit"], "HEAD"], timeout=120).returncode):
                raise ValueError("confirmation workspace is not reviewed history")
            destinations = {repo["id"]: repo for repo in physical.repositories(project, selected.get("physical"))}
            qualified = {}
            for key, row in value["repositories"].items():
                repo, record = destinations[key], selected["repositories"][key]
                if (repo.get("logical_topic", key) == "hub" or repo["role"] == "hub"
                        or row["role"] != repo["role"] or row["path"] != repo["path"]
                        or row["path"] != record["path"] or row["name"] != repo["github_name"]
                        or row["name"] != record["github_name"] or row["main"] != record["commit"]
                        or type(row["repository_id"]) is not int or row["repository_id"] <= 0
                        or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", row["pages"])
                        or row["build_commit"] != row["pages"] or row["build_status"] != "built"
                        or not row["build_url"].startswith(f"https://api.github.com/repos/{value['owner']}/{row['name']}/pages/builds/")
                        or type(row["checked_files"]) is not int or row["checked_files"] <= 0
                        or any(not re.fullmatch(r"[0-9a-f]{64}", row[field])
                               for field in ("files_sha256", "checks_sha256"))):
                    raise ValueError("confirmation destination or verification differs")
                qualified[(key, row["path"], row["name"])] = {row["pages"]}
            for key, revisions in qualified.items():
                commits.setdefault(key, set()).update(revisions)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            errors.append({"path": path.relative_to(root).as_posix(), "error": str(exc)})
    return commits, errors
