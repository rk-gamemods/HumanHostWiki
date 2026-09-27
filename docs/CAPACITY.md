# Capacity allocation

The [ADR](adr/0001-versioned-public-wiki.md#5-storage-and-presentation) requires
automatic file, site and history budgets while preserving logical topic ownership
and historical URLs. Allocation, committed-input measurement and immutable reference
projection are implemented and connected to the normal release and publication
stages. The update creates storage partitions as immutable objects fill existing
repositories. Rollover of the logical entrypoints and oversized control metadata
remains unfinished, so automatic capacity handling does not yet cover every ADR case.

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

`wikibuild/capacity_projection.py` plans reader data packs and runtimes first,
then snapshot indexes, then release configurations. Each phase resolves references
to its allocated dependencies before hashing the containing object. Logical routes,
snapshot membership and facts stay unchanged. References to another physical site
use absolute URLs; references in the original repository retain their existing bytes.
The browser must continue resolving relative references against the original logical
topic base, even when a configuration or index lives in another physical repository.

`wikibuild/release_content.py` owns snapshot/configuration transformations for both
normal release writing and capacity projection. It rewrites only declared pack
references. Evidence paths and strings inside facts are not URL rewrite targets.
Projection verifies the candidate, retains leaf paths instead of bytes, and holds
only transformed metadata. Its write iterator yields one new payload at a time,
rechecks its hash and skips reused files. Planning creates no destination files.

`wikibuild/physical.py` derives the physical registry from configured topic names.
`project.json` retains logical ownership; each release's `physical` map records
allocated repository IDs, logical topics, ordinals and sealed state. The checkout
lock includes all those repositories. Commands inspecting workspace state resolve
this map through the current immutable release manifest.

`wikibuild/release_output.py` owns generated files and their allocation membership.
Existing ownership records remain readable. New records distinguish allocated
objects from small entrypoint references, avoiding duplicate ownership when a
release configuration moves to another repository. Unchanged storage partitions
retain their exact files and commits, including their earlier ownership receipt.

`wikibuild/release_partitions.py` prepares new Git repositories in private staging.
The release journal records seed identities before installing them at their final
paths. Retry accepts the recorded staged or installed state, preserves unknown
destinations and resumes the exact prepared commits. Source and Pages objects are
pinned with local refs before promotion. Publication provisions the generated
repository names and verifies storage sites before topic entrypoints, then the hub.
The browser follows hashed configuration references while retaining its logical
base for relative paths and historical navigation.

Before promotion, the release writer checks changed file sizes, final public tree
bytes and the unique Git objects reachable from the prepared source and Pages
commits. If an earlier pending publication finishes after preparation, publication
rebuilds the Pages parent and repeats the history check before pushing. A failed
budget check leaves the prior release selected and reports an execution failure.
Configure byte limits and reserves through the optional `project.json.capacity`
object, using the field names in `capacity.Budgets`.

Mutable entrypoints, release indexes and ownership manifests still need bounded
storage and rollover. Oversized control files currently fail before promotion;
they are not automatically split. Full immutable storage partitions remain readable,
but a full logical entrypoint still requires the unfinished rollover path. These
limitations keep complete automatic capacity acceptance open.

Forced-threshold integration tests cover new local repositories, installation
interruption, publication dependency order/failure, retained historical URLs and
no-op replay. They use real Git objects and a deterministic host adapter. Real
GitHub overflow provisioning, oversized-index splitting and entrypoint rollover
remain acceptance gaps.

## Current validation

Run from the umbrella directory:

```powershell
py -3 -m unittest discover -s tests -p 'test_capacity*.py' -v
py -3 tools/check_capacity.py
py -3 tools/check_capacity_projection.py
```

The diagnostic reads the current committed inventory, checks unchanged placement,
then rehearses allocation from empty repositories using 1 MiB files, 2 MiB sites
and 4 MiB histories with 128 KiB reserves. It verifies conservation, topic ownership,
budgets and replay. It creates no payload copies, partitions or remotes. Its Python
peak-memory measurement excludes native Git child processes. This is allocator
evidence, not an end-to-end capacity acceptance test.

The projection diagnostic follows planned physical URLs and compares their bytes,
snapshot fields, pack membership and runtime hashes independently against the real
reader candidate. It checks both current placement and forced budgets, then verifies
that replay yields no writes. Small tests additionally materialize two releases in
temporary physical directories and verify that both remain readable. These checks
do not exercise provisioning, Git promotion, Pages publication or entrypoint rollover.

`tests/test_capacity_release.py` exercises the integrated Git/provisioning boundary
with a host adapter. `tests/test_release_browser.py` runs the actual loader in Node.js
with native URL and SHA-256 APIs, covering configuration references, mismatched bytes,
release identity, namespace containment, coordinated selection and local preview.
Node.js is a test dependency only; generation still uses Python's standard library.
