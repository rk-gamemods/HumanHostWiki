# ADR-0001: A generated, versioned Human Host wiki across topic repositories

- **Status:** Accepted architecture; implementation is staged as specified below.
- **Decision date:** 2026-09-26.
- **Decision maker:** Project owner, through the wiki planning discussion.
- **Audience:** Maintainers, generator implementers and reviewers.
- **Scope:** Human Host Wiki and its repositories under the `rk-gamemods` organization.
- **Local owner:** This independent `HumanHostWiki` umbrella repository.
- **Executable registry:** [project.json](../../project.json).
- **Derived topology:** [repository and pipeline map](../REPOSITORIES.md).

## 1. Context and intended outcome

The project needs a searchable technical reference for players and modders:
what exists, how systems work, where things are acquired, which objects relate
to one another, and what was true in each captured game version. A request for
valid loot tags should be answerable from an already generated reference.
Routine questions should not trigger another extraction or ad hoc analysis copy.

The local `HumanHostCodebase` already contains decompiled managed assemblies,
input inventories, serialized metadata, resolved references and readable views.
It is maintained by `HumanHostMods/tools/Decompile-GameCode.ps1` in its own local
Git history. The wiki consumes this work in place. It does not need the large
graphical, audio or other bulk payloads that account for much of the installed
game's size. Names, identifiers, paths, types, fields and relationships are useful
even when the referenced media is absent.

The developer-recognized community wiki remains a useful external reference,
but it is not a sufficient source for this project. The owner supplied an image
of its Items page with no content. Our reference must provide its own coverage
and useful navigation. Backlinks can complement that coverage.

Manual prose maintenance across the entire game would consume excessive time
and LLM tokens. Extraction, indexing, comparisons, reference linking, tables and
routine refreshes therefore belong in deterministic code. Human judgment is
reserved for explaining mechanics, ambiguous identity changes and new schemas.

## 2. Accepted product decisions

1. Publish an independent community reference on GitHub Pages, backed by ordinary
   public Git repositories. The wiki is free, carries no advertising and has no
   monetization. English is the publishing language.
2. Use one starting hub containing a high-level subject overview, curated guides,
   release information and version navigation. Deeper links lead into topic
   repositories/sites. Readers should always have a clear route back to the hub.
3. Cover the full agreed factual and technical catalog. Size is an engineering
   constraint addressed through organization and reuse, not an arbitrary cutoff
   on how much useful information the wiki may contain.
4. Include identifiers and modding details alongside relevant entries: game IDs,
   Addressables GUIDs, Unity object identities, asset paths, declaring assemblies,
   classes, members, field values and related objects wherever available.
5. Apply provenance and history to every page and fact, not only identifiers.
   Readers can select any game snapshot that we captured and see its information.
6. Generate routine updates without LLM calls. Use tests and recorded evidence to
   maintain curated explanations and expose uncertainty.
7. Keep the in-game viewer/mod idea deferred until the GitHub Pages wiki is
   stable, tested and maintainable. It adds no current runtime or packaging
   requirements.

The category list and ownership live once in `project.json`, presented in the
generated repository map. The accepted division is one hub and twelve topics.
Examples of grouping belong within that structure: an item-family comparison,
a workbench's recipes, or a biome's resources. There is no requirement to create
one page per Unity object or per extracted file.

### Publication posture

The owner chose public publication after reviewing the EULA and developer
statements. The developer explicitly recommends inspecting code for modding and
recognizes a public community wiki. The reviewed EULA did not identify a factual
catalog size/completeness threshold. This ADR does not create such a threshold
or impose advance developer contact as a prerequisite.

The project will credit the studio, identify itself as an independent community
resource, link to official game pages, respect explicit applicable requirements
and communicate constructively about the game. Relevant populated pages on the
recognized wiki may receive automatic backlinks. Empty placeholders must not be
presented as useful article destinations. Link checks record reachability and
content status; a temporarily unavailable external site does not erase our facts.

