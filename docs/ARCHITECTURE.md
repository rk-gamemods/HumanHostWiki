# Component boundaries and test runs

[`components.json`](../components.json) owns local Python/tool/test boundaries.
The product architecture remains in [ADR-0001](adr/0001-versioned-public-wiki.md),
and `project.json` owns pipeline stages and topic repository identities.
Components follow those stage owners and the actual imports. A feature should
usually change one or two owners; shared primitives belong below stage orchestration.

| Component | Allowed direct dependencies |
| --- | --- |
| process-runtime | None |
| storage | process-runtime |
| run-timing | storage |
| process | process-runtime, storage, test-support |
| source | process-runtime, storage |
| extraction | process-runtime, storage, source, test-support |
| identity | process-runtime, storage, source, extraction, test-support |
| presentation | test-support |
| gameplay | storage, source, extraction, identity, presentation, test-support |
| curation | storage, source, extraction, identity |
| availability | process-runtime, storage, process, test-support |
| external-links | storage, test-support |
| capacity | process-runtime, storage, extraction, presentation, external-links, test-support |
| workspace | storage, source, capacity, external-links, test-support |
| reader | storage, source, extraction, identity, gameplay, curation, presentation, availability, external-links, workspace, test-support |
| release | process-runtime, storage, process, source, extraction, reader, capacity, workspace, external-links, presentation, test-support |
| publication | process-runtime, storage, process, release, run-timing, capacity, workspace, reader, test-tooling, test-support |
| cli | All other production components, test-tooling, test-support |
| test-support | None |
| test-tooling | process-runtime, test-support |

## Process rule

The process runtime in `wikibuild/bounded.py` owns every external child through
a registered Windows job or POSIX process group, with shutdown fencing and
bounded tree cleanup. Git and other command launches use `bounded.run` for
captured output or `bounded.stream` for binary streaming, with an explicit
operation timeout and a one-line reason beside its constant. `bounded.run`
rejects captured stdout or stderr overflow with `OutputLimitExceeded` naming
the command; it never returns partial captured output. `bounded.stream` gives
the caller stdout incrementally and drains stderr concurrently, retaining only
a capped prefix for diagnostics; stream stderr overflow does not raise.
Streaming pipe reads and writes share an elapsed deadline, and every context
exit reaps its tree, including early exits, exceptions and partial setup failures.
Whole-tree scans consume streaming records incrementally. Callers with an
overall deadline reserve `CLEANUP_SECONDS`.
`tests/test_process_lint.py` tracks import bindings, permits only the listed
subprocess exceptions/results/pipe constants, rejects OS and asyncio launch
access, multiprocessing/PTY imports, prohibited cross-module access and dynamic
imports, and gives no exemption based on a variable's name. It deliberately
does not infer module types for parameters, assigned aliases, computed
attributes or arbitrary factory results. `tools/run_tests.py` is the explicit
exception because its isolated workers already use jobs/process groups and
bounded cleanup.

The contract supplies one-line descriptions and exact file/test globs. It covers
`wiki.py`, `wikibuild/**`, `tools/**` and `tests/**`, including browser assets,
non-Python tools and shared fixtures. Publication owns the publish gate, rehearsal
and publication retention tests. Timing diagnostics are shared infrastructure;
their command and pipeline integration tests belong to CLI. Availability owns
the SteamCMD installer and its PowerShell tests.

## Enforcement

```powershell
py -3 tools/check_components.py
```

The stdlib checker inventories tracked and pending untracked files through Git.
Every in-scope file must have exactly one component. Each test glob must match an
existing file, and `depends_on` must name existing components without cycles.
Globs use case-sensitive, repository-relative POSIX paths with Python `fnmatch`
semantics. The AST check resolves absolute `wikibuild` imports, from-imports and
relative imports, including imports inside functions. It also checks local tool
imports and the existing bare sibling test-fixture imports.

