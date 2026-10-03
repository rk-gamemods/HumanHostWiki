"""Rehearse an explicit local release against the live repositories' real state.

Every GitHub read is real: repository identities, branch tips and Pages configuration.
Nothing is written to GitHub: pushes, Pages builds and public hash checks are simulated
against local Git objects. Local publication records are snapshotted and restored, so the
workspace retains only a successful rehearsal receipt. A pass means publish would take the same
steps from the same starting state; it does not prove GitHub Pages will build.

    py -3 tools/rehearse_publication.py --release <id>
"""

import argparse
import hashlib
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wikibuild import bounded, github_pages, manifest as manifests, physical, publication, publish_gate, release  # noqa: E402
from wikibuild.storage import ContractError, writer_lock  # noqa: E402

PROTECTED = ("publications", ".local/publication")


class RehearsalHost(github_pages.GitHubPages):
    def __init__(self, owner, paths, progress):
        super().__init__(owner, progress)
        self.paths, self.simulated, self.events = paths, {}, []
        self.observed = {}

    def ref(self, name, branch):
        if (name, branch) in self.simulated:
            return self.simulated[(name, branch)]
        current = super().ref(name, branch)
        key = (name, branch)
        if key in self.observed and self.observed[key] != current:
            raise ContractError(f"Remote branch changed during rehearsal: {name}/{branch}")
        self.observed[key] = current
        return current

    def create(self, name, description):
        raise ContractError(f"Rehearsal would create repository {name}")

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

    def configure(self, name):
        value = self.api("GET", f"repos/{self.owner}/{name}/pages", missing=True)
        if value is None:
            raise ContractError(f"Rehearsal would enable Pages for {name}")
        if value.get("source") != {"branch": "gh-pages", "path": "/"} or value.get("build_type", "legacy") != "legacy":
            raise ContractError(f"Unexpected Pages configuration: {name}")

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
        publication.refuse_pending(root)
        target = manifest["release_id"]
        paths = {repo["github_name"]: root / manifest["repositories"][repo["id"]]["path"]
                 for repo in physical.repositories(project, manifest.get("physical"))}
        before = ""
        commit = publish_gate.git(root, "rev-parse", "HEAD")
        contract = publication.contract()
        # Snapshot every destination of the fresh publication.
        destinations = publish_gate.destinations(root, project, manifest)
        backup = root / ".local/rehearsal-backups"
        backup.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=backup) as saved:
            for relative in PROTECTED:
                if (root / relative).exists():
                    shutil.copytree(root / relative, Path(saved) / relative)
            host = RehearsalHost(project["github_owner"], paths, progress)
            try:
                for name, branch in sorted(destinations):
                    host.ref(name, branch)
                # Only this read-only simulator uses the engine without the production gate.
                timing = {"repositories": {}, "rollback": {}, "phases": {}, "prepare": 0.0, "resume": 0.0}
                refs = [{"repository": name, "branch": branch, "commit": sha}
                        for (name, branch), sha in sorted(host.observed.items())]
                result, _ = publication._run(root, project, manifest, host, progress, timing,
                                            {"rehearsal": {"remote_refs": refs}})
            finally:
                for relative in PROTECTED:
                    if (root / relative).exists():
                        shutil.rmtree(root / relative)
                    if (Path(saved) / relative).exists():
                        shutil.copytree(Path(saved) / relative, root / relative)
        if (publish_gate.git(root, "status", "--porcelain=v1", "--untracked-files=all") != before
                or publish_gate.git(root, "rev-parse", "HEAD") != commit):
            raise ContractError("Rehearsal changed workspace files or commit")
        if publication.contract() != contract:
            raise ContractError("Publication contract changed during rehearsal")
        if result["status"] != "published":
            raise ContractError("Rehearsal did not complete publication")
        refs = [{"repository": name, "branch": branch, "commit": sha}
                for (name, branch), sha in sorted(host.observed.items())]
        publish_gate.write_receipt(root, target, commit, refs)
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
