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

Every external wait has a bound. `wikibuild/bounded.py` runs `gh` and `git push`
with all pipe I/O on daemon threads and kills the whole process tree at the
deadline, so a descendant holding a pipe cannot outlast it. Each `gh api` call
times out after 120 seconds. A GET is retried up to four times; a POST is not
repeated after a timeout or 5xx, because it may have taken effect, and its caller
reconciles instead. Each `git push` times out after 600 seconds, and the remote
ref then decides whether it landed. A Pages build still queued or building after
30 minutes, ours or one ahead of it, stops the run with the publication left
pending. The next run reconciles that commit. SteamCMD's metadata check stops
after 300 seconds and is reported as unavailable. As a backstop for any wait
without its own bound, `wiki.py update` and `publish` stop themselves after four
hours; the OS then releases the writer lock and the journaled stages recover on
the next run. On 2026-09-29 a run without these bounds waited three days on a
build GitHub never finished.

## Durable state and recovery

The umbrella OS writer lock covers publication. Its holder records its PID, start
time and command in `.local/writer.lock.owner.json`. A blocked run reports that
holder, how long it has held the lock and whether it is still running. Before the first push, audit new
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

Allocated storage sites verify before dependent topic entrypoints are pushed.
Within each phase, independent workers finish even if another worker fails.
Replacement topic fronts verify before the successor records that select them.
For hub rollover, the new hub front verifies before the retiring hub publishes
its successor record. That retiring hub is the selection point for the transaction;
otherwise the active hub is the selection point. The publication journal records
this identity and the dependency groups, so retry and rollback address the same
repository even after the active map changes. Older pending journals retain their
original hub behavior.
The [capacity contract](CAPACITY.md) owns physical identities and size checks.
An earlier pending publication is completed before preparing a newer deployment;
if this changes the prepared Pages parent, its exact history is checked again.
The hub remains at its
previous release until every topic verifies. Direct topic landing pages consult
the hub's selection, so preparing a newer topic does not advertise an incomplete
release. Explicit historical release links continue to load their pinned content.

If the new hub fails verification, a new commit restores the previous validated
tree at that selection point. On the first publication, the fallback is an explicit unavailable page.
No force push or history rewrite is used. A rollback interruption is recorded and
completed on retry before attempting the new hub again.

After success, `publications/<release-id>.json` records remote identities, commits,
expected public bytes and validation completion. `publications/latest.json` advances
last. These receipts are distinct from local `releases/` manifests. Repeating an
unchanged run verifies current remote refs and small reader pointers or storage
landing pages, reusing prior
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
or running build is polled without restarting it, up to the 30-minute build deadline.
Once GitHub returns a build identity, subsequent reads address that build. If the
latest record belongs to another commit, the adapter checks the recent build
inventory before treating the target as unobserved. Twelve consecutive successful
checks with no target or earlier live build return an observation failure. This
bounds missing-job discovery, not the runtime of a queued or running job.

GitHub can leave a Pages build at `building` after its own deployment workflow fails, for
example on a transient "Failed to get ID Token" timeout. After five minutes of a live build the
adapter reads the `pages build and deployment` run for the commit. A failed run is rerun up to
three times; a fourth failure stops publication with the run's link.

An exhausted observation retry, missing build record or unknown build status keeps
the prepared publication pending. It does not trigger another build or a hub
rollback. Rerunning reconciles the same commit. An explicitly failed build or a
failed public-content check still uses the rollback procedure above. Build reads
use the documented [Pages build endpoints](https://docs.github.com/en/rest/pages/pages#get-a-github-pages-build).

Tests use real Git objects and an isolated host adapter for exact deployment order,
independent completion, duplicate runs, interrupted pushes, changed remote refs,
modified journals, both rollback cases and history audits. Local HTTP tests cover
content hashing and oversized responses. Observation tests cover long-lived builds,
another latest build, missing records, unknown states and retry without another
hub push. They do not establish live GitHub availability;
real deployment evidence belongs in [IMPLEMENTATION.md](IMPLEMENTATION.md).