Cross-component imports require a direct dependency. Existing exceptions are
specific source/target file pairs with reasons in `known_violations`. A repaired
or deleted import makes its exception stale and fails the check until that entry
is removed. New exceptions require review; do not regenerate this inventory to
silence a failure. Literal dynamic Python imports are checked too; non-literal
names require an explicit exception. JavaScript imports and subprocess calls
remain outside the AST check, so their integration tests remain necessary.

## Running tests

```powershell
py -3 tools/run_tests.py --list --changed main
py -3 tools/run_tests.py --changed
py -3 tools/run_tests.py --component gameplay presentation
py -3 tools/run_tests.py --all
py -3 tools/run_tests.py --all -j 1
```

`--changed [BASE]` defaults to `origin/main`. It combines `BASE...HEAD`, staged
and unstaged changes, and untracked files. Deleted and renamed paths retain
their impact. It selects owners and all transitive consumers. Recorded import
exceptions also select consumers, so the existing cycles can widen a run until
the boundary repairs below land. `--component` runs only the named owners;
`--all` selects every owner. `--list` prints modules and selection reasons without
executing; `--list --json` exposes the same plan to CI.

Documentation and `project.json` belong to workspace, whose foundation tests
read their committed contents and check links, anchors and the repository map.
Changes to `components.json`, either test tool, `.github/**`, `requirements*.txt`,
shared fixtures or package initializers select the full suite, as does any
unowned or ambiguous path. Literal dynamic project imports count as dependency
edges; imports with unknown names require an explicit known violation.
Literal relative dynamic imports resolve their `package` argument into edges;
unresolved project-module names fail the check.

Each Python module runs unittest in a separate Python process. Selected
`tests/*.ps1` scripts run through unittest workers with `pwsh` and
`-NoProfile -NonInteractive -File`, using a fixture directory from the shared API.
Tests can declare supported `sys.platform` values in their first ten lines, for
example `# HHWIKI-PLATFORMS: win32`. Unsupported tests report
`SKIP-UNSUPPORTED` and count as skipped before resolving platform tools.
The default concurrency is `os.cpu_count()`; `-j N` overrides it. Passing modules
produce a short result, failing output is printed in full, and the final table
sorts per-module wall times. Any failed module makes the command fail.
`--fail-fast` cancels pending modules after the first failure. Interruption and
failure-fast termination reap worker trees within five seconds using Windows
jobs or POSIX process groups before executor shutdown. Worker output goes to a
temporary file so inherited pipes cannot delay termination.

Tests create directories through `tests/_support.py`'s `fixture_dir(test, label)`,
which uses `os.mkdir` to inherit the parent's ACL and immediately registers test
or class cleanup. Tests never write inside the repository. The default root is
`<tempdir>/hhw`; each runner invocation owns a unique
`<tempdir>/hhw/<pid>-<8 hex>` parent, with private `w<N>` module roots supplied through
`HHWIKI_TEST_ROOT`, `TEMP`, `TMP` and `TMPDIR`. `remove_tree(path)` clears read-only
attributes and retries Windows sharing violations for up to five seconds;
cleanup failures fail the test, and the runner removes each worker root after
its module and scans only its own invocation parent for leftovers. Concurrent
runs never clean or inspect another invocation's fixtures. The resolved fixture
parent must be outside the checkout, including through junctions and symlinks.
Release fixtures copy a module-local Git
template, including `.git`; publication fixtures also copy their initial local
release. Every test owns a private mutable checkout.
Release fixtures share stable Git metadata query results until refs, config or
object directories change, and use a fixture-owned Git batch reader for revision
lookups. Cached checkout queries also inspect every visible file and the index
to detect edits, staging and deletions. Mutations and blob reads always execute;
the local publication host verifies blobs in one Git batch. Tests of later
releases copy completed release or publication baselines before making changes;
promotion-failure tests copy a checkpoint stopped after real preparation.
Cache stderr/stdin streams live in sibling fixture directories outside copied trees.
Paging scenarios use smaller catalogs and force the metadata-page threshold
independently of the real physical file budget.
Bare sibling fixture imports remain supported through the worker's `PYTHONPATH`.

