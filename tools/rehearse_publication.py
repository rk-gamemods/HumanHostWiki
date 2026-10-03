"""Rehearse publishing the latest local release against the live repositories' real state.

Every GitHub read is real: repository identities, branch tips and Pages configuration.
Nothing is written to GitHub: pushes, Pages builds and public hash checks are simulated
against local Git objects. Local publication records are snapshotted and restored, so the
workspace ends exactly as it started. A pass means the real publish would take the same
steps from the same starting state; it does not prove GitHub Pages will build.

    py -3 tools/rehearse_publication.py
"""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wikibuild import github_pages, manifest as manifests, physical, publication, release  # noqa: E402
from wikibuild.storage import ContractError, git, writer_lock  # noqa: E402

PROTECTED = ("publications", ".local/publication")


class RehearsalHost(github_pages.GitHubPages):
    def __init__(self, owner, paths, progress):
        super().__init__(owner, progress)
        self.paths, self.simulated, self.events = paths, {}, []

    def ref(self, name, branch):
        if (name, branch) in self.simulated:
            return self.simulated[(name, branch)]
        return super().ref(name, branch)

    def create(self, name, description):
        raise ContractError(f"Rehearsal would create repository {name}")

    def push(self, path, name, commit, branch, expected):
        current = self.ref(name, branch)
        if current == commit:
            return
        if current != expected:
            raise ContractError(f"Remote branch changed: {name}/{branch}")
        if current:
            if subprocess.run(["git", "-C", str(path), "cat-file", "-e", current + "^{commit}"], capture_output=True).returncode:
                self.fetch(path, name, branch)
            if subprocess.run(["git", "-C", str(path), "merge-base", "--is-ancestor", current, commit], capture_output=True).returncode:
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
            data = subprocess.check_output(["git", "-C", str(path), "cat-file", "blob", f"{commit}:{name_in_tree}"])
            if len(data) != expected["bytes"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
                raise ContractError(f"Rehearsal bytes differ: {name}/{name_in_tree}")
        self.events.append(("verified", name, len(files)))
        return {"bytes": 0}


def main():
    project = manifests.load(ROOT)
    target = json.loads((ROOT / "releases/latest.json").read_text())["release_id"]
    manifest = release.read(ROOT, target)
    paths = {repo["github_name"]: ROOT / manifest["repositories"][repo["id"]]["path"]
             for repo in physical.repositories(project, manifest.get("physical"))}
    before = git(ROOT, "status", "--porcelain")
    with writer_lock(ROOT), tempfile.TemporaryDirectory() as saved:
        for relative in PROTECTED:
            if (ROOT / relative).exists():
                shutil.copytree(ROOT / relative, Path(saved) / relative)
        host = RehearsalHost(project["github_owner"], paths, lambda message: print(message, flush=True))
        try:
            result, _ = publication.run(ROOT, project, manifest, host=host)
        finally:
            for relative in PROTECTED:
                shutil.rmtree(ROOT / relative, ignore_errors=True)
                if (Path(saved) / relative).exists():
                    shutil.copytree(Path(saved) / relative, ROOT / relative)
    if git(ROOT, "status", "--porcelain") != before:
        raise SystemExit("Rehearsal changed tracked workspace files")
    pushes = [event for event in host.events if event[0] == "push"]
    print(f"REHEARSAL PASSED for release {target}: status {result['status']}, "
          f"{len(pushes)} simulated pushes, {sum(e[2] for e in host.events if e[0] == 'verified')} file checks; "
          "hub promoted last. GitHub and local records unchanged.")


if __name__ == "__main__":
    main()
