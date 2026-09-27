# Delivery acceptance

This is the closed acceptance inventory for ADR-0001, REPOSITORIES.md and
WORKFLOW.md. It preserves the ADR requirements and distinguishes implementation,
fixture proof, real-source proof and unavailable external evidence. Later notes,
optional mechanics research and stale status labels do not add completion gates.

Delivery inventory: application **0.8.315**, Steam build **25548639**, source
capture **1080b929da89375e2c09b6a80abc28f343e9d9a5**. Coverage means the
414,343 enumerated catalog objects and the selected contracts for this capture.
It does not mean that every runtime mechanic has an authored explanation.

Public product: [wiki](https://rk-gamemods.github.io/HumanHost-Wiki/) and
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

| ID / requirement | Implementing code | Finite verification and existing evidence | Disposition / actual defect |
| --- | --- | --- | --- |
| A01 ADR 1: public English community reference, studio credit, free and ad-free | `navigation.py`, `pages.py`, `release.py`, `project.json` | Thirteen public repositories/sites; published hub/topic browser checks and committed pages | Implemented. No defect identified. In-game viewer remains explicitly deferred. |
| A02 ADR 1, 8: fixed current-capture coverage and original backlog | `adapters/components.py`, explicit topic contracts, `adapters/schema.py` | [191-row inventory](BASELINE_INVENTORY.md), two relationship groups, five article issues; 27,011 original component instances; zero baseline exceptions | Passed. 72 domain/configuration class contracts and 119 reviewed technical-summary contracts. |
| A03 ADR 1, 8: account for every object without exporting raw inputs | `adapters/catalog_policy.py`, `components.py`, parent catalog generator | Complete source audit: 414,343 objects accounted, 527 type summaries, 365,969 assertions; `.local/baseline-selective-source-audit.json` | Passed. 45,518 payload objects omitted by scope; three editor-only decode gaps explicitly retained. No unknown group hidden. |
| A04 ADR 2: canonical topic ownership, independent repositories, acyclic build graph | `manifest.py`, `workspace.py`, `project.json` | Registry/map/lock checks, `test_foundation.py`; real 13-repository release audit | Passed. Map stage labels describe implemented scope, not research completeness. |
| A05 ADR 3: input receipts, checkout lock and immutable releases are distinct | `snapshots.py`, `workspace.py`, `release.py` | Receipt validation, tampering and repeat tests; committed `snapshots/`, `workspace.lock.json`, `releases/` | Passed. None grants gameplay verification. |
| A06 ADR 4: exact build, source and generator provenance; application version | `snapshots.py::game_version`, extraction contracts | Snapshot receipts and source hash audit; application-version tests/checkpoint; version 0.8.315 from PlayerSettings evidence | Passed. Missing version evidence remains unknown; machine/account data excluded. |
| A07 ADR 4: stable wiki identity, scoped game IDs, renames/removals/reuse/ambiguity | `identity.py`, `model.py`, `history.py` | `test_identity.py`, `test_history.py`; real audit of 25,363 observations / 318,439 assertions | Implemented and fixture-proven for change cases. Real current-capture mappings audited. |
| A08 ADR 4: selected typed facts, exact references, fields, conditions and evidence | Topic adapters, `schema.py`, `prefabs.py`, `coded_values.py`, `model.py`, reader | Numeric source fidelity was insufficient: the user found `_AmmoType: 5` without a name or edge. The shared correction covers 31 selected enum fields, inherited/nested declarations, 109 used values and ammunition item joins. Independent source-text and reader regression checks pass. | Readability defect corrected locally; final normal publication/repeat evidence pending below. Unknown codes remain exceptions, raw values remain provenance. Unknown units/conditions are not invented. |
| A09 ADR 4: last changed differs from last verified; freshness remains honest | `availability.py`, `curation.py`, `pages.py`, `web/reader.js` | Availability, curation and reader tests; live Steam observation; browser capture selection | Passed. Extraction success cannot set runtime gameplay verification. Unknown status is an allowed result. |
| A10 ADR 4, 5, 8: versioned history and navigation across at least two captured builds | `history.py`, `reader.py`, `release_content.py`, browser loaders | Two-build fixtures cover additions/removals, ID changes, unchanged content and ambiguity. Real same-build capture revisions and historical URLs verified. See evidence disposition below. | Fixture-proven; **two distinct real catalog builds unavailable**. This is an evidence limitation, not a missing parser or permission for more gameplay research. |
| A11 ADR 5: deterministic Git text, semantic revisions, grouped Markdown and browser-readable history | `model.py`, `packs.py`, `release_content.py`, `release_output.py` | Reader audit: 67,018 retained observations / 603,170 assertions; release audit: 4,821 owned files and 260 historical configs | Passed. Unchanged semantic revisions are reused. Historical configs are not counted as game builds. |
| A12 ADR 1, 5: hub discovery, search, filters, version selection and cross-topic routes | `navigation.py`, `reader.py`, `web/reader.js`, release loader | Production-loader tests; live Crude Axe search, Items-to-Crafting and older capture navigation; source-preserving route checks | Passed. Authored guides are optional under ADR 7; no requirement to research every mechanic. |
| A13 ADR 5, 8: automatic splits, capacity allocation/provisioning and preserved history | `capacity*.py`, `physical.py`, `shard_index.py`, `capture_catalog.py`, `entrypoints.py`, release coordinator | Real-Git forced-threshold fixtures with deterministic host: overflow, provisioning, paged control indexes, retired fronts, replay and historical URLs; `test_capacity_release.py`, `test_capacity_projection.py`, `test_entrypoints.py` | Implemented and fixture-proven. Real inventory fits default budgets; live GitHub overflow was not forced. Existing live provisioning of 13 sites validates the host path. |
| A14 ADR 6: one operator command detects stable inputs, captures and processes supported work unattended | Parent `Decompile-GameCode.ps1`, `snapshots.py`, `pipeline.py` | Normal command logs `.local/baseline-selective-decompile.log` and repeat log in parent; source reused after input hashes/Steam identity/generator validation | Passed. No scheduler or automatic LLM stage. |
| A15 ADR 6: deterministic invalidation, no-op byte/Git stability, last-success baseline | Extraction, history, reader and pipeline contracts | Existing normal repeat: 53.760 s, 13 child commits and 4,927 file hashes/timestamps unchanged; extraction and identity repeat read zero selected-source bytes | Passed. Final status-only changes receive focused tests and one normal update/repeat. |
| A16 ADR 6, 8: unsupported content isolated; changed/new records continue | `schema.py`, `components.py`, `exceptions.py`, `pipeline.py` | New-field/class, wrong-assembly, missing-reference and malformed-value regressions; known records proceed; initial inventory resolved in owning rules | Passed. Content exceptions remain separate from execution failures. |
| A17 ADR 6, 8: interruption, writer exclusion, dirty input/output, retry and recovery | `storage.py`, `git_transaction.py`, `release_prepare.py`, `pipeline.py` | Pipeline, extraction, release and ownership tests; interrupted promotion and replay checks | Passed. No protected file override or history rewrite. |
| A18 ADR 6, 8: topic-first deployment, pinned target verification, hub promotion/rollback | `publication.py`, `publication_git.py`, `github_pages.py`, `entrypoints.py` | Real 13-site publication receipts and HTTP hashes; deterministic-host tests for partial publication, transient failures, lost response, changed remote and hub rollback | Passed. Existing release remains readable while a later deployment is incomplete. |
| A19 ADR 7: optional checked authored claims and isolated failed checks | `curated_rules.py`, `curation.py` | Curation fixtures verify typed values, code dependency changes, failed claims, last-success history and repeated-input reuse | Passed. Optional named C# checker work was restored and retained; it is not required to resolve the baseline or author prose. |
| A20 ADR 7: populated official backlinks, cached observations and independent outage behavior | `external_links.py`, `mediawiki.py` | Five original revisions now populated; 22 configured checks populated; article/provider and projection audits | Passed. Bodies discarded; article availability does not assert gameplay accuracy. |
| A21 ADR 6: future lightweight classifiers only recorded as experiments | `BASELINE_RECONCILIATION.md`, `IMPLEMENTATION.md` | Concrete candidate labels and test criteria documented | Passed. No classifier or model-spending service implemented. |
| A22 map/workflow: accurate implemented stages and actionable run status | `project.json`, generated `REPOSITORIES.md`, `pipeline.py`, `wiki.py`, `WORKFLOW.md` | Focused pipeline tests prove empty remaining-work list on success and content issues when detected | Corrected. Hard-coded gameplay/capacity todo labels removed. |

## Historical-build evidence disposition

The four registered real catalog captures all identify Steam build 25548639.
Earlier local source commits `7550530` (25448142) and `3c01f7f` (25407931) have
decompiled code but no `Catalog` tree. Current assets cannot establish their
historical values. They are not represented as captured wiki builds.

Two-build fixtures prove the finite behavior required by A10. The distinct-real-build
portion remains explicitly unproven until another complete catalog is available.
No claim of two-real-build acceptance is made, no historical data is fabricated,
and no unbounded collection/research task runs after delivery. The next normal
decompile after a game update can supply that evidence through the same workflow.

## Closure rule

Further engineering must name an acceptance ID and a reproducible failing case.
The listed external-evidence limitations are reported with delivery. Optional
guides, new mechanic explanations, extra retention policies and live capacity
experiments are not discovered blockers. A successful run is complete for its
captured inputs even when runtime verification is unknown. This does not erase
any ADR requirement or reclassify unavailable real evidence as passed.