The owner accepts the possibility of a future removal request and will respond
then. The operational response is to disable public Pages deployments and remove
or restrict repository access as appropriate. Changing repository visibility
alone must not be assumed to remove all public site content. Previously cloned
copies cannot be recalled. These are incident procedures, not advance permission
gates or reasons to reduce the agreed coverage.

## 3. Repository boundaries and ownership

```text
HumanHostMods/                  existing private tools and mod workspace
  HumanHostCodebase/            existing ignored local game snapshot repository
  HumanHostWiki/                new ignored, independent umbrella repository
    project.json               repository, ownership and dependency registry
    workspace.lock.json        exact local child commit baseline, not a release
    wikibuild/                 shared orchestration and validation
    docs/adr/                  accepted decisions and their successors
    snapshots/                 small receipts for local source snapshots
    releases/                  coordinated wiki release manifests, once verified
    repositories/              ignored independent hub/topic checkouts
      hub/
      <topic-id>/
    .local/                    ignored staging, preview outputs and local state
```

The parent workspace ignores this entire umbrella. The umbrella ignores child
checkouts. Each child has its own Git history and `.wiki-repository.json` identity.
The umbrella pins reviewed child commits in `workspace.lock.json`; its drift check
requires matching clean checkouts and the same registry.
An ordinary parent commit cannot accidentally swallow all of the children.
There are no submodules or subtrees. GitHub names in the registry are intended
names, not claims that remote repositories or Pages deployments exist.

| Owner | Authority and permitted dependencies |
| --- | --- |
| Existing decompiler | Installed game inputs to local source/catalog snapshots; retains extraction, decoding and source-inventory ownership |
| Umbrella | Contracts, registry, shared generator, tests, identity reconciliation, navigation, release coordination and build tooling |
| Hub | Curated guides, discovery, coverage, snapshot selection and coordinated release pointers |
| Topic repository | Its assigned canonical domain records, readable reference pages, topic-specific curated explanations and revision objects |
| Technical reference | Asset-level catalog and the visible fallback for unclassified objects, including documented extraction gaps |
| Local derived index | Rebuildable joins/search/graph calculations; never the only copy of accepted facts or identity decisions |

Topic code imports shared contracts through the umbrella's versioned generator
interface. It consumes pinned normalized inputs and the global identity/link map.
It must not read another topic's mutable working tree or maintain a private copy
of the orchestrator. Semantic links may be cyclic; build-stage dependencies may
not. The registry validator enforces single ownership and an acyclic stage graph.

Each domain entity has one canonical content owner. A weapon may appear in item,
loot, crafting, combat and biome views, but its item definition has one owner;
other views refer to that entity. Underlying Unity assets retain technical
identities and links to their domain entities. One game entity can span multiple
assets, and one asset can participate in several views. Unknown new types are
reported in technical reference until a topic adapter classifies them.

## 4. Data and provenance contracts

### Source snapshots

Pin an input by Steam app, branch, build and depot manifest identities, plus the
exact local snapshot commit. Preserve source file paths and SHA-256 hashes,
extractor/decompiler versions, extractor code hashes, normalization schema and
coverage report. A game build may have several extraction revisions after an
extractor correction; those revisions must not overwrite one another.

The foundation registers existing snapshots without copying their contents. The
current generator records Steam identities but not a reliable display version.
Its receipt therefore uses `game_version: null` and states the gap. Before public
gameplay publication, add an evidence-backed version-label extractor. If a
particular build genuinely lacks a display label, show its exact Steam build and
an explicit unknown label. Never substitute an old version from workspace notes.

Source commits identify complete inputs; per-record provenance identifies the
specific evidence. Public provenance uses game-relative paths, hashes and stable
identifiers. Machine paths, account details and transient logs are not public
provenance. Preserve the applicable EULA hash/date as part of future input
inventory provenance when the extractor supports it.

### Normalized entities, observations and edges

The implementation must distinguish these concepts:

