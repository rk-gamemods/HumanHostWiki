# Implementation evidence

The [ADR](adr/0001-versioned-public-wiki.md) owns requirements. This file tracks
delivery evidence and unfinished work; an implemented stage does not prove the
complete product.

## Boundaries and performance

- The parent decompiler owns input stability, source/catalog capture and Git diff.
  The planned command integration invokes the wiki only after successful capture
  or verified reuse; that entrypoint integration is still unfinished.
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

- Integrate the decompile entrypoint, verified capture reuse, durable run receipts,
  separate failure reports and final unresolved-content report.
- Extract and independently validate every registered gameplay topic. Account for
  source objects locally without copying the whole index into wiki content.
- Complete individual asset identities, real cross-build identity coverage and
  dependency-based verification beyond the selected-observation identity stage.
- Complete historical capture coverage, reader presentation of interpreted units
  and conditions, authored-claim checks and useful external backlinks beyond the
  selected-fact reader. Add verified freshness inputs and page-check receipts.
- Coordinate child commits and immutable releases with interrupted-run recovery,
  writer exclusion, unknown-file protection and failure-before-promotion checks.
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
