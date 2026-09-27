# Capacity allocation

The [ADR](adr/0001-versioned-public-wiki.md#5-storage-and-presentation) requires
automatic file, site and history budgets while preserving logical topic ownership
and historical URLs. The allocator and committed-input measurement are implemented.
Release projection, repository rollover and publication integration remain unfinished;
the normal update does not yet allocate physical partitions.

## Owners and inputs

`wikibuild/capacity.py` accepts metadata and returns a deterministic placement plan.
It performs no file, Git or network operations. Each artifact has a logical topic,
immutable relative path, SHA-256 and byte size. A placement identifies its physical
repository. Existing placements never move. Sealed or over-budget repositories
can serve existing objects but receive no new ones.

New objects use first-fit decreasing placement within their topic. Git blob payloads
are charged once per physical repository; distinct public paths each consume site
capacity. Repository IDs and GitHub names use numbered suffixes and skip collisions.
The plan hashes its inputs and records every reused and newly allocated location.
An unchanged replay preserves placements and creates no repositories.

`wikibuild/capacity_inventory.py` reads ownership from pinned release commits under
the workspace writer lock. It measures unique reachable Git objects from the
released source and published Pages commits, including removed files. It excludes
unrelated local branches and abandoned preparation objects. The measurement streams
object metadata without decoding payloads. Invalid revisions fail explicitly.

Default budgets are 32 MiB per file and 800 MiB each for site and uncompressed
reachable Git history, with 16 MiB reserved in each repository for control metadata
and Git tree/commit growth. These are implementation defaults, not platform limits.
The allocator rejects oversized new objects; the generating owner must split them
before allocation. Existing immutable content remains reusable after a budget change.

## Integration contract

Release projection must allocate leaf objects before resolving and hashing their
parent references. It must preserve prior locations and write only new objects.
The release journal owns new repository identities, staged files, prepared commits
and the route changes that depend on them. Publication must verify new storage
targets before promoting any route that advertises them.

Blob estimates alone do not prove capacity. Before promotion, the release writer
must measure the final prepared Git history and public tree, including control
files. Mutable entrypoints, release indexes and ownership manifests also need bounded
storage and rollover. A full partition must remain readable while later writes
use another partition. Moving only data packs does not satisfy the ADR.

Required integration proof includes forced thresholds, interrupted preparation and
publication, retained historical URLs, oversized-index splitting and a repeat that
creates no files, commits or repositories. Until those checks pass through the normal
entrypoint, automatic capacity management remains incomplete.

## Current validation

Run from the umbrella directory:

```powershell
py -3 -m unittest discover -s tests -p 'test_capacity*.py' -v
py -3 tools/check_capacity.py
```

The diagnostic reads the current committed inventory, checks unchanged placement,
then rehearses allocation from empty repositories using 1 MiB files, 2 MiB sites
and 4 MiB histories with 128 KiB reserves. It verifies conservation, topic ownership,
budgets and replay. It creates no payload copies, partitions or remotes. Its Python
peak-memory measurement excludes native Git child processes. This is allocator
evidence, not an end-to-end capacity acceptance test.
