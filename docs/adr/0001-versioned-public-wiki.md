# ADR-0001: Generated, versioned Human Host wiki

**Accepted 2026-09-26.** Architecture contract for `HumanHostWiki`.
Repository/category ownership and pipeline dependencies are defined in
[project.json](../../project.json); the [generated map](../REPOSITORIES.md)
shows their connections. Commands and recovery procedures belong in
[WORKFLOW.md](../WORKFLOW.md).

## 1. Outcome and scope

Build a public, English, free, ad-free GitHub Pages reference for players and
modders: game contents, mechanics, acquisition, technical identifiers and
relationships, with information for every captured game version.

- One hub provides topic navigation, curated guides and version selection;
  twelve topic repositories provide detail and links back to the hub.
- Cover all known assets and systems. Group related records into readable pages;
  page count does not follow source-file or Unity-object count.
- Read the existing `HumanHostCodebase` in place. Reuse the parent's
  `tools/Decompile-GameCode.ps1` for capture. Export useful text metadata, not
  graphical/audio payloads, raw source trees or duplicate analysis datasets.
- After initial setup, a non-LLM runner automatically detects updates, captures,
  parses, classifies, links, versions, validates, commits and publishes them.
  Routine updates require no operator commands, page edits or approval per release.
- Credit the studio and identify the site as an independent community resource.
  The in-game viewer remains deferred until the wiki is stable and maintainable.

## 2. Repository ownership

The parent ignores `HumanHostWiki/`; the umbrella ignores `repositories/`.
Children are independent Git repositories with `.wiki-repository.json` identities,
not submodules or subtrees. `workspace.lock.json` pins clean child commits and
checks registry/checkout drift. Registry GitHub names are intended names until
remotes exist.

| Owner | Responsibility |
| --- | --- |
| Existing decompiler | Game input inventory, decoding, local source/catalog snapshots and extraction coverage |
| Umbrella / `wikibuild/` | Shared contracts, generator, identity reconciliation, navigation, validation and release coordination |
| Hub | Curated guides, discovery, coverage, version selection and release pointers |
| Topic repositories | Canonical domain records, generated pages, authored explanations and revision objects |
| Technical reference | Asset identities, unclassified objects and extraction gaps |
| `.local/` | Rebuildable indexes, staging, previews and operational receipts |

Each entity has one canonical owner; other topics reference it. Domain entities
and underlying assets have separate identities and may relate many-to-many.
Existing category/schema rules automatically handle new records and supported
types. Content those rules cannot classify enters technical reference and an
exception report; only extending those rules requires maintainer work.
Topic generators consume pinned inputs and shared contracts, never another topic's
mutable checkout or a forked orchestrator. Semantic graph cycles/backlinks are
valid; build dependencies must be acyclic.

## 3. State boundaries

Keep three records distinct:

- `snapshots/`: small receipts identifying captured source inputs.
- `workspace.lock.json`: local child checkout baseline.
- `releases/`: immutable manifests for verified, coordinated wiki releases.

Registration or a navigation preview cannot establish gameplay verification.
The complete scope and implementation status are separate: the current foundation
supports registry validation, local repository setup/locking, input registration,
generated architecture maps and deterministic navigation previews.
The unattended runner, gameplay adapters, identity matching, historical browsing
and publishing remain planned. These manual foundation commands are diagnostic
entrypoints, not the intended maintenance workflow.

## 4. Data and provenance contracts

Pin source inputs by Steam app/branch/build/depot manifests and exact local
snapshot commit. Preserve source paths and SHA-256 hashes, extractor/decompiler
versions and code hashes, normalization schema and coverage. Extractor corrections
create separate capture revisions even when the game build is unchanged.

The current capture lacks a reliable game display-version label. Add evidence-backed
extraction; until available, use the exact Steam build with an explicit unknown
label. Public provenance uses game-relative paths and excludes machine/account
state. The registered receipts own baseline build details; do not duplicate them here.

