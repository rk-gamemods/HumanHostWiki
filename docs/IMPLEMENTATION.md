Historical evidence through 2026-09-27. For current status, see [ACCEPTANCE.md](ACCEPTANCE.md).

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

## Delivery status

The implemented reference is public at https://rk-gamemods.github.io/HumanHost-Wiki/.
Its hub repository is https://github.com/rk-gamemods/HumanHost-Wiki, with twelve
topic repositories. The original 193 content groups and five article issues are
reconciled for application 0.8.315, Steam build 25548639. The normal decompile
command generates, validates and publishes selected content and reuses unchanged
inputs. It does not invoke an LLM.

[ACCEPTANCE.md](ACCEPTANCE.md) is the closed requirement-to-code-and-evidence
checklist. [BASELINE_INVENTORY.md](BASELINE_INVENTORY.md) accounts for every
original exception. Later development notes do not add completion gates.
Historical checkpoints below retain their original results; their old "remaining"
statements are superseded by the checklist. Runtime verification may be unknown.
Optional mechanic explanations, guide authoring and additional infrastructure
experiments are not implied work. Any further investigation must name an actual
listed defect and result in a deterministic correction or check.

The distinct-real-build history requirement has fixture proof and an explicit
external-evidence limitation: available catalog captures cover one Steam build;
older local decompilations lack catalogs. Current data cannot reconstruct them.
Automatic capacity handling has forced-threshold real-Git fixture proof; the live
inventory fits default budgets, so live overflow was not artificially triggered.
Neither limitation is substituted with unrelated gameplay research.

## Current evidence

### Reader cache sharing checkpoint

On 2026-09-27, the normal wiki update shared 7,320 duplicate files across 16 local
reader candidates. Independent before/after hashing confirmed that all 9,650
existing files, including manifests, retained their paths and bytes. Unique-inode
file lengths fell from 748,756,204 to 113,969,356 bytes, a reduction of 634,786,848
bytes. These are logical file lengths per inode, not a free-disk-space measurement.

The compactor verified 746,673,073 payload bytes. With allocation tracing enabled,
it took 38.204 seconds and peaked at 34,009,824 traced Python allocation bytes.
An immediate cleanup repeat took 0.058 seconds, reused its completion receipt and
read zero payload bytes. The benchmark records its scope and complete metrics in
`.local/reader-retention-benchmark.json`; [RETENTION.md](RETENTION.md) owns the
storage and recovery contract.

The production pipeline result is
`f1f4b7855b328dab494753d7e29efee30acd2d9ec1eca73cade4cc44e2124113`.
It reused reader `60976dc8cc1a0e127488e8eb411d0c77eb640ecff99fd65a1728f04b82a22938`
and public release `e89be19a88ba2209581b9895133719aecb02628a3a8040a6243c7ba2ffc00022`.
Extraction, identity and authored-check source reads were zero; external article
requests and response bytes were zero. The subsequent normal decompile invocation
also succeeded with the same source capture and release. The 193 game-content
exception groups and five article issues were still unresolved in that run.
Their reconciliation is now part of the initial-delivery work authorized above.

The subsequent unchanged-update check passed in 10.457 seconds, preserving all
13 child HEADs and the hashes/timestamps of 1,080 checked files. Every stage reused
its result. This check ran while the isolated full test suite was also active;
its elapsed time is an observed run, not a controlled performance comparison.

The full Python suite passed all 268 tests in 622.629 seconds, including 12 direct
reader-retention cases and 14 pipeline cases. Coverage includes independent byte
conservation, receipt reuse, new candidates, corrupt files, unknown content,
interrupted replacement, protected operations, unsupported hard links, malformed
metadata, missing payloads, stale temporaries and Windows junctions. The repository
validator, map check, lock check and diff whitespace check passed. Test cleanup
retained protected Git fixtures without overriding their file protection.

### External article integration checkpoint

On 2026-09-27, the full Python suite passed 255 tests in 623.700 seconds.
The integration covers operator reporting, offline historical matching, provider
outages, observation-only reuse and capacity relocation. The shared source fixture
excludes production article settings; pipeline fixtures reject accidental live
article clients. This corrected a recovery-test failure caused by inherited settings.

Browser tests reproduced two delayed-response defects: article metadata held up
core content, and a late topic response appended links to a replacement search view.
The reader now displays core content first and appends optional links to their
own view. After the final view-ownership correction, all 37 affected browser,
reader, article integration and capacity projection tests passed. The larger suite
was not repeated for that final browser-only correction.

Implementation commit: `1af73b9ba0f077818e4bf89c3dc21c5c87914d33`.
The normal `tools/Decompile-GameCode.ps1` invocation completed in 229.894 seconds,
including installed-input hash verification and coordinated Pages publication.
It reused source commit `0bf00fe33781a7357b2d462fdaad49b0c3518b86` and published
release `e89be19a88ba2209581b9895133719aecb02628a3a8040a6243c7ba2ffc00022`
across all 13 repositories. The pipeline result is
`75175867182867b8ca1b00e1f86f831987efa8ebcf9d861a0ad9bd758da0df8b`.

The independent article projection audit checked 14 topic lookups and 5,748 eligible
entries across three captures of Steam build 25548639. Twelve entry links matched
populated destinations, representing four entries in each capture. The audit derives
matches from selected search records and the pinned observation. The independent
reader audit checked 24,438 observations with 219,948 assertions across 689 files
and 54,257,588 output bytes. The release audit checked 1,055 owned files,
57,788,850 owned bytes and 169 retained historical configurations.

The public browser checks verified Stone Axe facts and its revision-313 article
link, selected a historical capture without losing the link or its version context,
and confirmed that Construction's missing article and Vehicles' unsupported article
leave their catalog navigation available. No gameplay compatibility was claimed.

An immediate `tools/benchmark_release.py` run passed in 9.896 seconds, retaining
all 13 child HEADs and the bytes/timestamps of 1,080 files. Article requests and
response bytes were zero; extraction, identity and authored-check source reads
were also zero. This repeat measures the wiki update, excluding the decompile
entrypoint's installed-file hash scan. These are single-run timing observations.

Production article observation
`00b9b61998c9e154e33fc41377938872f0884673a85c9bd0c23c92a1c1e27ef5`
recorded 17 populated and five unavailable selected articles. The latter use
unsupported markup: Combat Perks, Craft Perks, Survival Perks, Game Structure and
Vehicle Building. They remain logged for user direction, along with the unchanged
193 game-content groups covering 27,087 occurrences. This work did not investigate
or classify those exceptions. Local acceptance logs use `.local/external-integration-*`;
the article-match audit is `.local/external-projection-audit.json`.

### External article adapter checkpoint

On 2026-09-27, 21 focused tests passed. The live acceptance fixture enumerated
64 community-wiki pages and checked 21 selected articles: 15 populated, two with
no recognized article body and four unavailable under the content rule.
The four unavailable pages were recorded for later review, not classified by an
LLM. The pending game-content exception queue was not processed.

