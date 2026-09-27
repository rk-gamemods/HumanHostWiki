# Implementation evidence

The [ADR](adr/0001-versioned-public-wiki.md) owns requirements. This file tracks
delivery evidence and unfinished work; an implemented stage does not prove the
complete product.

## Boundaries and performance

- The parent decompiler owns input stability, source/catalog capture and Git diff.
  The command invokes the wiki after successful capture or verified reuse.
- `wikibuild/source.py` reads hash-verified record ranges from the existing source
  checkout, with one streaming Git process for historical/mismatched local bytes.
  Adapters own field selection and interpretation. No raw catalog copy or public
  source tree is an intermediate wiki artifact.
- `wikibuild/exceptions.py` groups unsupported cases by rule/pattern, with counts
  and bounded examples. Execution failures propagate separately.
- Extraction results retain source hashes separately from semantic content hashes.
  Reuse checks include inputs, adapter/schema versions and required output hashes.
  New input discovery must run even when existing inputs are unchanged.
- Topic ownership stays in `project.json`. Identity, rendering, local release and
  publication have separate owners. Readers consume immutable release manifests;
  the hub points to a release only after every referenced target verifies.
- Use streaming and small selected-record joins first. Add SQLite only if measured
  access patterns justify it. Avoid parallel tasks that duplicate large resident
  catalogs; bounded concurrency suits independent decompiler and deployment jobs.

## Remaining completion gates

- Extend the integrated local runner through gameplay verification and publication
  without changing the operator workflow.
- Extract and independently validate every registered gameplay topic. Account for
  source objects locally without copying the whole index into wiki content.
- Complete individual asset identities, real cross-build identity coverage and
  dependency-based verification beyond the selected-observation identity stage.
- Complete historical capture coverage, reader presentation of interpreted units
  and conditions, authored-claim checks and useful external backlinks beyond the
  selected-fact reader. Add verified freshness inputs and page-check receipts.
- Create the declared public repositories, provision Pages, validate target content
  and promote the hub last. Prove retry, rollback and automatic capacity allocation.
- Run real initial generation and an unchanged repeat; measure time, bytes read,
  output size and peak memory. Exercise changed/new/removed/unsupported records and
  tool corrections, using real builds and focused fixtures for unavailable cases.
- Review public content for source fidelity and private-input exclusion, verify
  browser behavior and remote state, and audit every ADR acceptance requirement.

## Current evidence

- The item/loot extraction command produced 944 items, 29 loot tags, 51 loot tables
  and 862 loot sources from snapshot `build-25548639-9d77a0415918`. It read
  14,170,904 source bytes and produced 2,377,192 bytes of selected observations.
  An unchanged repeat read zero source bytes and reused hash-validated output.
  These counts cover the implemented contracts, not the complete game wiki.
- `py -3 tools/check_extraction.py` independently checked raw serialized records:
  78 assertions across 12 sampled observations covering all four implemented kinds.
- Extraction tests cover unknown/new/nested fields, unsupported source classes,
  reappearing dependencies, immutable reads, missing input, modified output,
  failure before pointer promotion and unchanged/irrelevant-change reuse.
- A real refresh created source commit `c0582635a6ecbe8dd85ed2271a3ab5f424d618ad`.
  Its only change was the generator hash. The immediate repeat verified installed
  hashes and skipped catalog export and all 197 assembly decompilations, retaining
  that commit and a clean source tree. Extraction from the new snapshot passed the
  same independent checks and reused identical observation bytes.
- The wiki suite passed 38 tests; the parent catalog suite passed 20 tests with the
  configured isolated Python dependencies. The mod solution built with zero warnings
  and zero errors. Map, registry, lock, documentation links and diff checks passed.
- Public repositories and release generation have not been implemented yet.
  No game files or third-party plugins were changed.

### Expanded extraction checkpoint

- Source commit `8f1263c7d28f1fcfd19e212c97d860cefa31b3b0` adds record byte offsets
  and SHA-256 hashes to the existing scripted-object index. Raw object bytes are
  unchanged. A real repeat verified the installed inputs and reused this clean
  source commit without catalog export or assembly decompilation.
- Topic-specific field contracts now extract 795 recipe observations, 70 skill
  observations, 36 status effects, 4,189 building configurations, and selected
  combat, creature, spawning, biome, vehicle and world settings, alongside the
  earlier item/loot records. These are source observations; duplicate definitions
  across containers have not yet been reconciled into canonical entities.
- Local accounting covers all 414,343 indexed objects: 4,834 selected component
  contracts, 2,832 selected-view inputs, 28,744 technical components, 305,404
  structural/technical records, 45,518 omitted media/rendering payload records,
  and 27,011 uninterpreted components. Only bounded type summaries describe the
  unselected records. This accounting is not complete gameplay interpretation.
- The exception report contains 191 unsupported component classes. Gameplay gaps
  include `Item_Info`, `Battle_Info`, `Zombie_Input` and trap/controller classes;
  they must be addressed before claiming the full ADR scope. Existing contracts
  complete despite those gaps. Infrastructure assemblies have explicit technical
  accounting rules, so known engine UI/rendering types do not require repeated
  manual classification.
