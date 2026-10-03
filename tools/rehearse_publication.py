"""Rehearse an explicit local release against the live repositories' real state.

Every GitHub read is real: repository identities, branch tips and Pages configuration.
Nothing is written to GitHub: pushes, Pages builds and public hash checks are simulated
against disposable Git clones. Local publication records are copied into isolation, so the
workspace retains only a successful rehearsal receipt. A pass means publish would take the same
steps from the same starting state; it does not prove GitHub Pages will build.

    py -3 tools/rehearse_publication.py --release <id>
"""

import argparse
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wikibuild import bounded, github_pages, manifest as manifests, physical, publication, publication_git, publish_gate, release  # noqa: E402
from wikibuild.storage import ContractError, within, writer_lock  # noqa: E402

PROTECTED = ("publications", ".local/publication")
TEMP_RECORD = ".local/publication/rehearsal-temp.json"
TEMP_MARKER = ".hhwiki-rehearsal.json"


def clear_temp_record(root, record):
    within(root, TEMP_RECORD).unlink(missing_ok=True)
    for relative in record["created_dirs"]:
        directory = within(root, relative)
        if directory.exists() and not any(directory.iterdir()):
            directory.rmdir()


def recover_abandoned(root, progress):
    pointer = within(root, TEMP_RECORD)
    if not pointer.exists():
        return
    record = publication.load(pointer)
    temporary = Path(record["path"])
    if (not temporary.is_absolute() or temporary.resolve() != temporary
            or temporary.parent != Path(tempfile.gettempdir()).resolve()
            or not re.fullmatch(r"hhwiki-rehearsal-[0-9a-f]{32}", temporary.name)
            or record.get("workspace") != str(root.resolve())
            or record.get("created_dirs") not in ([], [".local/publication"], [".local/publication", ".local"])):
        raise ContractError(f"Refusing unowned rehearsal temp path: {temporary}")
    if record.get("recovery_required"):
        raise ContractError(f"Rehearsal recovery requires the retained backup at {temporary}")
    if temporary.exists():
        marker = temporary / TEMP_MARKER
        # Before the marker is installed, a crash can leave an empty root or
        # just write_changed's partial marker file. After marker-last cleanup,
        # the only possible unmarked remainder is an empty root.
        incomplete_marker = (not marker.exists() and not marker.is_symlink()
                             and all(file.is_file() and not file.is_symlink()
                                     and re.fullmatch(re.escape(TEMP_MARKER) + r"\.[0-9a-f]{32}\.tmp", file.name)
                                     for file in temporary.iterdir()))
        if (not incomplete_marker and (marker.is_symlink() or not marker.is_file()
                or publication.load(marker) != {"workspace": record["workspace"], "nonce": record["nonce"]})):
            raise ContractError(f"Refusing rehearsal temp cleanup without its ownership marker: {temporary}")
        progress(f"Removing abandoned rehearsal temp root: {temporary}")
        publication_git.remove_disposable(temporary, marker=TEMP_MARKER)
    clear_temp_record(root, record)


@contextmanager
def isolated_git_environment():
    saved = {key: value for key, value in os.environ.items() if key.upper().startswith("GIT_")}
    for key in saved:
        del os.environ[key]
    environment = publication_git.disposable_environment()
    configured = {key: value for key, value in environment.items() if key.startswith("GIT_")}
    os.environ.update(configured)
    try:
        yield
    finally:
        for key in configured:
            os.environ.pop(key, None)
        os.environ.update(saved)


def state_snapshot(root):
    rows = {}
    for relative in PROTECTED:
        path = within(root, relative)
        rows[relative] = None if not path.exists() else {
            file.relative_to(path).as_posix(): file.read_bytes() if file.is_file() else None
            for file in sorted(path.rglob("*"))}
    return rows


def restore_state(root, backup, before, quarantine):
    """Defensive recovery only. Keep backup and displaced files until verified."""
    try:
        for relative in PROTECTED:
            target = within(root, relative)
            if target.exists():
                displaced = within(quarantine, relative)
                displaced.parent.mkdir(parents=True, exist_ok=True)
                target.rename(displaced)
            saved = within(backup, relative)
            if saved.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(saved, target)
        if state_snapshot(root) != before:
            raise ContractError("Restored publication state differs from its backup")
    except (OSError, ContractError) as exc:
        raise ContractError(f"Rehearsal restore failed; durable backup retained at {backup}: {exc}") from exc


