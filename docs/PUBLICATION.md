# Publish and recover a coordinated release

The normal decompile command stops at a local Git release and retention. Live sites
change only through the separate `py -3 wiki.py publish --release <id>` operator
command, after code review, merge and successful rehearsal against live state.
`publication.enabled` in `project.json` enables this explicit command;
`publication.workers` bounds concurrent topic deployments. Content exceptions are
reported after the local update. Execution failures retain a separate failure receipt.

## Production gate

`wikibuild/publish_gate.py` fails closed on the first failed check, in this order,
before any remote effect, pending-publication resume or provisioning:

1. The HumanHostWiki workspace has no tracked changes or non-ignored untracked files.
2. A bounded fetch of `origin` main updates `origin/main`, and `HEAD` equals that commit.
3. A read-only `GET /repos/rk-gamemods/HumanHostWiki/actions/runs?head_sha=<sha>`
   finds workflow `CI` completed with conclusion `success` for that exact commit.
   The newest matching run/attempt must succeed; absent or unfinished CI is refused.
4. `.local/publication/rehearsals/<release-id>.json` is a valid successful rehearsal
   receipt for the requested release, current workspace commit and
   `publication.contract()`. Its UTC timestamp must be at most 24 hours old and
   cannot be in the future. The gate re-reads every recorded destination branch
   ref and refuses drift. Both `main` and `gh-pages` must be covered for every
   current destination and any earlier pending publication destination.

The rehearsal command requires `--release <id>`. It reads live GitHub state and
simulates pushes, builds and verification locally. Only success, after restoring
publication state, writes a hash-checked receipt. The receipt records release id,
workspace commit, publication contract, UTC timestamp and each repository name,
branch and observed commit SHA (or `null` for an absent branch). It records actual
remote observations, never simulated branch tips. Receipt validity does not prove
that GitHub Pages will build; publication retains its deployment checks.

Publication journals the gate record and rehearsal receipt. Every invocation,
including recovery and unchanged publication checks, passes the gate. If live refs
changed during an interrupted deployment, rehearse again before resuming. There is
no override flag. A bypass requires a code change through a reviewed PR; branch
protection is unavailable for this private repository on GitHub Free.
Gate Git commands have a 120-second timeout and GitHub reads reuse the existing
bounded API adapter and authentication. No new credentials or dependencies are used.

## Owners and requirements

| Owner | Responsibility |
| --- | --- |
| `wikibuild/publish_gate.py` | Clean merged commit, exact-commit CI and rehearsal/live-ref preflight |
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
py -3 tools/rehearse_publication.py --release <id>
py -3 wiki.py publish --release <id>
py -3 -m unittest discover -s tests -p test_publication.py -v
```

`publish` selects an explicit local release; it never falls back to the latest
pointer. Review and merge workspace changes, wait for CI, then rehearse and publish.
On a transient network failure, rerun the same command after refreshing the
rehearsal if required; completed receipts and confirmed pushes are reused. A queued
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