The reviewed collection took 1.1060 seconds and transferred 78,310 bytes in four
requests. Its saved observation was 11,139 bytes. Peak Python allocation measured
by `tracemalloc` was 349,883 bytes; this is not whole-process resident memory.
The immediate repeat took 0.0007 seconds, made no requests and preserved the
pointer bytes/timestamp. After a test-only one-second expiry, one 15,492-byte
inventory request reused all 21 article checks. A separate 6,158-byte request
independently verified the IDs, byte lengths and content hashes of three pinned
revisions. These are single-run measurements, not statistical benchmarks.

Reproduce with `py -3 tools/check_external_links.py --online --root <isolated-directory>`.
Evidence is in `.local/external-link-acceptance-reviewed/acceptance.json`;
the initial observation is
`b57c5a3620319912672caff7fd31b128b9683032a7d451ea99a4093f495a7fa7`.
This adapter checkpoint alone does not prove pipeline publication or browser
integration. Those require the separate integration evidence below.

### Initial item/loot checkpoint (historical)

The following evidence predates coordinated releases and public repositories.

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
It was initially local and unpublished. All 193 unresolved content groups remained reported;
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
Steam build; they do not satisfy the real cross-build acceptance gate. At this
checkpoint, public deployment, automatic capacity allocation and staging retention
were unfinished. The following checkpoint records the public deployment.

### Initial public publication checkpoint

