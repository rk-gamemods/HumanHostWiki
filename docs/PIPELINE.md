# Operator update contract

`HumanHostMods/tools/Decompile-GameCode.ps1` owns the normal entrypoint. After a
successful full capture, including capture reuse, it invokes `wiki.py update`
with the captured source path. Topic extraction contracts select the necessary
facts and evidence in place. Raw source trees and whole catalogs never become
wiki output or model input.

`wikibuild/pipeline.py` owns stage ordering, the last successful processing point
and the final operator report. Stage implementations own their validation,
dependency invalidation and reusable artifacts. The shared OS-held wiki writer
lock covers registration through final promotion. The existing capture lock
protects capture; pinned source identity is rechecked before wiki promotion.

## Stage sequence

`project.json` declares capture as the external prerequisite, then the fixed
local sequence below. Installed-input detection and capture reuse belong to the
parent capture command. Steam availability runs after registration.
`manifest.stage_order` rejects a missing, extra or reordered stage and requires
dependencies to enforce each consecutive step. Foundation tests compare the
fixed order with `pipeline.run`'s stage-entry calls. Final receipt promotion is
internal bookkeeping after reader retention, not another product stage.

| Stage | Completion evidence |
| --- | --- |
| Register | Clean, pinned source and immutable snapshot receipt |
| Availability | Timestamped Steam branch observation or explicit unavailable status |
| External articles | Versioned article observations or explicit provider unavailability |
| Normalize | Selected observations, coverage, dependency hashes and content exceptions |
| Identity | Durable identity decisions and normalized models |
| Project | Validated static reader candidate |
| Verify | Stage artifact checks, stable source and unchanged rules |
| Release | Exact child commits, output hashes and immutable coordinated Git manifest |
| Retention | Remove verified duplicate release staging payloads, preserving committed releases |
| Reader retention | Share identical immutable reader files, preserving candidate paths |

The runner ends after [coordinated Git release](RELEASE.md), release retention and
reader retention. [Pages publication](PUBLICATION.md) is a separate gated operator
command after a successful rehearsal: `py -3 wiki.py publish --release <id>`.
Routine updates never construct a live publication host. Release preparation
applies [capacity allocation](CAPACITY.md). A local release alone cannot establish
public availability or gameplay verification. [ACCEPTANCE.md](ACCEPTANCE.md) owns
delivery status and evidence limits.

[Build availability](AVAILABILITY.md) is checked independently after source
registration. Remote unavailability is reported separately while supported content
continues. Its immutable observation participates in request and reader identities;
it cannot change source receipts or grant gameplay verification.

## State and recovery

Operational receipts live under `.local/pipeline/`:

- `requests/<hash>.json` freezes the inputs and previous successful run before
  extraction. A retry keeps this baseline even if intermediate stages completed.
- `runs/<hash>.json` records completed stage identities, the source comparison
  baseline, remaining work and the grouped exception list. Contents determine
  the full hash. Timing and reuse metrics stay outside this immutable result.
- `latest.json` advances only after all implemented stages and final checks pass.
- `failures/<hash>.json` identifies the failing stage, completed stages, typed
  error and content exceptions collected before failure. It cannot advance success.

Each invocation appends `.local/pipeline/timings/<UTC timestamp>-<status>.json`
with UTC start/finish, total and stage seconds, the failed stage if any, and
publication timings; these mutable operational files never enter content hashes.
Timing write failures are reported to stderr and do not change the update outcome.

Each invocation revalidates stage artifacts before reuse. A completed request
produces identical result bytes and leaves pointer timestamps unchanged. An older
request cannot rewind later successful work. Changed or unknown outputs are
preserved and refused. A failed final promotion can reuse the prepared result;
successful stages need not repeat their computation. Diagnostic stage pointers
may advance before the overall pipeline finishes and are not release pointers.

The comparison baseline is the previous successful pipeline run, not the source
repository's previous commit. Failed or skipped captures therefore cannot hide
changes from a later successful run. The first pipeline run has no comparison
baseline. Public release coordination must retain its separate publication state.

After the local release, [release-staging retention](RETENTION.md)
removes verified duplicate payloads under the same writer lock. Its counts appear
in invocation metrics, outside immutable pipeline results. Preserved cleanup
issues are recorded separately from content exceptions and do not undo the completed
release. Pending release transactions remain untouched. Retention removes only
verified staging duplicates; published releases and the newest local release
awaiting publication retain their manifests, committed objects and reader paths.

## Run timing schema