CI keeps the workflow name `CI`. Pull requests run the component checker and
targeted tests against `origin/${{ github.base_ref }}`, with complete checkout
history. Pushes to `main` and `workflow_dispatch` run the full suite on Ubuntu
and Windows. Production runs on Windows, so on PRs the Windows job runs the same
affected selection as Ubuntu; tests declaring `win32` without `linux` run only
there. (`--windows-relevant` still narrows a selection to process, availability
and owners of Windows-only tests, for quick local runs.)
JavaScript checks invoked by Python test
modules retain their Node dependency and execution path, including the
`node --test` server contract; its wrapper reports a skip when Node is unavailable.

## Architecture review (2026-10-03)

This review describes the merged boundaries as inspected in this worktree.
[ACCEPTANCE.md](ACCEPTANCE.md) owns current status and proof limits.
[The document index](README.md) names each contract owner.

### Growth and boundaries

The project grew from local capture into a wiki pipeline and thirteen Pages
sites: one hub and twelve logical topics. Physical partitions can extend storage
without changing canonical ownership or historical URLs. The parent owns installed
input detection, capture and source stability. The wiki selects facts in place,
reconciles identity, builds readers and coordinates local releases.

These boundaries hold:

- `snapshots/` identifies inputs. `releases/` pins coordinated child commits and
  artifacts. `publications/` records verified deployments. The checkout lock only
  pins local children.
- Topic repositories own canonical content. The umbrella owns shared orchestration.
  Readers consume immutable artifacts rather than neighboring mutable checkouts.
- Update stops after the local release and both retention stages. Publication
  verifies topics before advancing the hub. It remains a separate gated command.
- Content exceptions remain distinct from execution failures. Unknown source and
  staging ownership cannot authorize overwrite or deletion.

### Findings and responses

PR numbers below come from local merge history. No live deployment was checked.

| Weakness found | Merged response | Owner and proof |
| --- | --- | --- |
| Routine updates could change live sites | PR #27 separated publication and added the production gate. Failed attempts require local abandonment before a fresh rehearsal. | [PUBLICATION.md](PUBLICATION.md#production-gate); `test_publish_gate.py`, `test_cli_publication.py` |
| Rehearsal could alter production refs or objects | PR #36, fixing #4 and #28, runs the engine in an OS-temp workspace with disposable shared clones and isolated Git configuration. It checks original refs, pins, object counts and publication state before removing owned temporary state and issuing a receipt. | `tools/rehearse_publication.py`, `publication_git.py`; `test_rehearsal.py` |
| A stuck wait could retain the writer lock | PR #33 supervises timeout cleanup, fences launches and reaps registered trees, owner metadata and command temporary files before exit 124. Diagnostics cannot extend the cleanup grace. | [PIPELINE.md](PIPELINE.md#run-timing-schema); `test_bounded.py`, `test_run_timing.py` |
| Children could outlive the caller | PR #33 registers Windows jobs and POSIX groups. PR #38, fixing #37, waits for whole-group exit instead of treating a sent signal as proof. It reports unresolved cleanup at the deadline. | `bounded.py`; `test_bounded.py` |
| Git scans or pipe reads could hang or truncate evidence | PR #41, fixing #8, routes launches through bounded capture or streaming I/O. Lineage walks share a deadline. The process lint tracks import provenance and rejects direct launch access within its documented scope. | [Process rule](#process-rule); `test_git_bounds.py`, `test_process_lint.py` |
| Failed staging attempts accumulated without ownership proof | PR #39, fixing #12, adds bounded attempt records and retirement. Retry retains one owned diagnostic attempt per stage, retires older abandoned attempts and preserves unknown ownership. | [RETENTION.md](RETENTION.md#failed-staging-attempts), `staging.py`; `test_extraction.py`, `test_history.py`, `test_reader.py`, `test_release.py` |
| Pages could queue a commit without starting jobs | PR #32 observes the exact attempt and permits one journaled same-tree successor within the original deadline and ref lease. | [Stuck Pages builds](PUBLICATION.md#stuck-pages-builds); `test_github_pages.py` |
| Timing mixed elapsed work with overlapping repository work | PR #31 records wall stages separately from repository sums and keeps timing outside immutable identities. PR #35 corrected timing-test assumptions. | [Timing schema](PIPELINE.md#run-timing-schema); `test_run_timing.py` |
| Imports and fixtures blurred stage ownership | PR #29 declares components and private fixture roots. The checker rejects new dependency violations and retains concrete exceptions until repaired. | `components.json`, `tools/check_components.py`, `tools/run_tests.py`; `test_architecture.py` |
| Documents and the registry disagreed with execution | This branch closes #21, #15 and #16 with one contract index, dated evidence and a stage graph checked against the fixed runner. | [Stage sequence](PIPELINE.md#stage-sequence); `test_foundation.py` |

