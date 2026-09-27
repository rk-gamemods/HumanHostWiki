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

## Current stages

| Stage | Completion evidence |
| --- | --- |
| Register | Clean, pinned source and immutable snapshot receipt |
| Availability | Timestamped Steam branch observation or explicit unavailable status |
| Normalize | Selected observations, coverage, dependency hashes and content exceptions |
| Identity | Durable identity decisions and normalized models |
| Project | Validated static reader candidate |
| Verify | Stage artifact checks, stable source and unchanged rules |
| Release | Exact child commits, output hashes and immutable coordinated Git manifest |
| Publish | Verified topic targets, hub promotion and immutable publication receipt |

The runner includes [coordinated Git release](RELEASE.md) and configured
[Pages publication](PUBLICATION.md). Complete gameplay coverage, gameplay
verification and capacity allocation remain required delivery work. A local release
alone cannot establish public availability or gameplay verification.

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

## Operator report

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