`wikibuild/run_timing.py` owns command diagnostics. Each `update` and `publish`
exclusively creates one complete JSON file under
`.local/runs/wiki-<command>-<UTC>-<8 hex>.json`. A flushed staging file is linked
atomically to the final name without replacing existing records. Timing is
excluded from requests, immutable pipeline results and release identities.
Save failures produce a warning without changing the command outcome.

| Key | Type and meaning |
| --- | --- |
| `schema` | String, `humanhost.wiki-timing.v1` |
| `command` | String, `update` or `publish` |
| `started_at`, `finished_at` | UTC ISO 8601 strings |
| `seconds` | Nonnegative wiki wall time from a monotonic clock |
| `outcome` | `succeeded`, `failed` or `timed-out` |
| `release_id` | Release identity string when known, otherwise null |
| `stages` | Array of `{name, seconds, outcome, basis}` |
| `capture` | Null, or `{seconds, outcome, phases: [{name, seconds, outcome}]}` |

Update stages follow the pipeline, including partial duration of the active
stage on failure or timeout. Publish stages include gate, preparation, topic
phases, hub and other observed phases. Each repository also records push
(`push_main + push_pages`), Pages wait (`pages_build`) and verification seconds,
including rollback work. Stage outcomes are `succeeded`, `failed`, `timed-out`
or `not-run`. `basis` is `wall` for stages/phases and `repository-sum` for
repository details. Repository sums overlap parallel wall phases; adding all
rows does not yield elapsed time. The three largest items use capture phases
and wiki wall stages only, divided by capture total plus wiki wall time.

`update --capture-timing <path>` validates `humanhost.capture-timing.v1` before
embedding the summary. Required fields are `schema`, `started_at`, `finished_at`,
`seconds`, `outcome`, `error`, `output_path`, `output_commit`, `game`, `phases`
and `assemblies`. Timestamps are strings with timezones; path is a string.
Game is a version/build object with string or null fields, or null before identity
is available; legacy game strings remain accepted. Error and commit are strings or null; durations are finite,
nonnegative numbers, excluding booleans. Outcomes are `succeeded`, `failed`
or `reused`. Both arrays contain `{name: string, seconds: number, outcome}`, accepting
`succeeded`, `failed`, `reused` and `skipped` work.
Unknown fields are ignored. A missing or invalid receipt emits one warning;
the wiki continues without capture timing.

The watchdog claims `timed-out`, fences new child launches and supervises registered
process-tree, writer owner metadata and registered temporary-file cleanup before
exiting 124. The recorder-lock wait is limited to five seconds; an unavailable lock
is reported and cannot prevent exit. Cleanup has a 60-second grace, with unresolved
child PIDs and unfinished work reported before exit. Unconfirmed Windows jobs stay
registered and open for bounded cleanup retries. Timing saves run alongside cleanup,
with a final bounded diagnostic wait. Journals
and stage artifacts remain for update recovery; a timed-out publication requires
`abandon-publication`. Abrupt termination or blocked storage can prevent a timing
record. Repeated finalization cannot create a second record.
`wiki.py timing [--last N]` reads the latest records across both commands without
loading project configuration or acquiring the writer lock.

## Operator report

The report keeps its existing fields and adds `release_id` and `next_step`, naming
the explicit publish command after rehearsal. `--operator-report` remains compatible
with the decompile wrapper. The command's final Run timing table shows capture,
wiki stages and totals. Legacy stage-only timing reports remain readable.

The `external-articles` stage records bounded community-wiki checks as a versioned
input. Its configured source and routes are owned by [EXTERNAL_LINKS.md](EXTERNAL_LINKS.md).
The report lists unavailable article titles/reasons and incomplete inventories
separately from game-content exception groups. Provider outages permit supported
gameplay work to finish; invalid configuration or damaged local receipts are
execution failures. External article checks never grant gameplay verification.

Supported content proceeds while unresolved content is grouped by stage, topic,
code and pattern. Every occurrence contributes to counts; each group retains at
most eight source examples. Groups are marked new, changed or unchanged relative
to the previous distinct successful run. Repeating the same run preserves that
report instead of producing another history entry or re-analyzing exceptions.

The command prints stage progress and, after completion, the exception list and
full receipt path. The operator presents those issues and asks for direction.
Model-assisted explanation, classification or resolution is not an execution
stage. Execution failures return nonzero and identify a separate failure receipt.
After diagnosis and repair, rerun the normal command.

`-NoGit`, `-Assemblies` and `-SkipWiki` select source-only diagnostic behavior.
`-WikiPath` selects a configured umbrella. A missing wiki command after a normal
capture is an explicit failure, not a successful wiki update. No scheduler,
spending limit, automatic LLM processor or classifier is part of this contract.
