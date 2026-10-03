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

The process runtime in `wikibuild/bounded.py` owns every external child through
a registered Windows job or POSIX process group, with shutdown fencing and
bounded tree cleanup. Git and other command launches use `bounded.run` for
captured output or `bounded.stream` for binary streaming, with an explicit
operation timeout and a one-line reason beside its constant. Streaming pipe
reads and writes share an elapsed deadline, stderr drains concurrently with a
size cap, and every context exit reaps its tree, including early exits and
exceptions and partial setup failures. Captured stdout or stderr overflow raises
`OutputLimitExceeded` naming the command; partial output is never returned.
Whole-tree scans consume streaming records incrementally. Callers with an
overall deadline reserve `CLEANUP_SECONDS`.
`tests/test_process_lint.py` resolves import/assignment aliases and rejects
subprocess, OS, asyncio, multiprocessing and PTY launch routes outside this
owner; `tools/run_tests.py` is the explicit exception because its isolated
workers already use jobs/process groups and bounded cleanup.

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

## Planned boundary repairs

The initial inventory has 56 concrete import exceptions. Their exact file pairs
and individual reasons live in `components.json`; these repairs explain the groups:

- Move extraction's `file_hash` primitive into storage so generic Git transactions
  do not depend on extraction.
- Pass immutable allocation/inventory inputs into workspace and capacity checks;
  remove their reverse imports of release, publication and workspace manifests.
- Extract a lower-level artifact contract for capacity projection instead of using
  reader and release-content internals.
- Let the pipeline coordinate publication provisioning around local releases;
  move generic publication Git primitives into the process owner.
- Separate full-pipeline benchmark entrypoints from extraction and reader-retention
  stage measurements. Keep complete projection audits with release integration.
- Split CLI deadline and SteamCMD cases from generic process tests.
- Separate Steam availability provider units from pipeline/reader freshness cases.
- Move capacity-release and entrypoint lifecycle scenarios into release integration
  modules, preserving their repeat, interruption and publication assertions.
- Separate external article provider units from pipeline/reader/capacity/release
  integration, with fixtures owned by their consumer.
- Move semantic-model assertions in coded-value and prefab tests into identity.
- Separate curation claim units from reader/page integration; move reader
  invalidation checks out of guide-query units.
- Move publication backend cases from Git ownership tests into publication.

This unit records those repairs without changing production behavior or assertions.
