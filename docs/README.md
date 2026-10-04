# Document and contract index

Use this map to find the owner before changing a rule or reporting status.
Each row names one document's responsibility. Current contracts define behavior;
operator procedures explain commands. Generated documents derive from their named
inputs. Dated historical evidence records what happened at that checkpoint.
Historical status wording does not describe today's implementation.

[ACCEPTANCE.md](ACCEPTANCE.md) owns current implementation status, delivery
dispositions and evidence limits. Other documents link there for status.
`project.json` owns the machine-readable stage registry and repository identities.
Code paths below are relative to the repository root. Module names without a
directory prefix refer to `wikibuild/`; test names refer to `tests/`.

The parent runbook link assumes the deployed `HumanHostMods/HumanHostWiki` layout.
The coordinator supplied its target as
`C:/Users/Admin/Documents/GIT/GameMods/HumanHostMods/docs/RUNBOOK-game-update.md`.
This worktree checks that path text only; it does not inspect the target's existence
or contents.

## Document owners

| Document | Owns | Kind | Code owners | Tests or evidence |
| --- | --- | --- | --- | --- |
| [Root README](../README.md) | Project entrypoints | Operator procedure | `wiki.py`, `navigation.py` | `test_foundation.py` |
| [AGENTS.md](../AGENTS.md) | Agent work rules | Current contract | No runtime module | `test_foundation.py` |
| [This index](README.md) | Document ownership and lifecycle | Current contract | No runtime module | `test_foundation.py` |
| [ADR-0001](adr/0001-versioned-public-wiki.md) | Accepted product and state architecture | Current contract, accepted 2026-09-26, amended 2026-10-02 | `manifest.py`, `workspace.py`, `pipeline.py`, `release.py`, `publication.py` | `test_foundation.py`, `test_pipeline.py`, `test_release.py`, `test_publication.py` |
| [ADR-0002](adr/0002-player-template-and-guides.md) | Player presentation and generated guide decisions | Current contract, accepted 2026-09-28 | `presentation.py`, `gameplay.py`, `guides.py`, `guide_queries.py`, `web/` | `test_presentation.py`, `test_gameplay.py`, `test_guides.py`, `test_guide_queries.py`, `test_reader_player.py` |
| [ACCEPTANCE.md](ACCEPTANCE.md) | Current delivery status and scope of proof | Current contract with dated evidence | Stage owners named in its requirement rows | Requirement rows, snapshot/release/publication receipts |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Component and process boundaries, including test isolation | Current contract with dated review | `components.json`, `bounded.py`, `wiki.py`, `tools/check_components.py`, `tools/run_tests.py`, `tests/_support.py` | `test_architecture.py`, `test_process_lint.py`, `test_git_bounds.py`, `test_bounded.py`, `test_windows_fixtures.py` |
| [AVAILABILITY.md](AVAILABILITY.md) | Steam branch observation and cache policy | Current contract | `availability.py`, `steam_build.py`, `tools/Install-SteamMetadataClient.ps1` | `test_availability.py`, `Test-InstallSteamMetadataClient.ps1` |
| [CAPACITY.md](CAPACITY.md) | Physical storage allocation and rollover | Current contract | `capacity.py`, `capacity_inventory.py`, `capacity_projection.py`, `physical.py`, `shard_index.py`, `capture_catalog.py`, `entrypoints.py` | `test_capacity*.py`, `test_shard_index.py`, `test_capture_catalog.py`, `test_entrypoints.py` |
| [CURATED.md](CURATED.md) | Scoped checks for authored claims | Current contract | `curation.py`, `curated_rules.py`, `code_dependencies.py` | `test_curation.py`, `test_code_dependencies.py` |
| [EXTERNAL_LINKS.md](EXTERNAL_LINKS.md) | External article observations and matching | Current contract | `external_links.py`, `mediawiki.py` | `test_external_links.py`, `test_external_integration.py` |
| [EXTRACTION.md](EXTRACTION.md) | Selected fact rules and adapter extension | Current contract | `extraction.py`, `source.py`, `source_record.py`, `adapters/` | `test_extraction.py`, `test_source_record.py`, adapter suites; `tools/check_extraction.py` |
| [GAME_VERSION.md](GAME_VERSION.md) | Application-version provenance | Current contract | `snapshots.py`, `reader.py`; parent catalog selector, read in place | `test_foundation.py`, `test_reader.py`, `reader_captures.test.js` |
| [IDENTITY.md](IDENTITY.md) | Entity matching and semantic revision history | Current contract | `identity.py`, `model.py`, `history.py` | `test_identity.py`, `test_model.py`, `test_history.py` |
| [PIPELINE.md](PIPELINE.md) | Local update ordering, receipts and reporting | Current contract | `pipeline.py`, `manifest.py`, `run_timing.py`, `wiki.py` | `test_pipeline.py`, `test_foundation.py`, `test_run_timing.py` |
| [PUBLICATION.md](PUBLICATION.md) | Production gate, deployment and abandonment | Current contract | `publish_gate.py`, `publication.py`, `publication_git.py`, `github_pages.py`, `tools/rehearse_publication.py` | `test_publish_gate.py`, `test_publication*.py`, `test_github_pages.py`, `test_rehearsal.py`, `test_cli_publication.py` |
| [READER.md](READER.md) | Candidate rendering and browser data loading | Current contract | `reader.py`, `pages.py`, `packs.py`, `web/` | `test_reader*.py`, `reader_captures.test.js`, `reader_shards.test.js` |
| [RELEASE.md](RELEASE.md) | Coordinated local Git promotion | Current contract | `release.py`, `release_prepare.py`, `release_content.py`, `release_output.py`, `release_partitions.py`, `git_transaction.py`, `ownership.py`, `release_bootstrap.js` | `test_release.py`, `test_ownership*.py`, `test_release_browser.py`, `release_bootstrap.test.js` |
| [RETENTION.md](RETENTION.md) | Owned staging retirement and immutable reader sharing | Current contract | `staging.py`, `release_retention.py`, `reader_retention.py` | `test_extraction.py`, `test_history.py`, `test_reader.py`, `test_release.py`, `test_release_retention.py`, `test_reader_retention.py` |
| [WORKFLOW.md](WORKFLOW.md) | Operator setup, commands and recovery steps | Operator procedure | `wiki.py`, `tools/` | Command owners' suites; `test_foundation.py` checks links |
| [HumanHostMods game-update runbook](../../docs/RUNBOOK-game-update.md) | End-to-end operator procedure for a game update | Operator procedure, parent repository | Parent capture entrypoint; `wiki.py`, `pipeline.py` own the wiki handoff | HumanHostMods PR #13, reported by the coordinator; `test_pipeline.py`, `test_cli_publication.py` cover the local wiki boundary |
| [REPOSITORIES.md](REPOSITORIES.md) | Derived repository, navigation and stage map | Generated | `project.json`, `manifest.py::repository_map` | `test_foundation.py`; `wiki.py map --check` |
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | Implementation checkpoint results through 2026-09-27 | Dated historical evidence | Modules named at each checkpoint | Checkpoint logs and audit results |
| [BASELINE_RECONCILIATION.md](BASELINE_RECONCILIATION.md) | Initial rule-review decisions for build 25548639 | Dated historical evidence, 2026-09-27 | `adapters/`, `exceptions.py` | Recorded source reviews and baseline audits |
| [BASELINE_INVENTORY.md](BASELINE_INVENTORY.md) | Original exception-to-rule reconciliation | Dated historical evidence, 2026-09-27 | `adapters/components.py`, `adapters/schema.py`, `adapters/catalog_policy.py` | Baseline ledger and recorded source/history audits |
| [baseline-inventory-reconciliation.json](baseline-inventory-reconciliation.json) | Machine-readable original exception ledger | Dated historical evidence, build 25548639 | Baseline adapter rules | Per-class counts, selected fields and review reasons |
| [delivery-evidence.json](delivery-evidence.json) | Exact baseline delivery identities and checks | Dated historical evidence, 2026-09-27 | Extraction, identity, reader, release and publication owners | Recorded run IDs, hashes and repeat results |

## Rules of the road

- An update stops at the local release, release retention and reader retention.
  [PIPELINE.md](PIPELINE.md) owns that boundary.
- Publish only through the separate operator command and the
  [production gate](PUBLICATION.md#production-gate).
- Abandon a failed publication attempt. Do not salvage or resume it. Follow
  [PUBLICATION.md](PUBLICATION.md#durable-state-and-abandonment) before a fresh rehearsal.
- Run tests by component with private fixtures outside the checkout. Follow
  [ARCHITECTURE.md](ARCHITECTURE.md#running-tests).
- Launch production children through the owned, bounded process runtime. Follow
  the [process rule](ARCHITECTURE.md#process-rule).
- Do not add decompiled game code to any repository. Read the local capture in
  place and publish only selected factual records under [EXTRACTION.md](EXTRACTION.md).