- Three known editor-only decoding gaps remain attached to their technical type
  summaries and capture provenance; they are not presented as decoded fields.
- Independent validation checked 2,231 values/references/hash/name/count assertions
  across 92 sampled gameplay observations and 527 type summaries. It reads committed
  records through Git directly and does not import the extractor or source reader.
- A fresh benchmark took 2.442 seconds, read 109,252,036 source bytes (104.2 MiB),
  and produced 14,802,216 bytes (14.1 MiB) of selected records. Peak Python working
  set was 53.1 MiB, excluding the Git subprocess. The repeat took 0.096 seconds,
  read zero source bytes and preserved result bytes and the pointer timestamp.
  These are local measurements, not performance guarantees.
- The wiki suite passed 53 tests and the parent catalog suite passed 21 tests.
  New checks cover nested selection, null/unknown references, recipe projection,
  source/index hash disagreement, assembly-name collisions and object accounting.
  [Extraction contracts](EXTRACTION.md) identify the owning files for corrections.

### Selected identity checkpoint

- `wiki.py normalize` assigned wiki keys to 8,146 selected observations. The ledger
  retains matching evidence, ambiguity, semantic revisions and snapshot-specific
  provenance; source hashes do not determine semantic revision identity.
- The initial real-source model contains 76 unresolved relationship occurrences
  in two groups. Those gaps do not block other facts or relationships. The stage
  has no model calls and grants no gameplay/current-version badge.
- `tools/check_history.py` independently validated 101,032 assertions across all
  8,146 observations, including conservation, values, revision hashes, provenance
  and target aliases. It does not import identity, model or source-reader code.
- A combined local benchmark measured identity at 1.745 seconds fresh and 0.121
  seconds unchanged, with zero source bytes read on repeat. Peak Python working
  set for extraction plus identity was 62.5 MiB, excluding Git. The initial ledger
  is 8.4 MiB and model staging is 22.2 MiB. Public storage must still reuse immutable
  revisions and enforce capacity budgets; these staging files are not releases.
- Earlier real builds `25448142` and `25407931` contain decompiled code and
  `BUILD_INFO.md` but no asset catalog. Future historical registration must expose
  that capture gap rather than apply present-day asset facts to those builds.
- [Identity contracts](IDENTITY.md) locate matching rules, graph projection,
  reviewed corrections and persistent transaction ownership. Full historical
  browsing, underlying asset identities and publication remain incomplete.
- The suite passed 80 tests after adding duplicate-observation rejection and
  stable reviewed-new allocation across matching-rule changes. Reprocessing the
  real snapshot after that correction preserved all 8,146 semantic revisions;
  the independent checker passed again and the unchanged repeat reused its run.

### Static reader checkpoint

- `wiki.py reader` projects the 8,146 selected observations into 517 files across
  the 13 topic/hub directories, totaling 39,017,231 bytes (37.2 MiB). There is no
  raw source tree, asset index or media payload in those inputs or outputs.
- The reader includes topic/group navigation, search, selected facts, evidence,
  reverse links and snapshot selection. Immutable semantic/provenance packs are
  shared across snapshots. The largest real pack is 457,933 bytes, below 512 KiB.
  Generated Markdown groups preserve a readable Git navigation fallback.
- An independent checker compared all selected models against emitted facts,
  provenance, search records and reverse relationships: 73,316 assertions passed.
  This complements the separate real-source extraction/identity checks; it is not
  gameplay verification.
- Browser checks exercised Wood item search, its 222 reverse relationships,
  evidence identifiers and a cross-topic Crude Axe recipe link retaining the
  selected snapshot. A two-build fixture exercised an entry absent in the newer
  snapshot and present with its original facts in the older snapshot.
- The first real run exposed a reverse-link list over 600 KB. Reverse links now
  occupy separate bounded packs, loaded when opened. Browser review also caught
  string notes being iterated as characters; notes now render as complete text.
- `tools/benchmark_reader.py` measured 1.809 seconds fresh and 0.300 seconds on
  repeat, with stable bytes/file timestamps/pointer and no raw source reads.
  Releasing projection buffers before validation reduced measured Python peak
  working set from 183,099,392 to 140,353,536 bytes (about 134 MiB) without slowing
  this run. These measurements exclude browser memory and are local observations.
- The benchmark initially hit Windows path limits in per-file temporary names.
  Reader output now writes exclusively into its new private staging directory,
  validates the directory, then promotes it by rename. The benchmark uses a
  shallow ignored output path; no global OS setting or file protection changed.
- [Reader contracts](READER.md) own the new boundaries. Real older-build capture
  support, gameplay verification, curated assertions, external article checks,
  site/repository capacity allocation and coordinated publication remain open.
- Focused tests cover output protection, partial-write retry, safe URL bases,
  bounded reverse links, unchanged revisions, capture gaps and historical group
  routes after a whole group disappears. The complete wiki suite passed 92 tests.
  Registry/map/lock checks and JavaScript syntax validation also passed. The final
  real candidate passed the independent check and an immediate unchanged repeat.