| Record | Required meaning |
| --- | --- |
| Entity | Wiki-owned stable entity key, kind and canonical topic owner |
| Observation | Entity key plus source snapshot, build-scoped identifiers, English label, typed factual fields and evidence locators |
| Relationship | Predicate, source and target entity/observation, source field/evidence, snapshot and conditions |
| Identity decision | Candidate observations, accepted mapping or unresolved state, evidence, rule/reviewer and revision |
| Page revision | Page key, semantic content hash, entity/edge dependencies, renderer version and source snapshot evidence |
| Verification | Page revision, build checked, input dependencies/hashes, checks performed and result |
| Wiki release | Source snapshot, generator/contracts revision, exact child commits, route map and successful validation receipts |

Evidence locators include source file, hash and object ID/field path or assembly,
type and member. Values need units and conditions where relevant. Relationships
include useful reverse links such as item-to-source, ingredient-to-recipe and
creature-to-biome. The large raw reference index is a local input to these views;
it need not be committed wholesale to the wiki.

An observed serialized default is not automatically the active runtime value.
Gameplay explanations must account for code paths, overrides, difficulty/world
settings and conditions when they affect the answer. Loot weights are not labeled
as final probabilities without verifying selection rules. Record evidence as
extracted, derived, runtime-verified, or unresolved; a successful parser does not
prove behavioral interpretation. These checks belong in reusable adapters/tests.

### Identity across builds

Wiki entity keys must not be derived solely from a game GUID or Unity path ID.
Identifiers are scoped to the captured build and source container. Names, paths,
types, fields and neighboring relationships can contribute to matching, but
none is assumed universally immutable.

Deterministic matching emits evidence and confidence. Ambiguous matches remain
unresolved until a reviewed mapping is added. Preserve renames, removals, reused
IDs, splits and merges explicitly. An asset retaining a GUID does not prove
unchanged semantics; an asset changing a GUID does not prove it is a new entity.
Mapping corrections create a new wiki release and retain the earlier record.

### Page-wide version experience

Every gameplay page shows:

- Selected game version/build and source snapshot.
- Last build for which its contents were verified.
- Whether that verification matches the latest known available game build,
  with the time/source of the availability observation.
- Last substantive change and the game version/build associated with it.
- Change history, provenance links, evidence level and known coverage gaps.

`Last changed` and `last verified` are separate fields. If all relevant inputs
and checks remain valid, an unchanged page receives verification for a newer
build without changing its factual content. Page dependencies include code as
well as serialized data when behavior depends on both. A new build's existence,
a successful extraction, or a successful HTML build alone cannot mark pages current.

Historical links preserve the selected snapshot across repositories. A missing
historical observation produces a clear unavailable/not-yet-present result;
navigation never silently falls forward to current data. Distinguish an entity
not present in that build from a build we did not capture or a decoding gap.

Curated multi-version guides declare the supported builds and claim-level
dependencies. General project/navigation pages identify themselves as project
documentation with a wiki release revision; they do not claim a game build
validated explanatory content that they do not contain.

## 5. Git storage, indexing and presentation

Use Git for small deterministic text records, generated Markdown, curated prose,
contracts and release manifests. Readers can navigate meaningful pages and links
on GitHub itself. GitHub Pages provides the unified browsing experience with
search, filters, version selection and consistent shared navigation.

Store normalized facts in bounded topic/family shards with stable ordering and
filenames. A canonical semantic content hash identifies an immutable revision.
Per-snapshot manifests map stable page/entity keys to revisions. Unchanged
revisions can be reused across many builds. Keep revision objects needed by
published historical snapshots reachable in the built site or its deliberately
versioned historical hosting arrangement; Git history alone is not a browser API.

Generated Markdown presents current reference views and bounded histories.
Historical Git tags/commits remain a readable fallback. The Pages renderer uses
the selected release/snapshot to resolve the proper revision and outgoing links.
An initial route contract is `/entry/<entity-key>/?snapshot=<snapshot-id>&release=<release-id>`
within each topic site. The central route map supplies the owning site; templates
must not hand-build cross-repository URLs. Concrete deployment base URLs are set
only when the target repositories/sites actually exist.