@contextmanager
def isolated_workspace(root, manifest, progress=print):
    # Ordinary temp directories also work on hosts with restrictive mkdtemp ACLs.
    recover_abandoned(root, progress)
    temporary = Path(tempfile.gettempdir()).resolve() / ("hhwiki-rehearsal-" + uuid4().hex)
    owner_record = {"path": str(temporary), "workspace": str(root.resolve()), "nonce": uuid4().hex,
                    "created_dirs": [relative for relative in (".local/publication", ".local")
                                     if not within(root, relative).exists()]}
    engine, backup = temporary / "workspace", temporary / "backup"
    repositories = {}
    keep = False
    ready = False
    try:
        # Persist intent before creating anything the next invocation must own.
        publication.save(within(root, TEMP_RECORD), owner_record)
        temporary.mkdir()
        publication.save(temporary / TEMP_MARKER, {"workspace": owner_record["workspace"], "nonce": owner_record["nonce"]})
        progress(f"Rehearsal temp root: {temporary}")
        engine.mkdir()
        before = state_snapshot(root)
        repositories = {within(root, record["path"]): publication_git.storage_snapshot(within(root, record["path"]))
                        for record in manifest["repositories"].values()}
        for relative in PROTECTED:
            source = within(root, relative)
            if source.exists():
                shutil.copytree(source, within(backup, relative))
                shutil.copytree(within(backup, relative), within(engine, relative))
        if state_snapshot(backup) != before:
            raise ContractError("Rehearsal backup differs from workspace state")
        ready = True
        for record in manifest["repositories"].values():
            publication_git.disposable_clone(within(root, record["path"]), within(engine, record["path"]), record["commit"])
        yield engine
    finally:
        restored = False
        try:
            if ready and state_snapshot(root) != before:
                restore_state(root, backup, before, temporary / "displaced")
                restored = True
            for path, saved in repositories.items():
                if publication_git.storage_snapshot(path) != saved:
                    raise ContractError(f"Rehearsal changed real repository refs, pins or objects: {path}; evidence retained at {temporary}")
        except BaseException:
            keep = True
            publication.save(within(root, TEMP_RECORD), {**owner_record, "recovery_required": True})
            raise
        finally:
            if not keep:
                if within(root, TEMP_RECORD).exists():
                    recover_abandoned(root, lambda message: None)
                elif not temporary.exists():
                    clear_temp_record(root, owner_record)
        if restored:
            raise ContractError("Rehearsal changed original publication state; restored from backup")


