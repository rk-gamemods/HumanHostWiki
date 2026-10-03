# Component boundaries and test runs

[`components.json`](../components.json) owns local Python/tool/test boundaries.
The product architecture remains in [ADR-0001](adr/0001-versioned-public-wiki.md),
and `project.json` owns pipeline stages and topic repository identities.
Components follow those stage owners and the actual imports. A feature should
usually change one or two owners; shared primitives belong below stage orchestration.

| Component | Allowed direct dependencies |
| --- | --- |
| storage | None |
| process | storage |
| source | storage |
| extraction | storage, source, test-support |
| identity | storage, source, extraction |
| presentation | None |
| gameplay | storage, source, extraction, identity, presentation |
| curation | storage, source, extraction, identity |
| availability | storage, process |
| external-links | storage |
| capacity | storage, extraction, presentation, external-links |
| workspace | storage, source, capacity, external-links, test-support |
| reader | storage, source, extraction, identity, gameplay, curation, presentation, availability, external-links, workspace |
| release | storage, process, source, extraction, reader, capacity, workspace, external-links, presentation |
| publication | storage, process, release, capacity, workspace, reader, test-tooling |
| cli | All other production components |
| test-support | None |
| test-tooling | test-support |

The contract supplies one-line descriptions and exact file/test globs. It covers
`wiki.py`, `wikibuild/**`, `tools/**` and `tests/**`, including browser assets,
non-Python tools and shared fixtures. Publication reserves `publish_gate.py`
and `tests/test_publish*.py` for the concurrent gate work.

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
silence a failure. Dynamic imports, JavaScript imports and subprocess calls are
outside the AST check; their integration tests remain necessary.

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

Documentation-only changes select no tests. Changes to `components.json`, either
test tool, `.github/**`, `requirements*.txt`, or any other unowned/ambiguous path
select the full suite. Shared fixture changes select their consumers.

Each module runs as `python -m unittest <module>` in a separate process. The
default concurrency is `os.cpu_count()`; `-j N` overrides it. Passing modules
produce a short result, failing output is printed in full, and the final table
sorts per-module wall times. Any failed module makes the command fail.

Each module receives a short private temporary root under `.local/`, via
`HHWIKI_TEST_ROOT`, `TEMP`, `TMP` and `TMPDIR`. `tests/_support.py` redirects the
three fixtures that otherwise use checkout-local parents. Other fixtures already
use random temporary directories and local servers bind ephemeral ports. Bare
sibling fixture imports remain supported through the worker's `PYTHONPATH`.
Cleanup uses ordinary removal and reports protected leftovers without overriding
file protection.

CI keeps the workflow name `CI`. Pull requests run the component checker and
targeted tests against `origin/${{ github.base_ref }}`, with complete checkout
history. Pushes to `main` and `workflow_dispatch` run the full suite. The Windows
job runs the process component (`tests.test_bounded`) when a PR selects it and
always on main or manual dispatch. JavaScript checks invoked by Python test
modules retain their Node dependency and execution path.

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
