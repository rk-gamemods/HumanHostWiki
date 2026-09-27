# Local workspace workflow

Run these commands from the `HumanHostWiki` umbrella directory. Python 3.11+
and Git are the foundation dependencies. Publication also uses the authenticated
GitHub CLI. No Python packages are installed.

These are current foundation/development commands. The
[target update workflow](adr/0001-versioned-public-wiki.md#6-refresh-build-and-coordinated-release)
starts when an operator invokes the decompile command and completes supported work
through publication, including capacity management, without intermediate input.
The entrypoint now runs capture, registration, selected extraction, identity and
the validated reader, coordinated local Git release and configured Pages publication. The
[runner contract](PIPELINE.md) defines receipts and recovery. At completion the operator presents
unresolved wiki exceptions and requests direction; execution failures are separate.
The manual examples below are foundation diagnostics, not extra maintenance steps.

## Inspect and validate

```powershell
py -3 wiki.py validate
py -3 wiki.py status
py -3 wiki.py plan
py -3 wiki.py map --check
```

`validate` checks registry ownership, paths, relationship targets, publication
settings, pipeline order and any existing checkout identities. Absent topic
repositories are reported as absent. Dirty repositories are reported as dirty;
the command does not commit, clean or reset them. Unknown existing directories
fail validation rather than being adopted. `plan` explicitly distinguishes
implemented stages from unfinished gameplay interpretation and verification work.

Edit `project.json` to change repository declarations, then regenerate the map:

```powershell
py -3 wiki.py map
```

## Initialize independent child repositories

```powershell
py -3 wiki.py init-repositories
```

This creates the declared local checkouts on `main`, each with an identity
marker, README and ignore/line-ending settings. It creates no remotes and makes
no commits. It stages each new checkout under `.local/repository-stage/` before
moving it into its final path. Repeating the command preserves existing content.
Review and commit new seed files inside their owning child repository. The
initial project setup has already performed those baseline local commits.

Pin reviewed, clean child commits and check them with:

```powershell
py -3 wiki.py lock
py -3 wiki.py check-lock
```

`workspace.lock.json` records the registry hash and every child commit. It lets
the umbrella detect checkout drift without pretending that a set of seed commits
is a verified gameplay release. Both commands refuse dirty or missing children.

Children are ignored by the umbrella. The umbrella is ignored by HumanHostMods.
Do not use `git add -f` to override either boundary. The release coordinator
pins child commits in a release manifest; Git submodules are not used.

## Register an existing source snapshot

```powershell
py -3 wiki.py refresh
```

The default input is the sibling `../HumanHostCodebase`, owned by the existing
decompiler. `--source <path>` selects another clean independent local snapshot.
Registration reads pinned metadata and blob identities from Git. It copies no
game assets, source tree, reference index or raw catalog. It refuses a source
remote, dirty snapshot, wrong game or unsupported catalog schema. The resulting
small `snapshots/<snapshot-id>.json` is an **input receipt**, not a wiki release.
An unchanged repeat leaves the receipt bytes unchanged.

To capture newly installed game files and run supported wiki work:

```powershell
pwsh -NoProfile -File ../tools/Decompile-GameCode.ps1
```

Capture may be expensive and follows the parent's recovery rules. The wrapper
also invokes wiki processing when capture is unchanged. The wiki commands never
invoke capture implicitly. To rerun only wiki processing against the existing
capture, use `py -3 wiki.py update --operator-report`. The current source generator does
not provide the game's display version, so the receipt records it as unknown.

## Extract selected facts

```powershell
py -3 wiki.py extract
```

This development command registers the pinned existing source and extracts the
implemented contracts across the registered topics. It reads selected records,
resolves English item/skill names and records exact field evidence. Media, unrelated fields and raw code
are excluded. New fields produce grouped wiki exceptions while known fields and
independent records continue. Missing required input files or malformed records
are execution failures, not successful content exceptions.

The JSON result names the content-addressed records and exception report under
`.local/extractions/`. It reports partial coverage by topic and does not claim
a wiki release or runtime verification. The last-success pointer advances only
after all output hashes validate. Rerunning validates and reuses complete output;
modified output is refused. An unrelated source commit reuses facts when every
selected dependency is unchanged. Previously absent dependencies are rechecked.

See [extraction contracts](EXTRACTION.md) for extension points and
[implementation evidence](IMPLEMENTATION.md) for unfinished delivery gates.

Check selected real-source facts independently and measure an isolated fresh run:

```powershell
py -3 tools/check_extraction.py
py -3 tools/benchmark_extraction.py
```

The benchmark retains its generated cache under `.local/benchmarks/`; it reads the
existing source in place. It verifies unchanged output bytes and pointer timestamps.
Its peak-memory figure covers the Python process and excludes the Git subprocess.

## Reconcile selected identities

```powershell
py -3 wiki.py normalize
py -3 tools/check_history.py
py -3 tools/benchmark_extraction.py --identity
```

`normalize` registers and extracts the current source, then reconciles selected
observations with the durable ledger under `identity/`. It preserves ambiguous
matches and logs unresolved relationships while supported records complete.
The independent checker verifies observation conservation, facts, evidence,
semantic hashes and canonical target references against the pinned source.

Immutable run/state files and `identity/latest.json` are durable decision history.
The generated `.local/history/` model is rebuildable staging. Missing staging is
reconstructed from frozen decisions; modified staging is preserved and refused.
A repeated older request cannot rewind a later decision chain. For reviewed
corrections and rule ownership, see [identity contracts](IDENTITY.md).

This command currently processes the current source commit. Older captured game
builds without a catalog require explicit uncaptured status; current asset facts
cannot establish what those builds contained. Historical registration remains
unfinished. No identity run grants gameplay verification.

## Build and inspect the selected-fact reader

```powershell
py -3 wiki.py reader
py -3 tools/check_reader.py
py -3 tools/benchmark_reader.py
py -3 tools/serve_reader.py
```

The reader consumes the latest accepted identity run for each normalized snapshot
in the decision chain. It stages a complete candidate under `.local/readers/`,
validates ownership, semantic hashes, search membership and cross-topic targets,
then updates `.local/reader-latest.json`. Existing files must match recorded hashes;
unknown or changed files are preserved and refused. A repeat reuses the candidate.

The local server binds only `127.0.0.1`, prints its chosen URL and runs until stopped
with Ctrl+C. It pins the candidate selected at startup. Restart it after rebuilding
to inspect a newer candidate. Optional `--candidate <id>` selects retained output;
`--port <number>` chooses the port. Entry routes use the same `404.html` fallback
contract expected on Pages. Group pages are ordinary static files.

The browser supports topic search, entry evidence, reverse relationships and a
captured-version selector. A missing historical entry is explicit; it never
substitutes current data. The real dataset currently has one normalized game build.
Two-build navigation and removal behavior have also been exercised with fixtures.
`tools/check_reader.py` independently compares every selected model with emitted
facts, provenance, search records and reverse links. It does not import the renderer.

The benchmark retains its isolated candidate under `.local/rb-*/`, reads existing
selected models in place and checks byte/pointer stability. Its reported memory
covers the Python process. Reader candidates do not create child commits, remote
repositories, verification badges or wiki releases. See [reader contracts](READER.md).

## Inspect the coordinated Git release

For the coordinated Git release, `wiki.py update` commits validated generated
content to every child and updates the checkout lock automatically. Inspect the
release manifest under `releases/` and run `py -3 tools/serve_release.py` to preview
the committed content locally. The preview substitutes local origins; it does not
deploy the configured URLs. [RELEASE.md](RELEASE.md) owns recovery and retention.

```powershell
py -3 tools/check_release.py
py -3 tools/benchmark_release.py
py -3 tools/serve_release.py
```

The independent checker compares committed blobs with the candidate and verifies
that retained release indexes, packs and runtimes remain reachable. The benchmark
runs an unchanged `wiki.py update` and checks child commits, output bytes and
timestamps. It requires an already completed release for the current inputs.

The normal update applies [storage capacity allocation](CAPACITY.md) before
committing and publishing. New physical repositories retain their logical topic
owner, appear in the release manifest and checkout lock, and publish before their
dependent entrypoints. Optional byte limits and reserves live in
`project.json.capacity`; no separate allocation command is needed for maintenance.
Oversized snapshot pack-reference lists, release capture lists and ownership manifests
split automatically. Full entrypoint rollover and indivisible control records remain
unfinished; those cases fail before promotion if their budgets are exceeded.

## Publish or resume a release

Publication is enabled in `project.json` and runs during `wiki.py update`.
`py -3 wiki.py publish` resumes only the latest local release without recapturing
game inputs. It provisions configured repositories, audits outgoing history,
verifies topic deployments and advances the hub last. Completed publication
receipts live in `publications/`; incomplete work lives in `.local/publication/`.
See [publication recovery](PUBLICATION.md) for interrupted pushes and hub rollback.

## Build the architecture preview

```powershell
py -3 wiki.py build
# Optional: use an ID returned by refresh for an input-provenance banner.
py -3 wiki.py build --snapshot build-25548639-9d77a0415918
```

Output is under `.local/builds/<input-and-tool-hash>/`. Open the `index.html`
path printed by the command. It includes the hub, all topic landing pages and
their relationships. Empty-topic status is explicit. This preview has no
gameplay articles, version selector, search or public deployment.

All internal links are checked before promotion. A repeat with unchanged inputs
reuses byte-identical output. Modified output is rejected, not overwritten.
`.local/preview.json` selects the last successful preview and is replaced only
after every output file is complete. Changing templates produces a new build
directory so earlier previews remain available.

## Failure and recovery

- **Pipeline execution failure:** inspect the reported `.local/pipeline/failures/`
  receipt. It lists completed stages and the failing stage separately from content
  exceptions. Repair the execution problem and rerun the same command. The prior
  pipeline success and prepared stage artifacts remain available.
- **Another writer:** the OS lock releases when the process exits. Do not delete
  the persistent lock file to bypass a live writer.
- **Dirty source/child:** inspect its Git status and resolve useful work in that
  repository. No command stashes, resets or deletes it.
- **Unknown checkout:** verify ownership and reconcile its marker deliberately;
  do not overwrite the directory or assume it is disposable.
- **Interrupted initialization/build:** earlier checkouts/previews remain intact.
  Repeat the command. Incomplete staging stays under `.local/` for inspection;
  no staging directory counts as a completed build.
- **Receipt collision:** investigate the provenance mismatch. Registering an
  existing identity may not overwrite different receipt content.
- **Corrupt preview:** inspect the reported build directory and preserve useful
  evidence. Explicitly remove only the verified generated output after checking
  its absolute path; then rebuild. File protection is not bypassed.

There is no automatic garbage collection. Old local previews can be removed
after confirming none is selected or in use. Published historical revisions and
source snapshots require a separate retention decision.

## Tests and scope of proof

```powershell
py -3 -m unittest discover -s tests -v
py -3 wiki.py validate
py -3 wiki.py map --check
git diff --check
```

The tests cover ambiguous ownership, path escapes, pipeline cycles, missing
relationship targets, independent repository boundaries, repeat initialization,
input provenance/schema/dirty-state failures, receipt collisions, internal links,
no-op builds, writer exclusion and failure before preview promotion. They use
small synthetic local Git repositories. A real input registration and repeated
preview build complement those tests during initial setup.

Identity tests cover source-ID changes, renames, reused IDs, split/merge ambiguity,
reviewed mappings, revision reuse, removals, capture gaps and interrupted writes.
Publication tests cover independent topic completion, interrupted pushes, hub
rollback, retained history and rejection of changed remote refs. Live publication
and browser evidence are recorded in [IMPLEMENTATION.md](IMPLEMENTATION.md).
These checks do not establish correctness of unimplemented gameplay adapters or
real cross-build identity continuity. The ADR lists those remaining gates.

Git for Windows can mark synthetic test object files read-only. Test cleanup uses
ordinary removal and reports any protected fixtures retained under
`.local/test-runs/`; it does not change attributes or force removal. These small
ignored fixtures are separate from the real game dataset.