### Integrated runner checkpoint

The decompile wrapper invokes `wiki.py update --operator-report` after successful
full capture, including unchanged capture. The runner completes the supported
local stages and writes one deterministic exception report. Execution failures
have separate receipts and preserve the previous overall success. Request
receipts retain the last successful comparison baseline across skipped or failed
captures. Source-only and partial diagnostic exports explicitly skip the wiki.

Ten integration tests exercise actual extraction, identity and rendering over
small committed source fixtures: supported changes with unknown fields, unchanged
reuse, corrupted artifacts, dirty source, older-request rejection, interrupted
promotion, changed request baselines, concurrent writer rejection and recovery
across failed/skipped captures. The wrapper has seven
isolated PowerShell handoff cases. These establish local orchestration, not public
release or complete gameplay coverage. See [the runner contract](PIPELINE.md).

Integration testing exposed Windows path overflow after moving a reader candidate
from staging to its longer final directory. New cache directory names use 24
hexadecimal hash characters; manifests and pointers retain and validate the full
256-bit identity. A prefix collision fails validation. Existing full-hash paths
remain readable. The builder checks final Windows path lengths before writing.

The real wrapper run captured source commit
`a7d9406a5bfbf46a18e81c8b3edd5ea51f947ed1` for Steam build 25548639. Only
`Catalog/generator.json` changed. Identity classified all 8,146 selected
observations as unchanged in an extractor correction. The combined report has
193 unresolved groups and 27,087 occurrences; these did not block reader output.
This is a second capture revision of the same game build, not proof of real
cross-build historical coverage.

Independent checks passed: extraction (2,231 assertions), identity (101,032),
and reader (146,632 across 16,292 observations in the two selected snapshots).
Reader output contains 602 files totaling 46,383,400 bytes, with a largest data
pack of 457,933 bytes. The full 100-test suite passed before four additional
focused regression tests were added; the final reader and pipeline suites also
passed (14 and 10 tests). Parent catalog tests passed (21), and the mod solution
built with zero warnings and errors.

A real repeat of the normal command reused capture and wiki artifacts, preserving
source Git HEAD, all four success pointers' bytes/timestamps and reader file
timestamps. The final measured repeat took 36.195 seconds including installed-input
hashing; wiki-only reuse took 0.866 seconds and read no selected source bytes.
Python peak working set for that wiki-only repeat was 27,017,216 bytes; capture,
Git and PowerShell memory are excluded. The request-baseline guard also passed
its focused corruption regression.

### Coordinated Git release checkpoint

The integrated update commits selected generated output to all 13 child repositories
and records their exact commits, trees, routes and output hashes in an immutable
release manifest. The first real release is
`0c355d746f9e6cfe30ec0ca83fc6fcc8c78229a0e5935f880b167eba9f450bda`.
It is local and unpublished. All 193 unresolved content groups remain reported;
they did not block the supported release. [Release contracts](RELEASE.md) own
preparation, output ownership, retained historical objects and recovery.

The full suite passed 113 tests. Release tests use independent Git repositories
and exercise interruption during file promotion, between children and after a
branch update. Retry reuses the prepared commits. Other cases preserve authored
content, unknown ignored files and unexpected staged edits, and reject a modified
journal. A real integration fixture commits all 13 topics despite content gaps.
The eight release tests passed again after adding independent audit assertions,
including modified-pack rejection and two-release reachability.

`tools/check_release.py` independently checked 667 generated files totaling
46,833,111 bytes (44.7 MiB), including exact Git blob identities and conservation
of 589 candidate files after the documented path/link transformations. It also
checked all 13 release configurations and their referenced indexes, packs and
runtimes. The checker imports no release or renderer implementation.

`tools/benchmark_release.py` measured an unchanged `wiki.py update` at 2.269 seconds.
All 13 child commits and 686 file hashes/timestamps stayed unchanged. Extraction
and identity read zero source bytes. This excludes the parent capture/input-hashing
step and is a local measurement, not a performance guarantee.

The local committed-site browser check exercised topic navigation, Wood search,
entry facts and switching between the two capture revisions. Links retained the
selected snapshot and release. Requesting a missing release displayed an explicit
error without substituting current content. These revisions belong to the same
Steam build; they do not satisfy the real cross-build acceptance gate. Public
deployment, automatic capacity allocation and staging retention remain unfinished.

## Deferred classifier experiments

No classifier is implemented. Record evidence-backed candidates here as adapters
encounter them, including examples, expected labels, error impact, held-out test
data and accuracy/cost comparison with rules and manual review.

One candidate is reader-facing subcategory assignment for items whose existing
`Icon_Info._Tag` is broad: for example, `BuildMat` covers internally named building
shapes and materials. A classifier could propose labels from the English item
name and selected tags when explicit game enums/relationships do not decide them.
Test on manually labeled held-out items from different builds, measuring precision,
abstention, repeatability, memory and latency. Wrong labels affect navigation;
they must never alter extracted facts, canonical identities or declared ownership.