| Record | Required fields/meaning |
| --- | --- |
| Entity | Wiki-owned stable key, kind, canonical topic owner |
| Observation | Entity, snapshot, build-scoped identifiers, English label, typed facts, evidence locators |
| Relationship | Predicate, source/target, snapshot, conditions and source-field evidence |
| Identity decision | Candidate observations, accepted mapping or unresolved state, evidence/confidence, rule/reviewer, revision |
| Page revision | Stable page key, semantic content hash, entity/edge dependencies, renderer version, source evidence |
| Verification | Page revision, checked build, dependency hashes, checks and result |
| Wiki release | Source snapshot, generator/contracts revision, exact child commits, route map, output hashes and validation receipts |

Expose game IDs, Addressables GUIDs, Unity object identities, asset paths,
assemblies, types, members and fields alongside relevant entries. Evidence locators
identify file/hash and object/field path or assembly/type/member. Include units,
conditions and reverse relationships. Preserve the distinction between extracted,
derived, runtime-verified and unresolved facts: serialized defaults may be
modified by code/settings, and loot weights require verified selection rules
before being presented as probabilities.

### Identity across builds

Scope game identifiers to their build and container; no GUID, path ID, name or
asset path is universally stable. Wiki entity keys remain independent of them.
Deterministic matching records evidence and handles renames, removals, reused IDs,
splits and merges. Ambiguous matches retain separate observations and an unresolved
link; they do not require a guessed mapping or block unrelated updates. Optional
mapping corrections create new releases and preserve earlier decisions.

### Version behavior

Every gameplay page exposes selected version/build and snapshot, last verified
build, last substantive change, history, provenance, evidence level and gaps.
Freshness compares verification against the latest known available build and
includes the availability observation's source/time. Unknown freshness stays unknown.

Keep `last changed` separate from `last verified`. Unchanged content can gain
verification for another build only after relevant data/code dependencies and
checks pass. Extraction or HTML build success alone cannot grant a current badge.
Historical links retain the selected snapshot across repositories, never silently
fall forward. Distinguish not-present, uncaptured and decoding-gap states.
Multi-version guides declare supported builds; project/navigation pages identify
the wiki revision rather than claiming gameplay verification.

## 5. Storage and presentation

Store deterministic text records, generated Markdown, curated prose and manifests
in ordinary Git. Stable filenames/order and bounded topic/family shards keep diffs
useful. GitHub navigation remains usable; Pages adds search, filters and version
selection. A built-in Wiki may present curated content, with one authoritative
source for each guide.

Immutable revisions use semantic content hashes; small snapshot manifests map
entity/page keys to revisions. Reuse unchanged revisions across builds. Historical
content must remain browser-accessible, not merely buried in Git history; tags
and commits provide a readable fallback.

The central route map resolves owning sites and
`/entry/<entity-key>/?snapshot=<snapshot-id>&release=<release-id>` links. Set actual
base URLs when deploying. Use hub/category indexes and on-demand topic search
shards. Build-time joins may use streaming files or an ignored, rebuildable SQLite
index; retain accepted facts and identity decisions outside that cache. The raw
reference index need not be published. Compression is optional; Git LFS and a
public graph/database server are not required.

The builder enforces configured file/site/history budgets automatically: split
oversized shards, reuse revisions and allocate further repositories/sites under
the configured namespace. It updates registry locks, indexes and routes together,
preserving historical links and coverage without deleting snapshots or rewriting
history. Physical partitions retain their logical topic owner. Full history
partitions remain readable while new writes roll into another partition.
Configure headroom below the checked platform limits (2026-09-26):
[100 MiB per Git file, warnings above 50 MiB](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)
and [1 GB per Pages site](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits).

## 6. Refresh, build and coordinated release

One scheduled local runner owns this sequence. It checks for stable installed
build/catalog changes, skips unchanged inputs and invokes capture automatically.
Latest available builds are checked separately; unavailable local inputs produce
a waiting/stale state and automatic retry, never a false current badge. Configure
input paths, credentials, namespace and budgets once; no LLM scheduler is required.

| Stage | Required result |
| --- | --- |
| Detect | Observe build/input changes, wait for stable inputs and resume eligible work from durable state |
| Capture | Existing decompiler produces a stable, validated local snapshot; reuse captures when inputs are unchanged |
| Register | Check input identity/schema and record provenance without claiming wiki verification |
| Normalize | Stream typed facts/edges, dependency hashes, new types and coverage gaps |
| Identity | Apply evidenced matches and reviewed mappings; retain ambiguity |
| Project | Classify with existing rules; generate pages, links and search; automatically partition outputs to capacity budgets |
| Verify | Validate schemas, identities, relationships, semantics, provenance, coverage, links, size and repeatability |
| Release | Commit changed child outputs; persist the immutable coordinated manifest |
| Publish | Deploy version-addressed topic content, verify every target, then promote the hub pointer |

