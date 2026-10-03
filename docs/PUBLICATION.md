# Publish or abandon a coordinated release

The normal decompile command stops at a local Git release and retention. Live sites
change only through the separate `py -3 wiki.py publish --release <id>` operator
command, after code review, merge and successful rehearsal against live state.
`publication.enabled` in `project.json` enables this explicit command;
`publication.workers` bounds concurrent topic deployments. Content exceptions are
reported after the local update. Execution failures retain a separate failure receipt.

## Production gate

`wikibuild/publish_gate.py` fails closed on the first failed check, in this order,
before any remote effect or provisioning. An incomplete pending journal first
blocks the command and requires local abandonment; failed runs never resume.
The production checks then run in this order:

1. The HumanHostWiki workspace has no tracked changes or non-ignored untracked files.
2. `git remote get-url origin` identifies `github.com/rk-gamemods/HumanHostWiki`
   in HTTPS or SSH form. Local paths and other repositories or hosts are refused.
3. A bounded fetch of `origin` main updates `origin/main`, and `HEAD` equals that commit.
4. A read-only `GET /repos/rk-gamemods/HumanHostWiki/actions/runs?head_sha=<sha>`
   finds workflow `CI` at `.github/workflows/ci.yml`, triggered by `push` on `main`,
   completed with conclusion `success` for that exact commit.
   The newest matching run/attempt must succeed; absent or unfinished CI is refused.
5. `GET /repos/rk-gamemods/HumanHostWiki/commits/<sha>/pulls` returns a PR with
   `merged_at` set and `merge_commit_sha` equal to this exact commit. A direct push
   without matching merged-PR evidence is refused.
6. `.local/publication/rehearsals/<release-id>.json` is a valid successful rehearsal
   receipt for the requested release, current workspace commit and
   `publication.contract()`. Its UTC timestamp must be at most 24 hours old and
   cannot be in the future. The gate re-reads every recorded destination branch
   ref and refuses drift. Both `main` and `gh-pages` must be covered for every
   current destination.

The rehearsal command requires `--release <id>` and the same clean workspace
check before any other work. It reads live GitHub state and
simulates pushes, builds and verification locally. Only success, after restoring
publication state, writes a hash-checked receipt. The receipt records release id,
workspace commit, publication contract, UTC timestamp and each repository name,
branch and observed commit SHA (or `null` for an absent branch). It records actual
remote observations, never simulated branch tips. Receipt validity does not prove
that GitHub Pages will build; publication retains its deployment checks.
The contract hashes the rehearsal runner, gate and existing publication modules.

Publication journals the gate record and rehearsal receipt. Preparation refuses
any ref that changed after the gate, including this workspace's own lineage.
Before each push the ref must equal its rehearsed value, or this invocation's own
confirmed previous push. The adapter also checks fast-forward ancestry and uses
an explicit `--force-with-lease=refs/heads/<branch>:<expected>` to enforce that
tip atomically, with an empty expected value for an absent branch.
Every fresh invocation, including unchanged publication checks, passes the gate. There is
no override flag. A bypass requires a code change through a reviewed PR; branch
protection is unavailable for this private repository on GitHub Free.
Gate Git commands have a 120-second timeout and GitHub reads reuse the existing
bounded API adapter and authentication. No new credentials or dependencies are used.

## Owners and requirements

| Owner | Responsibility |
| --- | --- |
| `wikibuild/publish_gate.py` | Clean merged commit, exact-commit CI and rehearsal/live-ref preflight |
| `wikibuild/publication.py` | Provisioning identity receipts, prepared plans, topic verification, hub promotion, rollback and local abandonment |
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
pending. The operator must abandon the journal before rehearsing a fresh run.
SteamCMD's metadata check stops
after 300 seconds and is reported as unavailable. As a backstop for any wait
without its own bound, `wiki.py update` and `publish` stop themselves after four
hours; the OS then releases the writer lock. Local update stages recover on the
next run; failed publications must be abandoned. On 2026-09-29 a run without these bounds waited three days on a
build GitHub never finished.

## Durable state and abandonment

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
this identity and the dependency groups, so deployment and rollback address the same
repository during that invocation even after the active map changes.
The [capacity contract](CAPACITY.md) owns physical identities and size checks.
An incomplete pending publication blocks every release. The operator runs
`py -3 wiki.py abandon-publication`, which moves the journal to
`.local/publication/abandoned/<UTC-timestamp>-<release-id>/pending.json` with a
short README and makes no remote calls. Corrupt journals are archived under an
`unknown` release label. The next publication starts fresh after a new rehearsal
against current refs; preparation may adopt this workspace's previously published
lineage, but only when it matches the rehearsed refs. Before the first completed
publication, Pages lineage must start at a locally pinned publication root; main
must be an ancestor of the selected release. If the Pages parent changed,
its exact history is checked again.
The hub remains at its
previous release until every topic verifies. Direct topic landing pages consult
the hub's selection, so preparing a newer topic does not advertise an incomplete
release. Explicit historical release links continue to load their pinned content.

If the new hub fails verification, a new commit restores the previous validated
tree at that selection point. On the first publication, the fallback is an explicit unavailable page.
No history rewrite is allowed. Rollback is attempted only within the failing run.
A rollback interruption leaves evidence for abandonment, never automatic recovery.

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
# After an incomplete publication, before a new rehearsal:
py -3 wiki.py abandon-publication
py -3 -m unittest discover -s tests -p test_publication.py -v
```

`publish` selects an explicit local release; it never falls back to the latest
pointer. Review and merge workspace changes, wait for CI, then rehearse and publish.
On a publication failure, abandon the local journal, rehearse the selected release
against current live state, then publish afresh. A queued
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
rollback. The operator abandons this failed run before a new rehearsal. An explicitly failed build or a
failed public-content check still uses the rollback procedure above. Build reads
use the documented [Pages build endpoints](https://docs.github.com/en/rest/pages/pages#get-a-github-pages-build).

Tests use real Git objects and an isolated host adapter for exact deployment order,
independent completion, duplicate runs, interrupted pushes, changed remote refs,
modified journals, both rollback cases and history audits. Local HTTP tests cover
content hashing and oversized responses. Observation tests cover long-lived builds,
another latest build, missing records and unknown states. Gate tests cover origin,
CI identity, merged-PR evidence, receipt bindings, ref drift and local abandonment.
They do not establish live GitHub availability;
real deployment evidence belongs in [IMPLEMENTATION.md](IMPLEMENTATION.md).
