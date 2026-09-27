# Publish and recover a coordinated release

The normal decompile command runs publication after the local Git release. Enable
it once with `publication.enabled` in `project.json`; `publication.workers` bounds
concurrent topic deployments. The current project enables publication under
`rk-gamemods`. The operator receives content exceptions after supported publication
finishes. Execution failures retain a separate failure receipt.

## Owners and requirements

| Owner | Responsibility |
| --- | --- |
| `wikibuild/publication.py` | Provisioning identity receipts, prepared plans, topic verification, hub promotion and recovery |
| `wikibuild/publication_git.py` | Public history audit and Pages commit trees without another checkout |
| `wikibuild/github_pages.py` | GitHub CLI/API calls, fast-forward pushes, build observation and public HTTP hashes |
| `wikibuild/release_bootstrap.js` | Resolve a requested release or follow the hub's coordinated selection |

GitHub CLI and Git use existing local authentication. Credentials remain outside
the repository. The account must administer the configured organization/repositories
and have repository and Pages access. No scheduler, custom Actions workflow, LLM
processor or new hosted service is required.

The adapter uses GitHub's [Pages API](https://docs.github.com/en/rest/pages/pages)
and [branch publishing](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).
The `main` branch keeps readable reference documents and generated site files.
The `gh-pages` branch uses the exact site subtree as its root, sharing existing Git
objects. `.nojekyll` avoids an additional rendering step. Builds are observed for
the exact pushed commit, followed by HTTP content-hash checks.

## Durable state and recovery

The umbrella OS writer lock covers publication. Before the first push, audit new
outgoing Git history, including deleted files, for allowed text paths and obvious
private machine paths/credential markers. This complements selected-input extraction
and artifact validation; it cannot prove arbitrary authored prose is appropriate.
Authored public Markdown belongs under `authored/`. Unknown public paths fail
the audit and remain local.

`.local/publication/remotes/` records destination identity before/after creation.
Existing unrelated repositories are never adopted. Completed publication receipts
can reconstruct missing local remote records. Preserve incomplete provisioning
records: an empty remote alone does not prove ownership after local state loss.

`.local/publication/pending.json` records exact main/Pages commits, prior refs,
expected files and per-topic verification before deployment. Its content hash
detects accidental modification. Prepared Pages objects have local Git refs so
ordinary Git maintenance cannot discard an interrupted attempt. Pushes are
fast-forward only; unexpected remote edits fail without overwriting them.

Independent topics finish even if another topic fails. The hub remains at its
previous release until every topic verifies. Direct topic landing pages consult
the hub's selection, so preparing a newer topic does not advertise an incomplete
release. Explicit historical release links continue to load their pinned content.

If the new hub fails verification, a new commit restores the previous validated
hub tree. On the first publication, the fallback is an explicit unavailable page.
No force push or history rewrite is used. A rollback interruption is recorded and
completed on retry before attempting the new hub again.

After success, `publications/<release-id>.json` records remote identities, commits,
expected public bytes and validation completion. `publications/latest.json` advances
last. These receipts are distinct from local `releases/` manifests. Repeating an
unchanged run verifies current remote refs and small reader pointers, reusing prior
immutable-file checks. A changed release downloads only new/changed files and the
entry shells; unchanged packs retain their earlier verification evidence.

## Commands and tests

```powershell
py -3 wiki.py update --operator-report
py -3 wiki.py publish
py -3 -m unittest discover -s tests -p test_publication.py -v
```

`publish` is a recovery/diagnostic entrypoint for the latest local release. Normal
maintenance uses the integrated update. On a transient network failure, rerun the
same command; completed stage receipts and confirmed pushes are reused. A queued
or running build is polled without restarting it.

Tests use real Git objects and an isolated host adapter for exact deployment order,
independent completion, duplicate runs, interrupted pushes, changed remote refs,
modified journals, both rollback cases and history audits. Local HTTP tests cover
content hashing and oversized responses. They do not establish live GitHub availability;
real deployment evidence belongs in [IMPLEMENTATION.md](IMPLEMENTATION.md).