### Invalidation

| Change | Recompute/check |
| --- | --- |
| Data or relevant code | Dependent facts, edges, pages and curated assertions |
| Added/removed input or new type | Classification and coverage |
| Extractor/schema/normalizer | Affected adapters/data, including same-game-build corrections |
| Identity mapping | References, routes, backlinks and history; preserve prior releases |
| Template/navigation | Affected views; do not label it a gameplay change |
| Latest available build | Freshness only, without granting verification |
| Curated prose | Claims and links, without blanket extraction |

Use conservative invalidation until complete dependencies are recorded. Identical
inputs must produce identical bytes and no new content commit. Automation invokes
commands and consumes exit codes/receipts. Duplicate or missed wakes resume from
durable state; human attention is for unsupported content/schema or unrecoverable
failures, not normal changes, successful releases or capacity growth.

### Failure and recovery

One OS-held lock excludes concurrent writers. Pin source commits before reads
and recheck before registration. Reject dirty/changed inputs, unsupported input contracts
and conflicting identities without promoting results. Require clean destination
checkouts; stage outside them, validate before promotion, preserve authored/unknown
files, enforce path ownership and never override file protection automatically.

Git repositories and Pages sites do not share an atomic transaction. Persist stage
identities, expected hashes, commits and completion receipts. Partial deployments
remain unadvertised until every pinned target is available; existing version URLs
remain accessible. Retry from receipts, reusing verified outputs or rebuilding
incomplete staging. Retry transient failures automatically; isolate unsupported
records with explicit gaps so independently valid content can proceed. A failed
whole-release integrity check preserves the previous release and reports the cause.
Failed deployment verification automatically restores the previous validated hub
pointer. Preserve child history and source observations; capacity handling retains
historical snapshots.

## 7. Curated content and external links

Separate optional authored prose from generated facts. Claims use generated values
and executable dependency checks. Updates refresh factual sections automatically;
failed checks mark only the affected explanation unverified with its last verified
build and reason. Maintaining core reference coverage must not require prose edits.

Official backlinks use scripted entity/topic matching and recorded checks:
populated, empty, missing or temporarily unavailable. Link only useful populated
article destinations; temporary external failure does not remove our information.
Feed these observations into the default offline, deterministic build as versioned
inputs rather than querying live websites during rendering.

## 8. Acceptance and delivery

Required proof before full publication:

- Account for every source object as a domain/technical entry, payload omission or
  documented gap; resolve edges within the selected snapshot or label them unresolved.
- Independently check real-source identifiers, values and references. Across at least
  two captured builds, demonstrate history/navigation, ID changes, unchanged content,
  additions/removals and ambiguity; use fixtures for cases unavailable in real builds.
- Distinguish game changes from extractor corrections. Verify no-op byte/Git stability,
  freshness claims, cross-repository links, search and curated assertions.
- Exercise interruption, partial publication, concurrent writers, modified output,
  retry and rollback; preserve the prior coordinated release without duplicates/loss.
- Demonstrate unattended updates through new assets in existing categories and
  forced capacity thresholds, including automatic splits/provisioning and intact
  historical links. No hand edits, operator commands, release approvals or LLM calls.
- Unknown content enters technical reference with an actionable exception while
  supported changes proceed; retries and missed/duplicate wakes require no intervention.

Delivery order: **foundation (implemented) -> unattended runner with item/loot slice
-> all registered topics -> historical reader -> coordinated Pages publication**.
The first slice does not reduce final coverage. Select streaming versus
SQLite from measured access patterns and choose the production renderer when building
the historical reader; the current HTML preview does not select that framework.

Multiple repositories bound topic history/clone/site size but require shared release
coordination. Revision reuse avoids copying each patch's entire corpus. Grouped pages
and generated indexes avoid one-page-per-object sprawl. Update this ADR, the registry
and corresponding tests together when changing these boundaries.