### Complexity

The measured hotspots are `reader.build`, `pipeline.run`, `gameplay.graph`,
`tools/check_extraction.py::check`, `capacity_projection.build`,
`reader.validate_snapshot` and `guide_queries.py`.
Merged PR #39 centralizes staging lifecycle; PR #41 centralizes process and
streaming boundaries. Those repairs do not establish that these hotspots are gone.
PR #42 fixes #23/#24. It splits `reader.build` into `validate_bases`,
`inputs_changed` and `project_fonts`, and centralizes `pipeline.run`'s contract
construction in `contracts()`. Tests cover base validation, the complete font
inventory and failure journals that identify the helper's location.
PRs #44, #45 and #46 fix #26. `guide_queries.py` keeps its import point and
moves its query families into six `guide_query_*` modules. The remaining
functions shrink as follows (lines and cyclomatic complexity, before and after):

| Function | Before | After |
| --- | --- | --- |
| `gameplay.graph` | 297 / 199 | 62 / 23 |
| `check_extraction.check` | 186 / 121 | 23 / 10 |
| `capacity_projection.build` | 195 / 84 | 61 / 14 |
| `validate_snapshot` (now in `reader_validation.py`) | 92 / 69 | 24 / 11 |

Characterization tests pin their complete outputs and error messages.
Keep fact, history, no-op and failure assertions while moving responsibilities.

### Remaining work

No tracked architecture or complexity issue remains open. The remaining work is
the import repairs below.

The recorded import inventory has 51 exceptions. Exact pairs and reasons
live in `components.json`. Repair them by cause:

- Shared primitives sit too high: move extraction hashing into storage and generic
  publication Git preparation into the process owner.
- Lower owners read coordinator state: pass immutable allocation/inventory views
  to workspace and capacity. Remove reverse imports of release, publication and
  manifests. Let upper orchestration coordinate provisioning. PR #47 (#22)
  removed five of these exceptions.
- Physical projection reads presentation internals: extract a lower artifact
  contract from reader and release-content details.
- Stage benchmarks exercise pipelines: separate extraction/history and
  reader-retention/update measurement. Keep projection audits with release integration.
- Provider and lifecycle tests share consumer fixtures: split SteamCMD/CLI from
  process units, Steam provider cases from freshness integration, and external
  article units from consumer scenarios. Move capacity and entrypoint lifecycle
  scenarios into release integration with consumer-owned fixtures.
- Assertions cross feature owners: move coded-value/prefab semantics to identity,
  claim/page integration to reader, reader invalidation out of guide queries and
  publication backend cases out of Git ownership tests.

Remove an exception only after its forbidden import is gone. Preserve repeat,
interruption and historical-read assertions during every repair.

### Next growth steps

| Step | What it needs |
| --- | --- |
| More topics | Review ownership in `project.json`, add selected extraction and presentation contracts, regenerate navigation, and test relationships and placement. Keep one canonical owner per entity. |
| More game updates | Capture complete catalogs, reconcile schema and identity changes, preserve older revisions and URLs, and audit source values. Report unsupported content and verification limits. |
| More unattended updates | Keep operator invocation and the local release boundary. Exercise no-op, retry, process death and capacity behavior. Use isolated rehearsal for the separate publication step; no scheduler or automatic LLM stage is implied. |
