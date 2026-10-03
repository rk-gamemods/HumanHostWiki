# Identity and history contracts

The identity stage assigns wiki keys to selected observations and records why a
mapping was accepted or left unresolved. It does not grant gameplay verification.

| Owner | Input and responsibility | Output |
| --- | --- | --- |
| `wikibuild/identity.py` | Pure matching rules over selected descriptors and prior decisions | Keys, evidence and ambiguity |
| `wikibuild/model.py` | Selected observations, identities and relevant object-index matches | Semantic revisions and resolved/gapped relationships |
| `wikibuild/history.py` | Pinned extraction, corrections, prior ledger and writer lock | Immutable state, run receipt and last-success pointer |

`identity/` is durable umbrella-owned decision history. Keep it in Git. The
normalized content under `.local/` is staging for the later topic release stage;
it is not an accepted or published wiki release. Topic repositories remain the
owners of published canonical records and immutable content revisions.

Matching uses component/kind and container context plus corroborating evidence.
Exact identifiers alone are insufficient across game builds. Asset paths, names
and content hashes are evidence, never universal IDs. Higher-confidence matches
are reserved before weaker candidates so an unexplained new record cannot break
an established independent match. Splits, merges and ties retain new observations
and candidate links; the process never chooses an arbitrary winner.

An absent observation is `not-present` only when its source object is absent from
a complete current catalog and its extraction kind remains supported. A present
source object without an observation is an unresolved extraction/identity gap.
Missing capture scope is `uncaptured`. Historical states retain their original
decision, evidence and semantic revision.

Changes to semantic facts or canonical relationships create new revision hashes.
Source hashes, source identifiers and snapshot evidence are stored separately.
An unchanged revision can gain a new data-check record without changing its last
substantive-change snapshot. This does not establish runtime or page verification.

The request identity includes snapshot, extraction, matching contract and reviewed
corrections. The resulting run also pins its parent state. Write immutable files
and validate their hashes before promoting the last-success pointer. A retry after
interruption reuses that exact prepared run. Unknown/modified files fail closed;
an older request cannot silently rewind later decisions. The same OS-held wiki
writer lock protects extraction and identity promotion.

`identity/corrections.json` holds optional reviewed mappings. Each names a snapshot,
observation, target wiki entity (or `new`), reviewer and reason. Conflicting or
incompatible mappings are failures. A correction produces a new run and preserves
earlier decisions. The normal run never invokes an LLM to resolve candidates.

A reviewed mapping may list `supersedes` entity keys when correcting a component's
kind within the same captured snapshot. Each retired key must identify the exact
same source object and assembly/class, have a different kind, and no longer have
a current observation. Different objects, captures, active entities, duplicate
claims and conflicting replacements fail before promotion. The retired record
keeps its history and points to the replacement. This is an extractor correction,
not evidence that the game removed content. Unresolved absent observations are
included in the exception report even when all current relationships resolve.

Required proof covers unchanged repeats, source-ID changes, renames, reused IDs,
additions/removals, ambiguous splits/merges, extraction corrections, missing capture
scope, reviewed mappings, writer exclusion, modified outputs and interruption
before promotion. Full public history/navigation remains a later delivery gate.