The hub has a small category index, and each topic has its own indexes. Search
uses topic shards loaded as needed rather than downloading the entire corpus.
Build-time joins and reverse references can use an ignored local SQLite index or
streaming files. No public graph database, server or LLM service is required.
Compression is an optional transfer/storage optimization, not a substitute for
readable Git history or sensible partitioning. Git LFS is not the primary wiki
storage model.

Track both working-tree and compressed Git-history sizes. Splitting topics reduces
clone and deployment sizes per repository, but total storage is reduced by
deduplicating revisions, avoiding repeated indexes and updating only changed
records. Size measurements must precede further sharding or historical-site
partitioning. Preserve links and historical lookup when moving a topic. Do not
automatically rewrite history, delete old snapshots or discard coverage to meet
a budget.

As checked on 2026-09-26, GitHub blocks ordinary files larger than 100 MiB and
warns above 50 MiB. Published Pages sites have a 1 GB limit. These are separate
from a repository's history size. The pipeline must measure output before
publication and report which shard/site needs partitioning. The built-in Wiki
has a soft 5,000-file limit. It may serve curated material later, but it is not
the full-corpus store or a second authoritative copy of guides. See references.

## 6. Refresh, build and coordinated release

The generated map records stage owners and dependencies. The intended sequence is:

1. **Capture:** the existing decompiler creates a stable local snapshot and
   validates extraction coverage. Wiki refresh can consume an existing capture;
   it must not re-extract unchanged inputs unnecessarily.
2. **Register:** validate snapshot identity/schema, record provenance and compare
   it with earlier captured inputs. Registration does not certify wiki content.
3. **Normalize:** adapters stream source records into typed facts and edges;
   record gaps, new types and dependency hashes. Read raw inputs in place.
4. **Reconcile identity:** resolve deterministic matches, apply reviewed mappings,
   and retain ambiguous cases as explicit unresolved observations.
5. **Project:** assign canonical owners, aggregate readable pages, compute
   references/backlinks, produce topic search shards and record affected pages.
6. **Verify:** run schema, identity, relationship, page-provenance, semantic,
   link, coverage, size and deterministic-repeat checks. Curated assertions whose
   dependencies changed receive tests or a review-needed result.
7. **Release:** commit changed child outputs and create one immutable manifest
   that pins all participating commits, contracts and validation results.
8. **Publish:** deploy version-addressed topic content, verify it, and update the
   hub's coordinated release pointer last. Retain the previous working release.

No schedule or remote deployment is created by this ADR. Future automation should
invoke these commands and consume their exit codes/receipts. It should notify
maintainers about actionable failures or changes, without requiring an LLM to
rewrite ordinary updates.

### Invalidation rules

| Change | Required work |
| --- | --- |
| Input data or relevant source code | Re-evaluate dependent facts, relationships, pages and curated assertions |
| Added/removed input or new asset type | Inventory/classification reconciliation and visible coverage update |
| Extractor/schema/normalizer change | Revalidate affected adapters and derived data, even for the same game build |
| Identity mapping correction | Rebuild affected references, backlinks, routes and history, preserving prior releases |
| Template/navigation change | Re-render affected views; do not report a gameplay change |
| Latest available build observation | Update freshness information; do not silently grant verification |
| Curated prose change | Validate its claims and links; no blanket re-extraction |

Dependencies should become as narrow as evidence allows. Until an adapter records
complete dependencies, conservative invalidation is appropriate. Hashes establish
input equality, not semantic truth. Routine unchanged inputs should produce
byte-identical outputs and no content commit.

### Failure, concurrency and rollback

There is one writer per umbrella workspace, protected by an OS-held lock. A
process exit releases the lock; the small lock file is not proof of a live writer.
Raw source commits are pinned before reads and rechecked before registering a
receipt. Unknown schemas, dirty source snapshots, conflicting identities and
changed inputs produce errors with no promoted result.

Use staging directories outside child working trees. Validate complete outputs
before promotion. Child content must be clean before a release coordinator writes
it; curated files are never overwritten by a generated-content operation.
Operations use explicit owned paths, reject path escapes and preserve unknown
files. Normal retries reuse verified outputs or rebuild incomplete staging.
There is no automatic destructive cleanup or force override of file protection.