class RehearsalHost(github_pages.GitHubPages):
    def __init__(self, owner, paths, progress):
        super().__init__(owner, progress)
        self.paths, self.simulated, self.events = paths, {}, []
        self.observed = {}
        self.created, self.destination_observations = {}, {}
        self.pages_enabled = {}

    def api(self, method, *args, **kwargs):
        if method != "GET":
            raise ContractError(f"Rehearsal forbids GitHub writes: {method}")
        if args and args[0].endswith("/pages"):
            name = args[0].split("/")[2]
            if name in self.pages_enabled:
                return self.pages_enabled[name]
            if name in self.created:
                return None
        return super().api(method, *args, **kwargs)

    def repository(self, name):
        return self.created[name] if name in self.created else super().repository(name)

    def ref(self, name, branch):
        if (name, branch) in self.simulated:
            return self.simulated[(name, branch)]
        current = (None if self.destination_observations.get(name, {}).get("observed") == "absent"
                   else super().ref(name, branch))
        key = (name, branch)
        if key in self.observed and self.observed[key] != current:
            raise ContractError(f"Remote branch changed during rehearsal: {name}/{branch}")
        self.observed[key] = current
        return current

    def create(self, name, description):
        if self.destination_observations.get(name, {}).get("observed") != "absent":
            raise ContractError(f"Rehearsal cannot provision an unobserved destination: {name}")
        value = {"id": int(hashlib.sha256(name.encode()).hexdigest()[:12], 16),
                 "full_name": f"{self.owner}/{name}", "description": description,
                 "private": False, "archived": False, "fork": False, "permissions": {"admin": True}}
        self.created[name] = value
        self.events.append(("create", name))
        return value

    def push(self, path, name, commit, branch, expected):
        current = self.ref(name, branch)
        if current != expected:
            raise ContractError(f"Remote branch changed: {name}/{branch}")
        if current == commit:
            return
        if current:
            if bounded.run(["git", "-C", str(path), "cat-file", "-e", current + "^{commit}"], timeout=publish_gate.GIT_TIMEOUT).returncode:
                self.fetch(path, name, branch)
            if bounded.run(["git", "-C", str(path), "merge-base", "--is-ancestor", current, commit], timeout=publish_gate.GIT_TIMEOUT).returncode:
                raise ContractError(f"Non-fast-forward push: {name}/{branch}")
        self.simulated[(name, branch)] = commit
        self.events.append(("push", name, branch, commit))
        self.progress(f"[rehearsal] would push {name}/{branch} {current and current[:7]} -> {commit[:7]}")

    def configure(self, name, *, defer=False):
        observation = github_pages.observe_configuration(self, self.owner, name)
        if observation["observed"] == "pages-disabled":
            def enable():
                value = {"source": {"branch": "gh-pages", "path": "/"}, "build_type": "legacy",
                         "cname": None, "html_url": f"https://{self.owner}.github.io/{name}/"}
                self.pages_enabled[name] = value
                self.events.append(("enable-pages", name))
                return value
            return enable if defer else enable()
        return self.api("GET", f"repos/{self.owner}/{name}/pages")

    def wait(self, name, commit):
        if self.ref(name, "gh-pages") != commit:
            raise ContractError(f"Rehearsal Pages build would serve the wrong commit: {name}")

    def verify(self, base, files, **kwargs):
        name = base.rstrip("/").rsplit("/", 1)[1]
        path, commit = self.paths[name], self.ref(name, "gh-pages")
        for name_in_tree, expected in files.items():
            result = bounded.run(["git", "-C", str(path), "cat-file", "blob", f"{commit}:{name_in_tree}"], timeout=publish_gate.GIT_TIMEOUT)
            if result.returncode:
                raise ContractError(f"Rehearsal Git object is missing: {name}/{name_in_tree}")
            data = result.stdout
            if len(data) != expected["bytes"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
                raise ContractError(f"Rehearsal bytes differ: {name}/{name_in_tree}")
        self.events.append(("verified", name, len(files)))
        return {"bytes": 0}


def rehearse(root, project, manifest, progress=print):
    publish_gate.ensure_clean(root)
    with writer_lock(root):
        publish_gate.ensure_clean(root)
        recover_abandoned(root, progress)
        publication.refuse_pending(root)
        target = manifest["release_id"]
        before = ""
        commit = publish_gate.git(root, "rev-parse", "HEAD")
        contract = publication.contract()
        # Snapshot every destination of the fresh publication.
        destinations = publish_gate.destinations(root, project, manifest)
        release.verify(root, manifest)
        with isolated_workspace(root, manifest, progress) as engine, isolated_git_environment():
            paths = {repo["github_name"]: within(engine, manifest["repositories"][repo["id"]]["path"])
                     for repo in physical.repositories(project, manifest.get("physical"))}
            host = RehearsalHost(project["github_owner"], paths, progress)
            for name in sorted({name for name, branch in destinations}):
                host.destination_observations[name] = github_pages.observe_configuration(host, host.owner, name)
            for name, branch in sorted(destinations):
                host.ref(name, branch)
            # Only this read-only simulator uses the engine without the production gate.
            timing = publication.new_timing()
            refs = [{"repository": name, "branch": branch, "commit": sha}
                    for (name, branch), sha in sorted(host.observed.items())]
            observations = list(host.destination_observations.values())
            result, _ = publication._run(engine, project, manifest, host, progress, timing,
                                        {"rehearsal": {"remote_refs": refs, "destination_observations": observations}})
        if (publish_gate.git(root, "status", "--porcelain=v1", "--untracked-files=all") != before
                or publish_gate.git(root, "rev-parse", "HEAD") != commit):
            raise ContractError("Rehearsal changed workspace files or commit")
        if publication.contract() != contract:
            raise ContractError("Publication contract changed during rehearsal")
        if result["status"] != "published":
            raise ContractError("Rehearsal did not complete publication")
        refs = [{"repository": name, "branch": branch, "commit": sha}
                for (name, branch), sha in sorted(host.observed.items())]
        publish_gate.write_receipt(root, target, commit, refs, observations)
    pushes = [event for event in host.events if event[0] == "push"]
    progress(f"REHEARSAL PASSED for release {target}: status {result['status']}, "
          f"{len(pushes)} simulated pushes, {sum(e[2] for e in host.events if e[0] == 'verified')} file checks; "
          "hub promoted last. GitHub unchanged; rehearsal receipt saved.")
    return publish_gate.receipt_path(root, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True)
    args = parser.parse_args()
    rehearse(ROOT, manifests.load(ROOT), release.read(ROOT, args.release),
             lambda message: print(message, flush=True))


if __name__ == "__main__":
    main()