The configured public hub and twelve topic repositories now serve release
`120d76c6a29e1ed5b1f2153ba2ba1c81c956c9b8f024237f40e618de94eac59f` at
[Human Host Wiki](https://rk-gamemods.github.io/HumanHost-Wiki/).
The integrated update completed successfully with 193 unresolved content groups
(27,087 occurrences). The final report retains those exceptions for operator
review. Publication receipts pin each repository identity, main/Pages commit and
expected public file hash. The hub's live Pages API reports `built` for
`c7f12047e7db09ee035f6c26f86908f56207eb24`.

Publication prepares Pages trees from existing Git objects, uses four concurrent
topic workers, validates new/changed public bytes and promotes the hub last.
Unchanged immutable packs reuse prior validation. Compensating commits restore
the previous hub after failed verification without rewriting history. A direct
topic landing page follows the hub's coordinated release. Before initial hub
promotion, the browser showed the explicit unavailable state; after promotion,
the same topic loaded successfully.

The full suite passed 125 tests in 166.397 seconds. Publication tests include
independent completion after a topic failure, lost push responses, changed remote
refs, first-release fallback, restoration of a previous hub and retry. HTTP tests
check streamed hashes and oversized-response rejection. The test host uses real
Git objects; live rollback was not deliberately induced. A Windows path-length
failure in the test host's `git show` read was fixed by using `git cat-file blob`;
no operating-system setting or production protection was changed.

`tools/check_release.py` independently verified 680 owned files totaling
46,905,701 bytes (44.7 MiB), 589 candidate files and 26 retained release
configurations across all 13 repositories. `tools/benchmark_release.py` then ran
the unchanged published update in 8.022 seconds. All 13 child commits and 701
checked file hashes/timestamps stayed unchanged; extraction and identity read
zero source bytes. This measurement includes remote identity/ref and small public
pointer checks, excludes parent capture, and is not a performance guarantee.

Public browser checks covered Crude Axe search, its entity route through Pages'
custom 404 handler, a relationship into the crafting repository, an earlier
capture selection and navigation back to the hub. Snapshot and release parameters
were preserved. The two captures are revisions of Steam build 25548639, not two
distinct game builds. Gameplay verification, automatic capacity allocation,
staging retention and the other remaining gates still require implementation.

Publication observation was then hardened: reads pin an observed build, consult
the build inventory when the latest record belongs to another commit and report
unobservable outcomes separately from terminal failures. Observation failures
preserve the pending commit for retry without a compensating hub push. All 19
publication tests passed; after adding a disappearing-build case, all 10 adapter
tests passed. All 11 pipeline tests also passed. A read-only live adapter check
confirmed the hub commit above was built. The normal update reused the public
release, and a subsequent repeat took 8.045 seconds with the same 13 commits and
701 checked files unchanged. The [publication guide](PUBLICATION.md) owns these
retry rules.

### Capacity allocator checkpoint

The pure allocator and committed-input inventory reader pass 15 focused tests.
The real inventory rehearsal for release
`120d76c6a29e1ed5b1f2153ba2ba1c81c956c9b8f024237f40e618de94eac59f`
covered 452 immutable objects totaling 42,829,633 bytes across 13 logical topics.
Current placement and replay allocated no repositories. Forced 2 MiB site budgets
planned 16 additional partitions. This read-only rehearsal took 1.894 seconds with
1,647,383 bytes of traced Python peak memory; native Git memory is excluded.

Tests include history overflow, sealed partitions, input ordering, blob reuse,
name collisions, immutable conflicts and invalid measurements. A real Git fixture
independently checks reachable object sizes, including deleted content and exclusion
of unrelated branches. The [capacity contract](CAPACITY.md) identifies the remaining
projection, rollover, final-size verification and publication work. No automatic
capacity integration or remote partition creation is claimed by this checkpoint.

The reference projection now uses the same snapshot/configuration transforms as
the normal release writer. The expanded capacity suite passes 24 tests, including
two-snapshot placement, a second release with retained URLs, replay without payload
reads, namespace mismatches and changed dependencies. All 8 existing release tests
passed in 36.865 seconds after that shared transformation change.
All 11 pipeline tests also passed in 41.366 seconds, including independent supported
updates with content exceptions and unchanged-run reuse.

`tools/check_capacity_projection.py` independently checked the current candidate's
439 immutable objects and 26 snapshot indexes. Its 604 pack references retained
their logical ownership and bytes; forced 2 MiB sites relocated 370 references into
16 additional planned partitions. Replay yielded zero writes. The diagnostic took
4.095 seconds with 5,818,254 bytes of traced Python peak memory, excluding native
Git memory. It created no physical repositories or public changes. Journaled writes,
final prepared Git measurements, bounded control metadata and entrypoint rollover
remain required before the normal update can use these plans automatically.

### Integrated storage capacity checkpoint

The normal release stage now allocates immutable objects, prepares overflow Git
repositories, measures final source/Pages history and records physical ownership in
the release manifest and checkout lock. A durable journal precedes installation.
Publication verifies storage dependencies before topic entrypoints and the hub.
The loader follows hashed release-configuration references, and the preview preserves
immutable JSON bytes while resolving public URLs locally.

The full suite passed 164 tests in 250.413 seconds. Five forced-capacity integration
cases exercise real Git commits with a deterministic publication host: automatic
allocation and replay, interrupted installation, storage publication failure,
historical release retention, and final-size rejection before promotion. The actual
JavaScript loader passed six scenarios through Node.js, including byte/identity
mismatches, namespace containment and local preview. Pending older publication can
complete before a newer release; its updated Pages parent is remeasured before push.
The independent checker also accepted all 680 files and 26 historical configurations
of the previous real public release.

The integrated code at `efff6fc` then completed a normal live update for
`build-25548639-a7d9406a5bfb`. All thirteen sites published
[release d0d20c96](../releases/d0d20c96aa6c66a8b5c7e87f9027fb8ef4a448dd635a544ca2d759c083557b80.json);
the [publication receipt](../publications/d0d20c96aa6c66a8b5c7e87f9027fb8ef4a448dd635a544ca2d759c083557b80.json)
records the verified commits and HTTP checks. The real inventory fits the default
budgets, so this run required no additional physical repository.
`py -3 tools/check_release.py` passed for 706 owned files (47,197,419 bytes),
589 candidate files and 39 retained historical configurations. These configurations
span three wiki releases; they are not 39 game builds.

`py -3 tools/benchmark_release.py` completed the unchanged update in 8.349 seconds.
All thirteen child commits and 727 checked files retained their bytes and timestamps.
Normalization, identity, projection, release and publication reused completed results.
Normalization and identity each reported zero selected source bytes read. The local benchmark receipt is
`.local/capacity-live-repeat.json`. Live browser checks confirmed search for Crude Axe,
its Items-to-Crafting relationship, and selection of the earlier capture while
preserving the coordinated release in navigation. Both captures use Steam build
25548639; this does not prove real cross-build continuity. The operator report still
lists 193 unresolved content groups. No exception investigation or classification
was performed as part of this release verification.

These checks do not prove live GitHub overflow provisioning or complete capacity
management. Full logical-entrypoint rollover, oversized control-index splitting,
staging retention and the other ADR completion gates remain open. The owning
[capacity contract](CAPACITY.md) distinguishes the implemented path from those gaps.

### Snapshot directory splitting checkpoint

Oversized snapshot pack-reference lists now split into immutable directory pages.
The reader follows matching ranges for entries and backlinks and traverses search
directories sequentially. Small indexes retain their bytes. Capture catalog paging
is described below; ownership-manifest splitting, entrypoint rollover and indivisible
snapshot metadata remain unfinished cases in [CAPACITY.md](CAPACITY.md).

The forced projection test generates 160 entries with 1,024-byte data packs through
the production reader. It projects the resulting oversized index under a 20,000-byte
file limit, follows every allocated reference independently and checks replay plus
a later release without modifying historical bytes. The actual JavaScript reader
loads an entry and its semantic record in fewer than ten fetches and enumerates all
160 search records from the materialized physical sites. These are local fixtures,
not live GitHub overflow evidence. Separate checks cover multilevel directories,
overlapping ranges, changed bytes, invalid summaries, unavailable files and namespace
escapes. A regression test demonstrated and fixed cached JSON bypassing a different
reference's expected hash. New candidates declare the required runtime capability;
older candidates are refused if projection would require unsupported directories.

The full suite passed 170 tests in 255.358 seconds; its local log is
`.local/shard-index-tests.log`. The updated independent release checker also passed
against the existing real release `d0d20c96`, including all 706 owned files and 39
historical configurations. These checks establish compatibility with the retained
flat format as well as the forced directory fixture.

The normal update from `cb25c5c` published
[release 19db4c5f](../releases/19db4c5ffab35fc9323b2ebf8504f80fbcd1484df24a991bcf00aa2ae7960709.json)
on all thirteen sites. Its independent audit passed for 732 owned files
(47,491,035 bytes), 589 candidate files and 52 retained configurations across four
wiki releases. The real snapshot indexes fit the default budget, so this publication
checks runtime compatibility, not forced live splitting. Browser checks exercised
Crude Axe search, entry loading and all three reverse references. The unchanged
`tools/benchmark_release.py` run took 8.341 seconds and preserved all thirteen child
commits and 753 checked files, including timestamps. The local receipt is
`.local/shard-index-live-repeat.json`. The run still reports 193 unresolved content
groups; no exception investigation was part of this work.

### Capture catalog paging checkpoint

Release configurations now page large capture lists, retaining an inline default
and separate indexes for exact snapshot selection and chronological browsing.
The threshold and ownership contracts are in [CAPACITY.md](CAPACITY.md).
The production JavaScript reader loads older choices in batches of 50 and retries
a failed batch without advancing its cursor. Earlier flat releases remain readable.

An 80-capture fixture across three topics passed independent reference/byte checks
and production JavaScript selection and browsing against materialized physical files.
Appending capture 81 preserved historical files and reused earlier objects. A
60-capture fixture also passed real Git release, deterministic host publication and
unchanged-commit replay. These are synthetic captures, not additional real game builds
or live GitHub overflow evidence. The forced file budget is now 24,000 bytes to fit
the expanded runtime; repository rollover and oversized-index splitting remain
asserted by the tests. Indivisible control metadata and entrypoint growth remain
unfinished cases. Ownership paging is covered by the later checkpoint below.

A rendered local preview with 80 synthetic captures across eight physical sites
loaded all version choices in two batches, selected build 1003, searched and opened
its entry, and followed an entry-history link back to build 1079 while retaining
the same release identity. The local fixture builder is
`.local/build_capture_preview.py`; its output is not published game content.

The full suite passed 176 tests in 294.408 seconds; its local log is
`.local/capture-catalog-tests.log`. The independent release audit also passed
against the retained real release `19db4c5f`, covering 732 owned files and
52 historical configurations. Protected synthetic Git fixtures were retained
by ordinary test cleanup rather than having their file protections changed.

The normal update from `7c61782` published
[release ababd1f9](../releases/ababd1f9054c631ececa6977cd73300a20380c4a4a21af8c3d586412de05b54c.json)
across all thirteen sites. Its independent audit passed for 758 owned files
(47,846,817 bytes), 589 candidate files and 65 retained configurations across five
wiki releases. The real two-capture configuration remains flat, so live publication
establishes compatibility, not live overflow. Browser checks searched for Crude Axe,
opened its entry, selected the earlier capture and returned through its history link
while retaining the new release identity. Both captures belong to Steam build
25548639; they do not establish cross-build acceptance.

The unchanged `tools/benchmark_release.py` run passed in 8.330 seconds and preserved
all thirteen child commits and 779 checked files, including timestamps. Its receipt
is `.local/capture-catalog-live-repeat.json`. Normalize and identity reused their
results with zero selected-source bytes read; project, release and publish also
reused their results. This is not a claim of zero total I/O. The final
`.local/capture-catalog-operator-report.txt` lists 193 unchanged exception groups
(27,087 occurrences), with no execution failure or exception investigation.

### Ownership paging checkpoint

Large generated-file ownership receipts now use bounded hashed pages and directory
indexes. Small receipts retain their prior bytes. Allocation inventory, publication
and release validation use the same versioned codec; the independent audit expands
receipts separately and checks their files against Git objects. The format and
recovery contract are in [RELEASE.md](RELEASE.md#output-ownership-and-storage).

Focused tests passed for flat-to-paged migration, multiple directory levels,
allocation membership, exact repeat bytes, missing/modified pages, and malformed
receipts. A real Git transaction interrupted immediately after removing an obsolete
metadata page resumed to its prepared commit. Unknown and modified metadata were
preserved and rejected. Earlier receipts remained readable at their pinned commits
using one batch Git process, while metadata stayed outside Pages output.

The seven capacity-release integration tests passed in 108.127 seconds, including
two coordinated releases with paged ownership, deterministic host publication,
retained historical site files, independent audits and unchanged-commit replay.
The ownership page limit in that fixture was 2,048 bytes; the separate physical
file budget remained 24,000 bytes. These tests do not establish live GitHub
overflow or entrypoint rollover. Protected synthetic Git fixtures were retained
by ordinary cleanup without changing their protections.

The full suite passed 184 tests in 322.008 seconds; its local log is
`.local/ownership-tests.log`. Project validation, generated-map validation,
checkout-lock validation and `git diff --check` also passed. The independent
checker passed against the previous real release `ababd1f9`, including 758 owned
files, 589 candidate files and 65 retained configurations. Its ownership receipts
were flat, so that audit proves compatibility rather than live paging.

The normal update from `4fe97ca` published
[release 84499e31](../releases/84499e31b869a9e02cc30b44093a3c3bd251bee884a5ec78758922586cb31ddb.json)
across all thirteen sites. Its independent audit passed for 771 owned files
(47,912,621 bytes), 589 candidate files and 78 retained configurations across six
wiki releases. Real receipts still fit below the paging threshold. The reader
candidate was reused, so this change did not replace its browser runtime.

The unchanged `tools/benchmark_release.py` run passed in 8.200 seconds, preserving
all thirteen child commits and 792 checked files, including timestamps. Its receipt
is `.local/ownership-live-repeat.json`. Normalize and identity reused their results
with zero selected-source bytes read; project, release and publish also reused
their results. This does not measure zero total I/O. The final
`.local/ownership-operator-report.txt` lists 193 unchanged exception groups
(27,087 occurrences), with no execution failure or exception investigation.
The two captured inputs still belong to Steam build 25548639; cross-build
acceptance, current-game freshness and complete gameplay verification remain open.

### Entrypoint rollover checkpoint

Topic and hub fronts now roll into further physical repositories when their
prepared site or Git history would consume reserved headroom. Stable logical
URLs retain historical files and a successor record. The active front map is
recorded in the release; new fronts verify before their predecessors select them.
The owning contracts are [CAPACITY.md](CAPACITY.md) and
[PUBLICATION.md](PUBLICATION.md). Preparation is owned by `release_prepare.py`;
pure front selection and publication ordering are owned by `entrypoints.py`.

The focused suite passed three tests in 65.980 seconds. It used measured real Git
histories to force all three fixture topics through two rollovers over four
releases. It verified interrupted installation, exact commit recovery, retained
historical configurations, publication failure, hub rollback at both the original
and replacement repository, and frozen retired fronts. A separate pure test
verified that successor naming skips another configured topic's identity. The host
adapter performs real local Git operations without contacting GitHub.

Fifteen production-loader scenarios passed in Node.js, including historical
selection, successor cycles and namespace checks, current hub coordination and
direct visits to a replacement front. A rendered local synthetic preview also
passed canonical hub/topic navigation, group and entry links, direct replacement
entry access and a pre-rollover historical release/snapshot URL. The preview
builder is `.local/entrypoint_preview.py`; these fixtures are not public game data.
The browser check found and fixed a preview-server trailing-slash bug. Its focused
HTTP test also verifies missing-group HTML fallback and unchanged JSON bytes.

The final broad run passed 188 tests in 504.453 seconds, including the preview
HTTP regression. Its log is `.local/entrypoint-final-tests.log`. Registry validation,
the generated map, all thirteen child locks and the staged whitespace check passed.
An intermediate broad run passed 186 tests in 472.198 seconds. Before that, a
storage-failure test selected the first created repository, which can now be an
entrypoint. Its selector was corrected to choose a storage role, and the focused
test passed. Protected synthetic Git fixtures remain retained without overriding
file protections. The live repositories have not exercised capacity rollover yet.

Implementation commit `0d893ca` completed the normal operator update and published
release `bd8693d245c439e4bc52d164e562f767abd167662155d4f404e04f430b6f39e7`
to all thirteen existing sites. The independent release audit checked 797 owned
files (48,307,247 bytes), 589 candidate files and 91 historical configurations.
The unchanged update then passed in 8.485 seconds with all thirteen child commits
and 818 observed files' hashes and modification times unchanged. Normalize and
identity reused their results with zero selected-source bytes read; this does not
mean zero filesystem I/O. The operator report retained 193 exception groups and
27,087 occurrences without an execution failure. No exception was resolved in
this checkpoint. Evidence is in `.local/entrypoint-operator-report.txt`,
`.local/entrypoint-release-audit.json` and `.local/entrypoint-live-repeat.json`.
The published browser check passed hub-to-item navigation, search for `Crude Axe`,
entry facts and selection of the older `8f1263c7d28f` capture while retaining the
release ID. It does not establish gameplay correctness or distinct-build coverage.

The retained decompilations for builds 25448142 (`7550530`) and 25407931 (`3c01f7f`)
have no `Catalog` tree, checked with `git ls-tree <revision> Catalog BUILD_INFO.md`
in the local source repository. They do not satisfy the two-build catalog acceptance
gate. Current wiki captures still cover one game build and an extractor correction.

### Steam availability checkpoint

The normal operator update now observes the captured Steam branch through an
isolated anonymous SteamCMD client, caches successful checks and records unavailable
checks separately from content exceptions. Each reader release pins the observation
and its UTC check time. A matching build does not grant gameplay verification.
[AVAILABILITY.md](AVAILABILITY.md) owns the provider, setup and recovery contract.

An availability-only change skips model projection and hard-links validated
immutable reader packs into the new candidate. Its test rejects a second model
projection, verifies shared files and unchanged snapshot versions, then checks a
stable repeat. Failed remote checks still permit supported pipeline work. The
provider bounds response bytes while reading and tokenizes by position without
copying the remainder for each field.

The broad run passed 197 tests in 514.184 seconds; its log is
`.local/availability-full-tests.log`. After the parser copy optimization, all nine
focused availability tests passed in 1.373 seconds, including a response with
10,000 irrelevant metadata fields. The Node.js capture/availability checks passed.
The final no-op measurement now includes the observation and its pointer in the
hash/mtime comparison. Registry validation, the generated map, all thirteen child
locks and whitespace validation passed before the live update. Protected synthetic
fixtures remain retained without overriding their file protections.

Implementation commit `8145ba9` completed the normal operator update and published
release `242d80ac4dde930da38365b9eec1a67e165ef19b646afe0fe8166838ba606ca5`
to all thirteen sites. The provider observed public build `25548639` at
`2026-09-27T09:26:55+00:00`, matching the captured build. Immutable observation
`446c285e4bb26fa3e022cbb096fd7009b5498c9bd433374737be60c47484fb41`
records its source and hashes. The release audit independently checked 823 owned
files (48,697,973 bytes), 589 candidate files and 104 historical configurations.
The cached unchanged update passed in 8.703 seconds with all thirteen child commits
and 846 observed files' hashes and modification times unchanged. Normalize and
identity reused results with zero selected-source bytes read. This is not a claim
of zero filesystem I/O. Evidence is in `.local/availability-operator-report.txt`,
`.local/availability-release-audit.json` and `.local/availability-live-repeat.json`.

The published browser check verified the observation time and matching-build text,
the explicit absence of gameplay verification, hub-to-item navigation, `Crude Axe`
search and entry facts, and selection of the older `8f1263c7d28f` capture while
retaining the release ID. Both real captures belong to the same Steam build;
different-build wording is fixture-tested. The operator report retains 193
exception groups and 27,087 occurrences. No exception was investigated or resolved
in this checkpoint. Display-version capture and dependency-based gameplay
verification remain open.

### Captured application-version checkpoint

The source generator now selects `PlayerSettings.bundleVersion` into a small
`Catalog/game-version.json` record with source hash and object/field evidence.
Wiki registration validates that evidence against the pinned input inventory.
New reader captures expose the label alongside Steam build identity; older receipts
keep their original unknown state. [GAME_VERSION.md](GAME_VERSION.md) owns the
contract and extension points. Gameplay verification is unaffected.

Parent implementation `db7b5d6` produced source commit
`0bf00fe33781a7357b2d462fdaad49b0c3518b86` for Steam build `25548639`, recording
application version `0.8.315`. The capture changed only `BUILD_INFO.md`,
`Catalog/game-version.json` and `Catalog/generator.json`. The independent
`tools/check_game_version.py` audit checked the captured field, serialized-file
mapping, inventory entry and installed input hash. It imports neither the selector
nor the wiki registrar. Logs are `.local/game-version-capture.log` and
`.local/game-version-source-audit.json` in the parent workspace.

All 22 parent catalog tests passed in 2.820 seconds. The mod build passed with zero
warnings and errors. All 200 wiki tests passed in 544.289 seconds while the real
capture ran independently; the log is `.local/game-version-full-tests.log`.
The focused reader checks and production JavaScript checks also passed.
Registry validation, map, child locks and whitespace checks passed. Protected
synthetic fixtures remain retained without overriding file protections.

The normal parent command, `pwsh -NoProfile -File tools/Decompile-GameCode.ps1`,
verified unchanged installed inputs and reused the source commit, then completed
the wiki stages and published release
`748fc6c9de3b17187d77d4df69818b72939c03554225b9c3155929390db52411` across all
13 repositories. Its log is `.local/game-version-operator.log` in the parent
workspace. The independent release audit checked 960 owned files (56,680,248 bytes),
674 candidate files and 117 historical configurations; it does not certify gameplay.
The report is `.local/game-version-release-audit.json` in this repository.

The immediate unchanged wiki rerun took 8.765 seconds, preserving 983 tracked
output files and all 13 child HEADs. Normalization and identity reused their
results with zero selected-source bytes read; this is not a claim of zero
filesystem I/O. All subsequent stages reused their outputs. See
`.local/game-version-live-repeat.json` for measurements.

Live browser checks on 2026-09-27 confirmed the application version and source
evidence, topic navigation, search and the Crude Axe entry under the new capture.
Selecting `build-25548639-a7d9406a5bfb` retained the release query, loaded that
historical entry and showed its application version as unknown. Its facts and
relationships remained accessible. These captures share one Steam build and do
not satisfy the distinct-real-build acceptance requirement. The 193 unresolved
content groups (27,087 occurrences) remain pending user direction.

### Committed release-staging retention checkpoint

The normal update now removes committed duplicate release payloads after supported
publication work. [RETENTION.md](RETENTION.md) owns eligibility, conservation,
path checks and retry behavior. Completion markers avoid repeated Git reads and
payload scans. This housekeeping changes no public artifact contract or release ID.

The real update on 2026-09-27 completed in 19.412 seconds while the full test suite
ran independently. It removed 2,204 files containing 90,247,462 bytes from nine
completed staging directories. `.local/rs/` fell from 2,447 files and 92,172,547
bytes to 243 files and 1,925,085 bytes. The retained files are diagnostic journals
and Git preparation files. No cleanup issue was reported. The audit script and
result are `.local/retention_acceptance.py` and `.local/retention-live.json`.
It independently measured removed bytes, preserved all 13 child HEADs and 982
release/output files and timestamps, and compared the complete content exception
report with the previous run. Only the local pipeline result advanced to reflect
the new runner contract; public release `748fc6c9de3b17187d77d4df69818b72939c03554225b9c3155929390db52411`
remained selected. The 193 content groups remain pending user direction.

The immediate unchanged repeat took 9.495 seconds, preserved all 983 observed
files and 13 HEADs, and reused cleanup without removing files. Its evidence is
`.local/retention-live-repeat.json`. The independent release audit rechecked
960 owned files (56,680,248 bytes), 674 candidate files and 117 historical
configurations; see `.local/retention-release-audit.json`.

A separate cached-cleanup measurement took 0.0304 seconds and peaked at 745,738
bytes of Python allocations for the nine completed journals. This measures
neither initial cleanup nor whole-process working set. The reproducer is
`.local/retention_cached_cost.py`; `.local/retention-cached-cost.json` records the
measurement. The regression test also rejects any Git call on cached cleanup.

Seven focused retention tests passed in 2.274 seconds, including a real Windows
directory junction, a changed journal plus payload, absent Git objects, pending
transactions and retry after a simulated permission failure. The existing eleven
pipeline tests passed in 52.016 seconds; a new cleanup-report isolation check
passed separately in 1.330 seconds. All 208 tests then passed in 534.448 seconds
against the final implementation, with no skips; the log is
`.local/retention-full-tests.log`. Registry, map, checkout-lock and whitespace
checks passed. Parent and captured-source working trees remained clean.
Protected test fixtures remain retained without overriding permissions.

### Checked authored explanations checkpoint

`curation.py` and `curated_rules.py` check committed topic definitions against
selected typed facts and optional captured C# hashes. Definition revisions affect
pipeline request identity. A failed check logs a content exception, retains its
last successful text and leaves independent generated facts available. Results are
scoped to the declared checks and do not grant page gameplay verification.
The [authoring contract](CURATED.md) records schemas, owners and recovery.

The Crude Axe example was published in release
`777a627ba7ac1c13208f8db5b95783f3267edcff7a260cf35a884613219a928f`.
Its configured `MaxStack` value of 1 was independently compared with the captured
`Catalog/views/items.jsonl` Git blob at source commit
`0bf00fe33781a7357b2d462fdaad49b0c3518b86`. The browser showed the explanation for
the current capture and omitted it for an older capture, keeping gameplay
verification explicitly unperformed. Two older captures were checked for absence
of the newly authored explanation. All captures still represent Steam build
25548639; this does not close the two-game-build acceptance requirement.

Reproduce the example audit with `py -3 .local/curation_acceptance.py` and the
unchanged update with `py -3 tools/benchmark_release.py`. Evidence is retained in
`.local/curation-source-audit.json` and `.local/curation-repeat.json`. The first
published repeat took 9.988 seconds and preserved 13 child HEADs and 1,024 file
hashes/timestamps. Cached explanation checking took 0.0489 seconds with 43,508
peak Python-allocated bytes, excluding subprocess/whole-process memory, and read
zero model or code bytes. Historical checks also reuse unchanged snapshot inputs.

Independent `tools/check_reader.py` and `tools/check_release.py` audits passed
24,438 selected observations, 219,948 reader assertions and 143 retained release
configurations. The authored-file adoption and publication path gaps found by the
initial real runs were repaired and covered by regression tests. Unadopted child
commits, generated-file changes, private bytes and source-code paths remain
rejected. The 193 content exception groups / 27,087 occurrences are unchanged and
remain pending user direction. Dedicated guide pages/search, complete gameplay
verification and the other remaining completion gates are still open.

The complete suite passed 226 tests in 601.046 seconds with no skips, recorded in
`.local/curation-final-tests.log`. A subsequent one-line correction excludes
explanations from removed-entry search records while retaining their entry-page
history. Its regression failed before the correction; all 15 curated checks,
15 reader tests and the production JavaScript checks passed afterward
(`.local/curation-search-fix-tests.log`, `.local/curation-reader-final-tests.log`).
The earlier broad attempt exposed the 24,000-byte synthetic capacity limit being
smaller than the expanded 24,833-byte runtime; capacity cases now exercise 25,000
bytes and still prove index splitting and rollover. One earlier run also detected
an implementation edit during release preparation; the passing full run used
frozen implementation files. The failed-attempt log remains retained.

The final correction is included in implementation commit `da221dd` and published
release `7a3c1abc5752db31b2560fac7258e4b4ce5c9581eb634473097f1940995c69b9`.
The final unchanged repeat took 9.374 seconds, preserving all 13 child HEADs and
1,037 files. The source audit and browser check passed again; the Git-release
audit checked 156 retained configurations. Final receipts are
`.local/curation-final-repeat.json`, `.local/curation-final-source-audit.json`,
`.local/curation-final-reader-audit.json`, `.local/curation-final-release-audit.json`
and `.local/curation-final-publication.log`. The cached explanation check reused
the same receipt with zero model/code reads, 0.049 seconds and 43,457 peak
Python-allocated bytes. Protected synthetic Git fixtures remain retained.

### Initial exception reconciliation, first batch

The [reconciliation record](BASELINE_RECONCILIATION.md) documents reviewed source
evidence for 12 gameplay classes and 16 technical summary classes. Individual
GameObject identities selected through domain relationships resolve both original
relationship groups. Five external article checks now accept reviewed literal
formatting; all 22 selected articles are populated. The initial baseline is still
unfinished: 163 unsupported classes covering 22,143 occurrences remain in scope.

The normal decompile command completed pipeline
`6bfa2dbb943c3cf55d2fe0dab845e330df11d78d2d955a117ca33e14b26a7ab3`
and published release
`c8cab53303aa808a64cfca46153681d3f64993d9bc976c49730bf5815d185d8e`.
Source capture remained unchanged. The independent full source audit checked
12,222 selected gameplay records, 181,450 assertions, 527 type summaries and
2,063 referenced GameObjects. The reader audit checked 31,104 observations and
279,942 assertions across retained captures. The Git release audit verified 13
repositories, 1,682 owned files and 182 retained release configurations. These
checks prove selected facts and their projection, not complete gameplay coverage.

The full suite passed 277 tests in 654.844 seconds. A later identity regression
proves that reviewing a technical summary preserves its existing key; all 14
identity tests passed afterward. Evidence is retained in the
`.local/baseline-reconciliation-*` reports. The unchanged normal update took
12.282 seconds and preserved 13 child commits and 1,731 file hashes/timestamps.
Public browser checks verified
the selected release and the corrected Vehicle Building revision link.

An isolated extraction benchmark measured 6.041 seconds cold and 0.114 seconds
for the unchanged repeat. Cold identity processing took 2.594 seconds, with a
0.200-second repeat. Both repeats read zero source bytes and preserved output
bytes and pointers. Peak Python working set was 91,824,128 bytes, excluding the
Git subprocess. This single observation ran alongside publication and is not a
controlled comparison.

### Initial exception reconciliation, acquisition and bindings

The [review record](BASELINE_RECONCILIATION.md#acquisition-inventory-and-binding-review)
adds eight gameplay/configuration contracts and 30 exact technical classifications.
Merchant stock is projected into ten biome tables with source-indexed item links,
quantity ranges and price factors. Initial inventories, item-quality/upgrade arrays,
new-character options, item-model bindings and keyboard defaults are selected.
Unrelated UI, audio, notice text and save state remain excluded. Unknown nested
notification, tooltip and skybox fields still generate exceptions.

The normal decompile command completed pipeline
`cc27346e9fa9f5661a4d2383a7bcfb4e0826805414b6d317303350a2f72b55ff`
and published release
`012d87ffce67b8780f0f0bd6d5171861d8b867d66ad102ae87fc1becba65867a`.
The source capture is unchanged. The backlog is now 125 unsupported classes and
16,890 occurrences, with zero relationship exceptions and 22 populated article
checks. All remaining classes stay in scope for initial delivery.

The independent full source audit checked 16,643 gameplay/configuration records,
197,719 assertions, 2,139 referenced GameObjects and all 527 type summaries.
The identity audit checked 19,309 current observations and 230,349 assertions;
the reader audit checked 35,601 observations across captures and 320,415 assertions.
Its candidate contains 1,290 files and 115,662,605 bytes, with a largest pack of
518,915 bytes. These are selection and projection checks, not gameplay verification.

Focused tests passed: 3 acquisition, 14 component, 5 referenced-object, 4 model,
17 extraction and 15 reader cases. The acquisition fixture exercises malformed
stock entries, nested new fields and unresolved item links without losing valid
quantities or shifting later positions. A test expectation initially assumed the
relationship order; it now checks the predicate and exact source path. The full
source audit found and prompted correction of its older loot-table assumption.
Evidence is retained in `.local/baseline-acquisition-*`; protected synthetic Git
fixtures remain retained without overriding permissions.

The unchanged normal update passed in 12.943 seconds, preserving 13 child commits
and 2,258 file hashes/timestamps. The release audit verified 2,207 committed output
files, 164,401,021 owned bytes and 195 retained release configurations. Registry,
map, checkout-lock and whitespace checks passed.

The public browser check found all ten merchant stock tables. The Mountain Forest
table displayed the Bearing item link, quantity bounds 10 and 20, sampling value 1,
price factor 1 and three merchant prefab links in the selected release. No browser
console errors were reported.

### Initial exception reconciliation, combat and runtime state

The [review record](BASELINE_RECONCILIATION.md#combat-material-and-runtime-state-review)
adds nine selected configuration classes and 28 exact technical classifications.
Attack timing, handmade ammunition modifiers, scope FOV, terrain material tables,
slot restrictions and inventory-template context now have explicit contracts.
Fragment connectivity and rendering/audio state retain technical summaries.
The initial backlog is 88 classes and 7,735 occurrences, with zero relationship
exceptions; all remain authorized work before the first baseline is delivered.

Extraction `9bdf173a94f682861c51def84ccc5b29bf092b66c4916330eac14522a97b0128`
and identity `386697456b7e5da1b06ef40219c98253037b939cd92a4f910375a21d681734c6`
passed independent audits: 17,384 selected records and 205,786 source assertions;
20,050 current observations and 239,804 identity assertions. Reader candidate
`eab8fd04cdf9e5a4e3566e7a2d642e35a2ee06edaea5aa03a6ed818b12faf520`
passed 327,084 assertions over 36,342 retained observations. It contains 1,345 files,
119,489,985 bytes and a largest pack of 517,450 bytes.

Two combat tests verify exact default-time markers and continued extraction when
new nested fields appear. The source review also caught a mistaken assumption
that Weapon_Range's ScopeInfo was a reference; it is mounting geometry and remains
excluded. Scope settings are linked through their owning manager.

The normal decompile command completed pipeline
`483cf6447f6a9b3bd6bfa5ca589b8a065c41483e90c15c5f4e293e9a3b94889c`
and published release
`4c0e7085ed767ed79ddca5f8fa7727a0c87e3040e298393a6b163a7bf47ff93a`.
An unchanged wiki update passed in 12.677 seconds, preserving 13 child commits
and 2,739 file hashes/timestamps. The release audit verified 2,686 owned files,
223,163,210 bytes, 208 retained configurations and 28 ownership pages. Registry,
map, checkout-lock and whitespace checks passed.

The full 284-test run passed 283 cases and exposed a positional adapter lookup
in the recipe test. It now selects `UI/Craft_Items` by its stable class identity;
all 14 component tests passed afterward. No runtime fix was required for that
test failure. The public Axe_Combo_1 page displayed selected timing values,
the exact default-time marker and seven weapon references in the published
release, with no browser console errors. Evidence is retained in
`.local/baseline-combat-render-*`.

### Initial component backlog reconciliation checkpoint

All 191 initially unsupported classes now have explicit source-reviewed contracts.
The two initial relationship groups and five article issues were already resolved;
the complete selected-field pass now reports zero content exceptions. All 22
configured external articles are populated. This reconciles the original backlog
at the captured-field level, without declaring complete gameplay interpretation.
[Baseline reconciliation](BASELINE_RECONCILIATION.md) records the decisions and
the remaining source-defined mechanics.

The final class batch covers world/dungeon settings, streaming and composition,
vehicle/controller parameters, navigation, environment modules and reviewed
technical exclusions. Seventy-seven intermediate controller identities have
explicit same-capture supersessions; their original decisions remain intact.
Unresolved absent observations now reach the operator's exception report.

Scene-prop composition is aggregated by prefab index, with totals and unresolved
counts. Selected records fell from 129,010,537 to 45,108,743 bytes. The independent
source audit passed 365,969 assertions over 22,111 selected records, 2,725 prefab
identities and 527 technical type summaries. Identity audit passed 318,439 assertions
over 25,363 current observations. Reader candidate
`7c4321986c2e914a3b4344905c8a827b9b7ce2db16c5d390184be20f806a83ed`
passed 374,901 assertions over 41,655 retained observations; it contains 1,918 files,
151,683,613 bytes and a largest pack of 514,644 bytes.

The normal decompile command published release
`4ad92f64ed9390922318e102097e776e7a6a8d0880213a3ee6c46936be0b2bb5`
through pipeline `9b4d8ba2b881672c9f79410bda4b0640d61d295d0dc9bdb6aef2a4015b3cae88`
with zero unresolved content. The full 291-test suite passed in 702.039 seconds.
Subsequent composition/batch changes passed six configuration tests and 16 component
tests. Composition tests prove conservation, explicit invalid-index counts,
order-independent output and bounded evidence; batch tests prove byte/count bounds
and oversized-record isolation. Byte-bounded batching then published release
`42edecbf810d13ee478c1883f309cd6eed5781c31f07139bad0f47089572cb1f`
through pipeline `f6f39503174df3a023e7c284ce568bc9e4bb2a3162bfb30cbec34391309e4a2c`.
Its reader `f146eeca1bb43f5328b5f78d5449babb68a57086e4def82d8e6597f72596478f`
passed the same 374,901 assertions. Release audit verified all 13 repositories,
4,431 owned files, 409,756,545 owned bytes and 247 retained configurations.
An unchanged update passed in 15.512 seconds, preserving all 13 child commits
and 4,529 file hashes/timestamps. All stages reused prior results. Public SceneProps
and Z_Boss_01 pages showed the compact composition and corrected controller links
without console warnings or errors; this browser check used release `4ad92f64`,
whose selected payload is byte-identical to the batching-only successor.
Registry, map, checkout-lock and whitespace checks passed. Evidence is retained
in `.local/baseline-bounded-*` and `.local/baseline-composition-*`.

An isolated cold extraction took 19.574 seconds and peaked at 676,261,888 Python
working-set bytes including the subsequent identity stage. Limiting ordinary
component batches to 2 MiB/128 records preserved the exact selected-output hash
`f843aca7527f64766e85cd6d5cf98fee9da4a2548d930bd118d4148bec5c29dc`;
the next cold run took 13.620 seconds, but peak memory remained 676,065,280 bytes.
Unchanged extraction took 0.128 seconds with zero source reads; unchanged identity
took 0.202 seconds. These are measured runs, not a controlled latency comparison.

Targeted profiling located the peak in a single 43,408,929-byte
`Terrain_Loader_Manager` raw record. Its four excluded corner-fade arrays contain
many coordinate objects. Byte-bounded batching cannot fix a single decoded record.
Selective field reading remains required memory work; raw geometry stays local.
Diagnostic evidence is in `.local/baseline-memory-profile.jsonl`, and benchmark
results are in `.local/baseline-bounded-extraction-benchmark.json`.

### Large-record memory correction

The catalog writer now indexes every member of script records at least 1 MiB
in size. New source capture `1080b929da89375e2c09b6a80abc28f343e9d9a5`
changes only `Catalog/generator.json` and `Catalog/views/object-index.jsonl`.
All raw object shards and decompiled files remain byte-identical. An independent
audit checked all 142 indexed records and 2,128 fields against their complete raw
values. Member metadata totals 66,403 bytes for 261,714,133 raw record bytes.

The wiki verifies the complete record hash while decoding only declared fields.
Skipped values are read in chunks of at most 64 KiB; their names remain visible
to new-field detection. Tests cover malformed metadata, changes inside skipped
values, Unicode names, stale local files, immutable Git fallback and legacy indexes.
The Git fallback still buffers one encoded line, and legacy indexes still decode
complete records. Selected large values remain complete.

The cold extraction/identity benchmark peaked at 181,633,024 Python working-set
bytes, down from 676,065,280. This excludes the Git subprocess. Cold extraction
took 11.913 seconds; unchanged extraction took 0.175 seconds with zero source
reads. Cold identity took 4.624 seconds; its repeat took 0.200 seconds with zero
source reads. Publication and the independent checker were running concurrently,
so these latency samples are not a controlled comparison. The complete selected
output remains 45,108,743 bytes with SHA-256
`f843aca7527f64766e85cd6d5cf98fee9da4a2548d930bd118d4148bec5c29dc`.

All 23 catalog tests, 18 extraction tests, 16 component tests and four record-reader
tests passed. The parent solution built with zero warnings and errors. Independent
source and history audits passed 365,969 and 318,439 assertions. Reader candidate
`d4def90989e529d23a8f59dcaef8916d900d6ca80f8bdeca3fd07c41e11abf11`
passed 603,170 assertions across 67,018 retained observations. It contains 2,289
files totaling 181,071,520 bytes; the largest pack remains 514,644 bytes.
Evidence is in `.local/baseline-selective-*`. The parent normal-command log is
`../.local/baseline-selective-decompile.log`.

The normal command published release
`dbb5d525f6a7b033fef567b60c3844283ed3f7a21d31d5d147842072da3ae7d6`
through pipeline `00cb20428e5de8944e8a54eedfceb92882d1d8ecae431e4261d294b2ac6fb78a`.
It reports zero unresolved content groups and 22 populated external article checks.
The independent release audit verified all 13 repositories, 4,821 owned files,
439,339,142 owned bytes and 260 retained configurations. A second normal decompile
command completed in 53.760 seconds, preserved the source commit and all 13 public
child commits, and left 4,927 file hashes/timestamps unchanged. Installed-input
hashes, Steam identity and generator checks confirmed source capture reuse.
The live SceneProps page selected the new capture/release, displayed 4,887 total
placements and zero unresolved placements, and kept the previous substantive-change
date. No browser warnings or errors were recorded. Registry, map and checkout-lock
checks passed. This completes the measured large-record memory correction.

### Game 0.8.319 update checkpoint (2026-10-08)

Captured Steam build `25752290` as local source commit
`072c9ca90af0d9fe156df062db952d11cfd5b6d1`. Installed-byte version auditing
verified game `0.8.319`. The selected snapshot contains 27,283 current observations:
2 changed and 27,281 unchanged. It reports zero content exception groups and
22 populated external article checks. Catalog decoding reports no failures or
unresolved non-null references. Three unchanged, unshipped editor-only layouts
remain explicitly unsupported; this does not establish gameplay verification.

The repairs remain limited to checks and observed reader/retention defects. The
independent reader audit now accepts declared fonts and validates identity
supersessions, provenance, player-facing names and hub aggregates. Merchant owner
facts are checked against their pinned source fields without adding owner links
to stock records. Creature browse lists now show the 325 present entries and
preserve the 77 superseded entries in history. Long source keys wrap at a
390-pixel viewport. Local search/guide routing matches the published reader.
Capture timing accepts the structured game identity and skipped phases.

Retention validates 26 completed legacy stages against their immutable bindings
without adopting or deleting them. Independent repeat checks preserved all
702 legacy files and all 40,711 owned/metadata files across the 13 clean child
repositories, including their bytes, timestamps and file identities. The
unchanged full capture/wiki command completed in 111.81 seconds. One measured
legacy-stage validation fell from 12.354 to 0.287 seconds; this is a local sample,
not an overall throughput claim. The final cold wiki run spent 403.70 seconds
in reader retention and 265.89 seconds in projection, the next profiling targets.

The full local suite ran 990 tests with six expected skips and no failures.
The final reader style change passed its 87 affected tests and native browser review. A
precision-sensitive CI fixture was reproduced with a fractional virtual clock
origin and fixed with an exactly representable origin, preserving exact deadline
assertions; all 26 deadline tests passed locally. Catalog, capture timing and
Windows handoff tests passed, and the mod solution built without warnings or
errors. Independent source, history, reader and release audits passed.

Windows main CI also exposed a silent nonzero Git read in the independent
source checker. The exact fixture and its 32-test module passed locally.
Eighteen ordinary direct and nested Git-read cases passed without an observed
ownership race. Separate timeout and termination controls behaved distinctly.
The original process exit remains unidentified. The auditor now preserves
native Git exit codes. A real subprocess test proves that valid partial JSONL followed by a
silent exit 17 still fails and leaves no child behind; all 59 affected tests
passed. This diagnostic change leaves generation fingerprints and the selected
release unchanged.

Publication used merged commit `ad6dc39faefb36e925be38360322ccbaea62719c`
and successful exact-main push [CI run 37733674721](https://github.com/rk-gamemods/HumanHostWiki/actions/runs/37733674721).
Both platforms ran all 991 tests with no failed modules: Ubuntu had seven expected
skips and Windows had six. A fresh hash-bound rehearsal passed 26 simulated
pushes and 978 file checks, preserved GitHub state and promoted the hub last.
The separate publish completed in 399.93 seconds. Its
[immutable receipt](../publications/6207400cdf3a24ef64685d9319cc4471bbf1b314d8bbb3a0d5fb732fd8e3ec72.json)
selects release `6207400cdf3a24ef64685d9319cc4471bbf1b314d8bbb3a0d5fb732fd8e3ec72`
and records all 13 destinations as verified.

Fresh native browser checks covered all 13 public landings, topic counts, current
version/build and release selection. Browse/search controls, older capture
selection, cross-topic navigation and retired Creature replacement links passed.
The 390-pixel expanded source panel wrapped long identifiers and had matching
375-pixel client and scroll widths. No asset/data failures, unhandled site errors
or source-disassociation notices were observed. Successful static-host SPA
404 shells were classified separately. Native desktop captures retain a known
soft-text artifact; layout review used actual captures, DOM labels and public
hash verification. Original-size mobile source evidence was legible and unclipped.

Further profiling should measure reader-retention verification, projection
fingerprint reuse and Windows test scheduling while preserving full byte checks,
deterministic promotion, cleanup and platform coverage.

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