There is no atomic transaction spanning several Git repositories or Pages sites.
The release manifest and hub pointer provide the logical commit boundary. If
some repositories commit/deploy and another fails, their new version-addressed
content remains unadvertised by the hub. Retry from recorded stage receipts;
promote the hub only after every pinned target is available. Existing version
URLs must remain available while deploying a newer site.

Rollback selects a previously validated release manifest and restores its hub
pointer. It does not rewrite child histories or mutate source observations.
The future coordinator must persist stage identity, expected hashes, participating
commits and completion receipts so restart cannot mistake partial publication
for success. Network operations use bounded retry with surfaced failures;
contract violations require correction, not blind retry.

## 7. Curated content and low-cost maintenance

Curated guides supply explanations, comparisons and practical advice. Generated
tables and references are inserted from versioned facts. Each material claim
records dependencies or an explicit manual verification requirement. Assertions
can check valid tag sets, item membership, recipe inputs and outputs, relevant
code signatures and calculation examples.

Separate authored prose from generated sections. A changed dependency should
update factual sections automatically and either pass the claim's tests or mark
its explanation for review. An obsolete explanation must not retain a current
badge merely because generation completed. Failed assertions preserve the last
verified version and show the reason. LLM assistance is optional for new adapters
or explanations, never part of the normal refresh loop.

External links use a reviewed mapping keyed by stable entity/topic. An automatic
checker can suggest or validate official wiki destinations, retain check dates,
and distinguish populated, empty, missing and temporarily unavailable pages.
The default build is offline and deterministic; link observations enter as
versioned inputs instead of making output depend on live HTTP responses.

## 8. Structural enforcement and acceptance

The local foundation delivered with this ADR implements:

- A validated repository registry, exclusive kind ownership, known relationship
  endpoints, safe checkout paths and an acyclic pipeline graph.
- Local-only initialization of independent child repositories and read-only
  status checks that reject unknown repository ownership; a checkout lock pins
  exact reviewed child commits separately from future release manifests.
- A generated repository/relationship map with a drift check.
- Existing-source snapshot registration, rejecting dirty inputs, remotes,
  unsupported schemas and receipt collisions.
- A deterministic architecture/navigation preview with link validation, output
  integrity checks, writer exclusion and staged promotion.

It deliberately labels topic extraction, identity reconciliation, gameplay
verification, coordinated releases and Pages deployment as **planned**. The
preview cannot serve as evidence those stages exist. The input receipt is not
a release manifest. The full gameplay wiki is not built by this foundation.

Implementation acceptance for the later stages requires:

1. Every source object is accounted for as a domain observation, technical asset
   entry, explicit payload omission or documented extraction gap. No silent loss.
2. One canonical owner per entity; graph targets resolve within the selected
   snapshot or carry an explicit unresolved/not-present status.
3. Real source examples independently demonstrate identifiers, values and
   reference paths; fixtures alone cannot establish source fidelity.
4. At least two captured versions demonstrate changed IDs, unchanged content,
   new/removed entities, ambiguous matches and correct historical navigation.
   Synthetic tests cover cases the available builds do not contain.
5. A game update and an extractor-only correction produce distinct, accurate
   change histories. No-op reruns produce no byte changes or new commits.
6. Every gameplay page renders its provenance/freshness/history, and failed or
   incomplete verification prevents a current badge.
7. Cross-repository links, search, curated assertions and official-link handling
   pass focused tests. English names and technical IDs remain discoverable.
8. Interrupted generation and partial multi-repository publication retain the
   previous coordinated release. Concurrent writers and modified output fail
   safely; retries do not duplicate records or lose content.
9. Publication inventories meet measured platform limits without copying bulk
   media, raw source trees or unnecessary intermediates into output repositories.
10. A maintainer can run refresh/build, interpret failures and recover from a
    documented receipt using scripts, without an LLM in the normal workflow.

## 9. Delivery sequence and remaining implementation choices

