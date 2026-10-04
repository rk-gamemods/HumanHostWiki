# Delivery acceptance and current status

This is the closed acceptance inventory for ADR-0001, REPOSITORIES.md and
WORKFLOW.md. It preserves the ADR requirements and distinguishes implementation,
fixture proof, real-source proof and unavailable external evidence. Later notes,
optional mechanics research and stale status labels do not add completion gates.

Baseline delivery inventory (2026-09-27): application **0.8.315**, Steam build **25548639**, source
capture **1080b929da89375e2c09b6a80abc28f343e9d9a5**. Coverage means the
414,343 enumerated catalog objects and the selected contracts for this capture.
It does not mean that every runtime mechanic has an authored explanation.
This file alone owns current implementation status and evidence dispositions.
[The document index](README.md) identifies behavior and procedure owners.

Public product: **Unofficial Game Data Wiki for Human Host**, with recorded destinations for the
[wiki](https://rk-gamemods.github.io/HumanHost-Wiki/) and
[hub repository](https://github.com/rk-gamemods/HumanHost-Wiki). The generated
[repository map](REPOSITORIES.md) lists the twelve topic repositories. The normal
command, from HumanHostMods, is:

```powershell
pwsh -NoProfile -File tools/Decompile-GameCode.ps1
```

## Requirement, implementation and finite proof

Evidence under `.local/` is retained local diagnostic material. Durable release,
publication, snapshot and identity receipts are committed in this umbrella.
Historical implementation checkpoints describe their own dates, not new work.
The rows retain their dated baseline evidence. A10 and A22 include the later
receipt and stage-graph reconciliation below.

| ID / requirement | Implementing code | Finite verification and existing evidence | Disposition / actual defect |
| --- | --- | --- | --- |
| A01 ADR 1: public English community reference, studio credit, free and ad-free | `navigation.py`, `pages.py`, `release.py`, `project.json` | Thirteen public repositories/sites; approved public name and explicit non-affiliation statement in headers, repository READMEs and descriptions | Implemented. In-game viewer remains explicitly deferred. |
| A02 ADR 1, 8: fixed baseline-capture coverage and original backlog | `adapters/components.py`, explicit topic contracts, `adapters/schema.py` | [191-row inventory](BASELINE_INVENTORY.md), two relationship groups, five article issues; 27,011 original component instances; zero baseline exceptions | Passed. 72 domain/configuration class contracts and 119 reviewed technical-summary contracts. |
| A03 ADR 1, 8: account for every object without exporting raw inputs | `adapters/catalog_policy.py`, `components.py`, parent catalog generator | Complete source audit: 414,343 objects accounted, 527 type summaries, 365,969 assertions; `.local/baseline-selective-source-audit.json` | Passed. 45,518 payload objects omitted by scope; three editor-only decode gaps explicitly retained. No unknown group hidden. |
| A04 ADR 2: canonical topic ownership, independent repositories, acyclic build graph | `manifest.py`, `workspace.py`, `project.json` | Registry/map/lock checks, `test_foundation.py`; real 13-repository release audit | Passed. Map stage labels describe implemented scope, not research completeness. |
| A05 ADR 3: input receipts, checkout lock and immutable releases are distinct | `snapshots.py`, `workspace.py`, `release.py` | Receipt validation, tampering and repeat tests; committed `snapshots/`, `workspace.lock.json`, `releases/` | Passed. None grants gameplay verification. |
| A06 ADR 4: exact build, source and generator provenance; application version | `snapshots.py::game_version`, extraction contracts | Snapshot receipts and source hash audit; application-version tests/checkpoint; version 0.8.315 from PlayerSettings evidence | Passed. Missing version evidence remains unknown; machine/account data excluded. |
| A07 ADR 4: stable wiki identity, scoped game IDs, renames/removals/reuse/ambiguity | `identity.py`, `model.py`, `history.py` | `test_identity.py`, `test_history.py`; real audit of 25,472 observations / 449,827 assertions, preserved in the final delivery evidence | Implemented and fixture-proven for change cases. Real current-capture mappings audited. |
| A08 ADR 4: selected typed facts, exact references, fields, conditions and evidence | Topic adapters, `schema.py`, `prefabs.py`, `coded_values.py`, `model.py`, reader | The `_AmmoType: 5` defect produced a shared correction for 31 selected enum fields, 24,203 occurrences, 109 used values and 42 ammunition item links. Source-text and reader checks pass; Ammo Type is now a linked 7.62x54mm entry. | Corrected and published. Unknown codes remain exceptions, raw values remain provenance. Unknown units/conditions are not invented. |
| A09 ADR 4: last changed differs from last verified; freshness remains honest | `availability.py`, `curation.py`, `pages.py`, `web/reader.js` | Availability, curation and reader tests; live Steam observation; browser capture selection | Passed. Extraction success cannot set runtime gameplay verification. Unknown status is an allowed result. |
| A10 ADR 4, 5, 8: versioned history and navigation across at least two captured builds | `history.py`, `reader.py`, `release_content.py`, browser loaders | Two-build fixtures cover additions/removals, ID changes, unchanged content and ambiguity. Retained release versions now include four distinct real builds with identity runs. See captured-build evidence below. | Multi-build capture and normalization are recorded. Fixtures prove the listed change cases; receipts alone do not prove that each case occurred in real gameplay. |
| A11 ADR 5: deterministic Git text, semantic revisions, grouped Markdown and browser-readable history | `model.py`, `packs.py`, `release_content.py`, `release_output.py` | Final reader audit: 67,127 retained observations / 604,151 assertions; release audit: 5,990 owned files and 299 historical configs | Passed. Unchanged semantic revisions are reused. Historical configs are not counted as game builds. |
| A12 ADR 1, 5: hub discovery, search, filters, version selection and cross-topic routes | `navigation.py`, `reader.py`, `web/reader.js`, release loader | Production-loader tests; live Crude Axe search, Items-to-Crafting and older capture navigation; source-preserving route checks | Passed. Authored guides are optional under ADR 7; no requirement to research every mechanic. |
| A13 ADR 5, 8: automatic splits, capacity allocation/provisioning and preserved history | `capacity*.py`, `physical.py`, `shard_index.py`, `capture_catalog.py`, `entrypoints.py`, release coordinator | Real-Git forced-threshold fixtures with deterministic host: overflow, provisioning, paged control indexes, retired fronts, replay and historical URLs; `test_capacity_release.py`, `test_capacity_projection.py`, `test_entrypoints.py` | Implemented and fixture-proven. Real inventory fits default budgets; live GitHub overflow was not forced. Existing live provisioning of 13 sites validates the host path. |
| A14 ADR 6: one operator command detects stable inputs, captures and processes supported work unattended | Parent `Decompile-GameCode.ps1`, `snapshots.py`, `pipeline.py` | Normal command logs `.local/baseline-selective-decompile.log` and repeat log in parent; source reused after input hashes/Steam identity/generator validation | Passed. No scheduler or automatic LLM stage. |
| A15 ADR 6: deterministic invalidation, no-op byte/Git stability, last-success baseline | Extraction, history, reader and pipeline contracts | Final normal repeat: 66.601 s, 13 child commits and 6,111 observed file hashes/timestamps unchanged; source commit unchanged; identical pipeline/release IDs | Passed. No additional content commit or unchanged-content publication. Existing extraction and identity reuse checks also read zero selected-source bytes. |
| A16 ADR 6, 8: unsupported content isolated; changed/new records continue | `schema.py`, `components.py`, `exceptions.py`, `pipeline.py` | New-field/class, wrong-assembly, missing-reference and malformed-value regressions; known records proceed; initial inventory resolved in owning rules | Passed. Content exceptions remain separate from execution failures. |
| A17 ADR 6, 8: interruption, writer exclusion, dirty input/output, retry and recovery | `storage.py`, `git_transaction.py`, `release_prepare.py`, `pipeline.py` | Pipeline, extraction, release and ownership tests; interrupted promotion and replay checks | Passed. No protected file override or history rewrite. |
| A18 ADR 6, 8: topic-first deployment, pinned target verification, hub promotion/rollback | `publication.py`, `publication_git.py`, `github_pages.py`, `entrypoints.py` | Real 13-site publication receipts and HTTP hashes; deterministic-host tests for partial publication, transient failures, lost response, changed remote and hub rollback | Passed. Existing release remains readable while a later deployment is incomplete. |
| A19 ADR 7: optional checked authored claims and isolated failed checks | `curated_rules.py`, `curation.py` | Curation fixtures verify typed values, code dependency changes, failed claims, last-success history and repeated-input reuse | Passed. Optional named C# checker work was restored and retained; it is not required to resolve the baseline or author prose. |
| A20 ADR 7: populated official backlinks, cached observations and independent outage behavior | `external_links.py`, `mediawiki.py` | Five original revisions now populated; 22 configured checks populated; article/provider and projection audits | Passed. Bodies discarded; article availability does not assert gameplay accuracy. |
| A21 ADR 6: future lightweight classifiers only recorded as experiments | `BASELINE_RECONCILIATION.md`, `IMPLEMENTATION.md` | Concrete candidate labels and test criteria documented | Passed. No classifier or model-spending service implemented. |
| A22 map/workflow: accurate implemented stages and actionable run status | `project.json`, generated `REPOSITORIES.md`, `manifest.py`, `pipeline.py`, `wiki.py` | Foundation tests compare the declared graph with the fixed runner sequence and reject order/edge drift. Pipeline tests cover content issues and the separate publish next step. | Corrected. A successful update ends locally and reports `publish` as the next operator step, plus detected content/article issues. |

## Baseline delivery evidence (2026-09-27)

The normal command completed successfully and published the approved name and
non-affiliation statement on 2026-09-27. The 193 original content groups and five
article issues remain reconciled, with zero unresolved content groups or article
issues and 22 populated article checks. The original ledger is preserved in
[baseline-inventory-reconciliation.json](baseline-inventory-reconciliation.json).

The subsequent normal-command repeat completed in 66.601 seconds. All 13 child
commits and 6,111 observed file hashes and timestamps remained unchanged. It reused
the published release and produced no new content publication. The final run IDs,
source/history audit reuse, reader/release audits, public repository commits and
local log hashes are preserved in [delivery-evidence.json](delivery-evidence.json).

- Pipeline: `cc2e8ff11bf9e0fa2d6408a4fcae2356d096928474c7b50dd3c266669dc4a533`.
- Release: `53307f1c57a80b3a7bce5441eb1dab973ea18481d70e96655c4fd7c0e0284d1d`.
- Reader: `81ccfe3d8fac58edf157383e218b6b6399bf032175bfc6a3d758e096280948ca`.
- Source and identity audit inputs are unchanged from the independently checked
  coded-value correction. Final reader and release audits passed again because
  their rendered output changed.
- Seventeen focused reader, release-repeat and publication-order tests passed
  after the final branding edits. Existing extraction, history, identity,
  foundation and recovery test evidence remains applicable.
- Live browser checks verified the approved header and exact disclaimer on the
  hub, weapon and caliber pages. The weapon's Ammo Type links to 7.62x54mm; that
  destination links to the factory bullet and five material variants. Entry
  document titles also use the approved public name.

That delivery reconciled the original backlog for build 25548639. It does not
establish exception-free coverage for every later capture. The evidence limits
below remain explicit; they do not trigger autonomous follow-on work.

## Captured-build evidence

Local receipts inspected on 2026-10-03 record nine snapshots across four distinct
Steam builds. Six snapshots belong to build 25548639; each later build has one.
These are captured inputs, not nine game versions.

| Steam build | Application label | Representative input receipt |
| --- | --- | --- |
| 25548639 | 0.8.315 on the baseline capture; earlier labels remain unknown | [build-25548639-1080b929da89](../snapshots/build-25548639-1080b929da89.json) |
| 25587699 | 0.8.316 | [build-25587699-a399133f7ca4](../snapshots/build-25587699-a399133f7ca4.json) |
| 25606549 | 0.8.316 | [build-25606549-f1e8b4a4a8b8](../snapshots/build-25606549-f1e8b4a4a8b8.json) |
| 25675256 | 0.8.318 | [build-25675256-8764ea7be0f8](../snapshots/build-25675256-8764ea7be0f8.json) |

[releases/latest.json](../releases/latest.json) selects release
`cd0a533da3419bc83656c4e016f2733ab49757fe7952e88568d516425e5adb07`.
Its [manifest](../releases/cd0a533da3419bc83656c4e016f2733ab49757fe7952e88568d516425e5adb07.json)
records all four builds in `versions`, with snapshot IDs, observation counts and
identity-run IDs. Distinct real builds have therefore been normalized and retained.
[publications/latest.json](../publications/latest.json) selects the same release.
Its [publication receipt](../publications/cd0a533da3419bc83656c4e016f2733ab49757fe7952e88568d516425e5adb07.json)
records `status: published` and verified outputs for all thirteen logical sites.
This is saved publication evidence, not a fresh live-availability check.

The release records `reader_artifacts: passed`, `coverage: partial` and
`gameplay_verification: not-performed`. Multi-build receipts do not establish
runtime verification or demonstrate every identity change case in real captures.
Fixtures remain the finite proof for changes that those captures do not exercise.
The 2026-09-27 history review found no catalogs for earlier local source commits
`7550530` (25448142) and `3c01f7f` (25407931). This task did not reinspect those
source checkouts. Current assets cannot reconstruct their historical values.

## Current engineering limits

Capacity allocation, paged snapshot/capture/ownership metadata and entrypoint
rollover have real-Git fixture proof. The retained release fits configured budgets;
it records no new physical repositories or rolled topics. Live overflow was not
forced. An indivisible over-budget control record is a deliberate pre-promotion
failure, not an unfinished splitter.

The production gate, local publication abandonment, stuck-Pages recovery and run
timing have deterministic tests. Merged PR #33 added supervised timeout cleanup;
PR #38 confirms whole POSIX process-group exit. Production children use registered
Windows jobs or POSIX groups, with launch fencing and bounded cleanup.
PR #41 bounds Git calls and streaming I/O; its process lint tracks import provenance
within its documented scope. PR #36 runs rehearsal in an OS-temp workspace with
disposable child clones. PR #39 records staging ownership and retires older abandoned
attempts while preserving a diagnostic attempt and unknown files.

PR #42 fixes #23/#24 by splitting reader helpers and centralizing pipeline
contract construction. The coordinator reports #34 (legacy rehearsal pins) and
#22 (release/allocation coupling) in flight, not merged. Open backlog
includes #26 (remaining complexity hotspots) and #40 (staging tombstones and
process-death tests). The [architecture review](ARCHITECTURE.md#architecture-review-2026-10-03)
groups the remaining boundaries and names their owners. Test proof does not
establish live GitHub availability.

## Closure rule

Further engineering must name an acceptance ID and a reproducible failing case.
The listed external-evidence limitations are reported with delivery. Optional
guides, new mechanic explanations, extra retention policies and live capacity
experiments are not discovered blockers. A successful run is complete for its
captured inputs even when runtime verification is unknown. This does not erase
any ADR requirement or reclassify unavailable real evidence as passed.

## ADR-0002 player template and guides

The user opened this scope on 2026-09-28 by choosing design study 11 as the public
template ([ADR-0002](adr/0002-player-template-and-guides.md)). Each row names the failing
case that justifies the work, as the closure rule above requires. Failing cases were
observed in release `53307f1c…` and reader `81ccfe3d…`.

| ID / requirement | Failing case | Planned implementation | Proof required | Status |
| --- | --- | --- | --- | --- |
| A30 ADR-2 §6: deterministic readability audit | No check measures whether player-facing text is readable. 18 Items packs carry `0.07999999821186066` (Crude Axe blade hit chance), and nothing reports it. | `tools/audit_readability.py` | Two runs produce identical bytes. The report lists the Crude Axe float, the duplicate M1891 names, the bow damage multiplier, the untranslated tags and the `G_Mode` debug item. | Passed 2026-09-29. Two runs over reader candidate 64d6af9d (build 25587699) produced identical bytes. The report lists the Crude Axe float, the M1891 duplicates, `_baseDamage`, `cjk_text` (42) and `G_Mode`. |
| A31 ADR-2 §2, §3: reviewed presentation registry and build-time formatting | `fieldLabel()` builds labels from serialized names, such as "Dura Cost Per Attack", and `valueNode()` prints raw floats. | `presentation/fields.json`, `wikibuild/presentation.py`, pack display strings | Every player-tier field has a label and a format. Unlisted fields render as technical. Raw values stay in the technical tier. | Passed 2026-09-29. `test_every_player_tier_value_has_a_label_and_format` checks every registry value (and fails when a format is removed); `test_presentation` covers formats, cases and the Crude Axe card. |
| A32 ADR-2 §3: distinct player names for records that share a display name | Several item records all display as "M1891", including a crafted record and a loot-only record with different damage and magazine size. | Name derivation from acquisition sources | No two player-tier records in one topic share a displayed name unless the audit reports them as identical. | Passed 2026-09-29. Build 25606549 search index (27,273 rows): 0 names repeated within one topic and kind. Records of different kinds for one game object share a name and show their kind. |
| A33 ADR-2 §4: derived gameplay joins | The biomes topic has no biome-to-item relationship. `Terrain_Block_Info.CollectableItems.ItemBI_refKey` is unresolved, and container biome is known only from bundle names. | New adapters in `wikibuild/adapters/` | Fixture tests for each join. Real Desert lists Nitrate ore and Chrismatite. Rates are never shown as probabilities. | Passed 2026-09-29. `test_gameplay` fixture tests per join. Real Desert lists Nitrate Ore and Yellow Wax Stone, the game's English name for `Chrismatite_Icon`, as dig-hit rates. |
| A34 ADR-2 §5: generated guides | The hub owns `guide`, but it has no guide entries. The current "long reads" are the Crude Axe and M1891 entry pages. | `guides/*.json`, `wikibuild/guides.py` | Four guides. Golden output from fixtures, a byte-identical repeat run, every link resolves, and no empty section. | Passed 2026-09-29. Four guides render on build 25606549 with 0 jargon findings. `test_guides` and `test_guide_queries` hold the fixture goldens, and `test_default_selection_files_repeat_bytes_and_explicit_selection` checks that a repeat render produces identical bytes. `check_site.js` follows 5 seeded links per guide (0 failures, candidate 26a359e5), and `render` rejects an empty required section. |
| A35 ADR-2 §6: jargon lint on player text | Player-facing text has no lint. | Test over the player tier and guides | No identifiers, raw enum integers or unformatted floats in the player tier. | Passed 2026-09-29. `test_lint`; `render_guides` reports 0 jargon findings on build 25606549; the audit's `identifier_value` flag is 0. |
| A36 ADR-2 §7: study 11 reader on the hub and all topic sites | Live reader, observed 2026-09-28: hub search returns 0 entries for every query; "m1891 rifle" returns 0 because matching is one substring; the entry name is an `h2` below the topic `h1`. | `wikibuild/web/`, `pages.py`, `reader.py` | A browser suite at desktop and mobile shows 0 console errors, 0 overflow, visible focus, reduced motion and 0 axe violations. Old snapshots render. Existing entry routes resolve. | Passed 2026-09-29. `tools/check_site.js` on candidate 8d422b27: 22 views at desktop and mobile, 0 failures, 0 axe findings of any impact, reduced motion renders the map and waffle, the oldest capture's entry opens. |
