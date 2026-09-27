# Local workspace workflow

Run these commands from the `HumanHostWiki` umbrella directory. Python 3.11+
and Git are the only foundation dependencies. No packages are installed.

These are current foundation/development commands. The
[target update workflow](adr/0001-versioned-public-wiki.md#6-refresh-build-and-coordinated-release)
starts when an operator invokes the decompile command and completes supported work
through publication, including capacity management, without intermediate input.
That integration is not implemented yet. At completion the operator presents
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
implemented stages from later gameplay generation and publication work.

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
Do not use `git add -f` to override either boundary. Future release coordination
will pin child commits in a release manifest; Git submodules are not used.

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

To capture newly installed game files, use the parent's existing command first:

```powershell
pwsh -NoProfile -File ../tools/Decompile-GameCode.ps1
py -3 wiki.py refresh
```

That separate capture may be expensive and follows the parent's recovery rules.
The wiki command never invokes it implicitly. The current source generator does
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

They do not establish correctness of unimplemented gameplay adapters, historical
identity matching or remote publication. The ADR lists their acceptance gates.

Git for Windows can mark synthetic test object files read-only. Test cleanup uses
ordinary removal and reports any protected fixtures retained under
`.local/test-runs/`; it does not change attributes or force removal. These small
ignored fixtures are separate from the real game dataset.