| Milestone | Deliverable and exit condition |
| --- | --- |
| Foundation, current | This ADR, independent umbrella/child repositories, registry, map, snapshot receipt, tested local commands and preview |
| Data contracts and vertical slice | Implement normalized observations/edges, source version labels, identity decisions and item/loot projections with real-source checks; retain all other topics in the registry |
| Full coverage | Extend reusable adapters across all registered topics; technical catalog accounts for remaining assets and exposes gaps |
| Historical reader | Revision reuse, version selection, history, search and curated assertions demonstrated across captured builds |
| Coordinated publication | Create intended public remotes/Pages sites, implement release receipts and hub-last deployment, rehearse failure/rollback |
| Stable operation | Repeatable refreshes with measured size/time, bounded review queues and no routine LLM dependence |

The vertical slice is an implementation sequence, not reduced final scope.
Use measured record counts and query patterns to choose streaming files versus
a rebuildable SQLite index. Choose the final renderer/theme when the historical
reader is implemented; the foundation's standard-library HTML preview is not a
commitment to a custom production rendering framework. Additional repository
splits require measured need and preserved routes. Our authored code/documentation
license can be selected at publication; it cannot purport to relicense the game.

## 10. Alternatives and consequences

| Alternative | Decision and reason |
| --- | --- |
| One large public repository | Multiple topic repositories better isolate history, clone costs and Pages output size; the shared registry absorbs coordination work |
| Built-in GitHub Wiki as the whole corpus | Ordinary repositories and Pages better support generated structure, tooling and the full catalog; curated Wiki use remains optional |
| Publish the raw catalog index as navigation | Generate links, category indexes and search shards instead; the raw reference index is a build input |
| One Markdown file per source object | Group by readable subject/family while retaining searchable technical identities and coverage accounting |
| Fully duplicated site for every game patch | Reuse unchanged revisions and store small snapshot mappings; materialize only what browsing requires |
| Git submodules or copied child trees | Independent ignored checkouts plus a registry and release lock avoid nested history and implicit cross-repository mutations |
| Runtime/on-demand game extraction or an in-game viewer | Deferred; the current deliverable is a reliable GitHub-hosted wiki |
| LLM-generated full rewrites on updates | Deterministic extraction, templates, tests and selective human review provide predictable cost and diffs |
| Private-only wiki or advance studio permission gate | Rejected by the project owner; the accepted publication posture is recorded above |

The principal cost is maintaining a coordinated multi-repository release and a
trustworthy semantic interpretation layer. The benefits are usable history,
bounded topic storage, explicit provenance and reusable automation. The design
does not promise that every behavior can be inferred from static assets. It does
require every gap and inference to be visible and tied to evidence.

## References and evidence

- Existing extraction contract: `HumanHostMods/docs/GAME_CODEBASE.md`; generator:
  `HumanHostMods/tools/Decompile-GameCode.ps1` and `tools/game_catalog/`.
- Baseline inspected: local snapshot commit
  `9d77a0415918fe14276bde8508d67f713e97ec77`, Steam build `25548639`, depot
  `2393972` manifest `8060226703539543058`. Catalog reports 414,343 objects and
  three editor-only schema gaps. This is a captured input, not a claim about the
  latest available game release or completed wiki verification.
- [Developer modding announcement, 2026-05-05](https://steamcommunity.com/ogg/2393970/announcements/detail/678497276169030049).
- [Developer recognition of community wiki, 2026-08-24](https://steamcommunity.com/app/2393970/discussions/0/591813437999526401/).
- Shipped `_End User License Agreement (EULA).txt`, effective 2026-04-06,
  SHA-256 `DF11EF15168A60C1857B92AAB0F2DC37E1E060209D528A1F348DD2187BCD1E96`.
  The owner's publication decision followed review of this evidence and is
  not a claim of a blanket source-redistribution license.
- [GitHub file/storage guidance](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github),
  [Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits), and
  [Wiki limits](https://docs.github.com/en/communities/documenting-your-project-with-wikis/about-wikis), checked 2026-09-26.

Changes to accepted boundaries require a successor ADR or an explicit amendment
that identifies what changed and why. Update the registry, generator and tests
with the decision so the architecture does not depend on remembering this chat.
