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
5. GraphQL `associatedPullRequests` for this commit returns a merged PR whose
   `mergeCommit.oid` is this exact commit. REST API version 2026-03-10 returns
   `merge_commit_sha` as null, so the gate no longer reads it. A direct push
   without matching merged-PR evidence is refused.
6. `.local/publication/rehearsals/<release-id>.json` is a valid successful rehearsal
   receipt for the requested release, current workspace commit and
   `publication.contract()`. Its UTC timestamp must be at most 24 hours old and
   cannot be in the future. The gate re-reads every recorded destination branch
   ref and refuses drift. Both `main` and `gh-pages` must be covered for every
   current destination. It also re-reads each destination's repository identity,
   visibility and Pages configuration and requires the recorded observation to match.

The rehearsal command requires `--release <id>` and the same clean workspace
check before any other work. It reads live GitHub state and
simulates pushes, builds and verification in an OS-temp workspace. Each child
repository has a disposable shared clone: existing objects are borrowed read-only,
and new objects, fetched refs and `refs/wiki-publications/` pins stay in the clone.
Clone, setup and storage snapshot commands use 120-second bounds with descendant
cleanup. Clones use an empty template and an empty hooks directory. The isolated
Git environment ignores system/global configuration, external filters and inherited
Git routing variables; clone setup retains only the source's committer identity.
The engine reads copies of provisioning records, publication history and journals;
every engine write, including publication receipts, goes to the temporary workspace.
Before deleting that workspace, the runner compares the real children's complete
`git for-each-ref` output, pin files (including packed refs) and `git count-objects -v`
output byte-for-byte with their starting values. It also verifies original publication
state. A defensive restore retains its durable backup and displaced files until equality
is verified; a failed restore fails loudly and reports the retained backup path.
Only success after these checks and temporary cleanup writes a hash-checked receipt.
The runner prints its temporary root and records ownership in
`.local/publication/rehearsal-temp.json`, with a matching marker in that root.
Success removes both. The next invocation removes an abandoned recorded root only
after checking its OS-temp location and ownership marker; it never scans for folders
to delete. A failed restore retains the record and backup for explicit recovery.
The receipt records release id,
workspace commit, publication contract, UTC timestamp and each repository name,
branch and observed commit SHA (or `null` for an absent branch). It records actual
remote observations, never simulated branch tips. Each destination also records
`{"repository": "<name>", "observed": "absent" | "pages-disabled" | "present"}`.
Existing destinations bind their repository ID, identity, visibility, administrator
permission and relevant Pages settings. The shared read-only validator checks the
repository identity, visibility, Pages source, CNAME and `html_url` at each
destination's first remote effect in either production or rehearsal. Existing Pages
settings are checked by `configure()` before pushes to that destination. Enablement
waits until its source branch exists. Immediately before hub promotion, all destination
configurations are checked again, allowing only this invocation's confirmed
provisioning transitions.

A missing repository or disabled Pages site is provisioned only in the local
simulation. Its observation remains absent or disabled in the receipt. The production
gate refuses if that state changed, an existing repository was replaced, or its bound
settings differ. Production then creates the repository or enables Pages through
the usual provisioning path. Receipt validity does not prove
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
ref then decides whether it landed. Build observations and their API retries share
an elapsed deadline. A Pages build for the pushed commit still unfinished after
30 minutes stops the run with the publication left
pending. The operator must abandon the journal before rehearsing a fresh run.
SteamCMD's metadata check stops
after 300 seconds and is reported as unavailable. As a backstop for any wait
without its own bound, `wiki.py update` and `publish` stop themselves after four
hours; the OS then releases the writer lock. Local update stages recover on the
next run; failed publications must be abandoned. On 2026-09-29 a run without these bounds waited three days on a
build GitHub never finished.

## Stuck Pages builds

Only the pushed commit's Pages build and newest workflow attempt determine its
state. A workflow queued, waiting or pending with no started job is
`queued-not-started`; unknown job observations fail and unrelated old queued runs
are ignored. After five continuous minutes for the same run ID and attempt,
publication journals one successor commit with the stuck
commit as its parent and exactly the same tree, then pushes with a lease expecting
the stuck SHA. The confirmed transition becomes this invocation's expected ref.
Recovery ref reads, the push and the successor wait share the original 30-minute
deadline. Verification checks the same file hashes. Runs are never cancelled or deleted.

Each repository gets one successor attempt per invocation. If the successor also
stays queued, publication fails and preserves the transition in the journal.
The operator must run `py -3 wiki.py abandon-publication`, then rehearse a fresh
run later. Missing builds and unknown observations do not trigger recovery.

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
short README and makes no remote calls. It also archives every rehearsal for that
release and releases named in the journal's gate receipts, including duplicate
receipt files. Publishing requires a fresh rehearsal even when live refs did not
change. A matching immutable publication receipt saved before `latest.json`
advanced is archived as `publication.json`; a receipt referenced by `latest.json`
is never moved. Other attempts' publication receipts are preserved. The archive
uses short receipt names and records original paths in its README.
Corrupt or non-object journals are archived under an `unknown` release label.
Because their attempt cannot be identified, all rehearsal receipts are invalidated;
completed publication history is preserved. The next publication starts fresh after a new rehearsal
against current refs; preparation may adopt this workspace's previously published
lineage, but only when it matches the rehearsed refs. Before the first completed
publication, Pages lineage must start at a locally pinned publication root with
durable publication provenance; main must be an ancestor of the selected release.
If the Pages parent changed, its exact history is checked again.

Run `py -3 wiki.py publication-pins` for a read-only list of unprovenanced pins
(destination, ref, commit and exact `retire_command`), including dangling symbolic
refs with a null commit and their symbolic target. Ownership requires a hash-valid
completed publication receipt in `publications/*.json` whose bytes match the blob
at `HEAD:publications/<id>.json`, naming that destination and commit, including
adopted `old_pages` and recovery; saved or abandoned journals never qualify.
Committed receipts are trusted as reviewed history; the residual risk of someone
committing a simulated receipt is accepted and must be caught in review.
After reviewing and confirming a pin is
disposable, run its reported `git -C '<destination-path>' update-ref --no-deref -d '<ref>' <commit>`
from the workspace root; symbolic refs use the same command without `<commit>`.
The expected commit protects changed direct refs, and `--no-deref` removes a
symbolic pin itself while preserving its target. Preserve
ambiguous work. Pin creation reuses identical direct pins and refuses existing
symbolic or different-target refs under Git's ref lock; code never automatically
deletes or retargets pins. At each prepared pin write, rehearsal applies the same
collision check read-only to that exact target in the source repository, including
dangling symbols. Historical pins remain lineage input; an unchanged publication
never enters preparation, so rehearsal checks no source pins.

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
against current live state, then publish afresh. A running build is polled up to
the 30-minute build deadline; never-started jobs use the recovery described above.
Once GitHub returns a build identity, subsequent reads address that build. If the
latest record belongs to another commit, the adapter checks the recent build
inventory before treating the target as unobserved. Twelve consecutive successful
checks with no target build or matching workflow return an observation failure.
Unrelated live builds do not extend this discovery window.

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
