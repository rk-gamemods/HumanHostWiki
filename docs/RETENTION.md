# Local retention

## Committed release staging

`wikibuild/release_retention.py` owns removal of duplicate release payloads under
`.local/rs/`. The normal `wiki.py update` calls it after the local release,
while holding the existing writer lock. It makes no network calls and
does not alter child checkouts, Git history, source captures or public snapshots.

Before removing a payload, the cleaner requires a saved coordinated release
whose manifest matches the staging journal. It reads each repository's committed
tree and confirms that the referenced blob objects exist. It streams each staged
file in chunks of at most 1 MiB, comparing both its journal SHA-256 and its Git
blob identity. It validates the whole stage's deletion set before unlinking any
files, then checks file identity, size and modification time again immediately
before each unlink. Paths must stay within the stage without symlinks or junctions.

A pending release transaction prevents cleanup. Missing release receipts,
modified payloads, invalid paths and protected files remain available for
investigation. The cleaner never overrides protection. Unknown files, journals,
Git preparation indexes and path lists are retained. Only exact payload paths
declared in a validated journal are candidates for committed-payload removal;
this compaction never removes directories.

An interruption after some unlinks is safe to retry: committed copies remain,
and already absent staging files need no action. Completion records under
`.local/releases/retention/` bind the stage to its journal hash and release ID.
An unchanged repeat checks those records without Git reads or payload scans.
Cleanup counts stay in invocation metrics, so they cannot change release IDs
or generate new public commits. The operator report lists any cleanup issues
after the wiki content report. `.local/releases/retention/report.json` retains
their current reasons separately from content exceptions.

## Failed staging attempts

`wikibuild/staging.py` owns attempt records and retirement. Release, reader,
extraction and history staging attempts carry `attempt.json`
with their stage, attempt ID, creation time in UTC and state. Under the writer
lock, retry marks stale `materializing` attempts `abandoned`; cleanup keeps only
the most recent owned failed attempt of each stage for diagnosis and retires
every older one, even without a completed attempt. Current and completed
directories stay available. A crash leaves `materializing`; ordinary failures
and rollover proposals become `abandoned`.
Unknown or invalid ownership, including malformed JSON, is reported and preserved.
Retirement validates the literal stage root and its direct children before any
resolution, rejects symlinks and reparse points throughout the deletion tree,
and processes at most 100,000 entries per inventory or deletion tree. Files are
unlinked first; read-only protection is cleared only on single-link files. A
protected shared file that cannot be unlinked keeps its attempt and is reported.
Ownership records contain exactly `schema_version` (integer 1), `stage`,
`attempt_id`, `created_utc` and `state` (strings). Readers and writers reject
extra fields and non-scalar values. Reads and encoded writes are capped at
4 KiB; an oversized terminal write preserves the existing record.
Reader ownership stays outside promoted
candidate payloads; release ownership completes once the recovery journal is saved.

`tests/test_extraction.py`, `tests/test_history.py`, `tests/test_reader.py` and
`tests/test_release.py` cover repeat failure, ownership validation and retirement
at each stage. [ACCEPTANCE.md](ACCEPTANCE.md#current-engineering-limits) owns
the remaining engineering work.

## Retention scope and checks

Extraction caches, identity model caches, test fixtures and old diagnostic indexes
are outside this cleaner's scope. Removing them requires their own recovery and
ownership proof. Tests own their cleanup under [ARCHITECTURE.md](ARCHITECTURE.md#running-tests).

Focused checks:

```powershell
py -3 -m unittest discover -s tests -p test_release_retention.py -v
py -3 -m unittest discover -s tests -p test_pipeline.py -v
```

The retention suite uses a real Git repository to verify conservation, no-op
repeats, independently detected changed bytes, pending transactions, path escape
and interrupted deletion. The full pipeline fixture verifies cleanup after the
local release while content exceptions remain available for user direction.

## Immutable reader files

`wikibuild/reader_retention.py` shares identical files across completed candidates
under `.local/readers/`. The normal update invokes it after the local release and staging
cleanup, under the same OS-held writer lock. Every candidate path remains available
for historical previews, audits and release recovery. No Git tree, accepted fact,
source snapshot or public file is changed. This reduces duplicate storage without
evicting unique candidate content.

Before sharing, it checks candidate identity, exact file membership, regular paths,
declared sizes and streamed SHA-256 values. An invalid candidate is retained in full
and excluded from sharing. Symlinks and Windows junctions are rejected. File reads
use chunks of at most 1 MiB; metadata reads are capped at 8 MiB. A candidate whose
metadata exceeds that bound is retained and reported. Already shared inodes are
hashed once per pass. Windows requires explicit file stats because directory-entry
stats omit the identity needed for this check.

Each duplicate is replaced atomically with a hard link to verified identical bytes
in another immutable candidate. The compactor rechecks file identity, size, mode
and modification time before replacement. It never writes through shared inodes or
links to editable repository files. All reader writers must continue to replace
files or build a new candidate, never edit candidate bytes in place. This is the
same immutability contract used by the reader's observation-only projection path.

An interruption leaves a complete original or a complete shared file. Temporary
links live under `.local/reader-retention/links/`; retry accepts a leftover only if
it is still a hard link to the selected verified source inode. Unknown temporaries,
protected files and filesystems without hard-link support are preserved and
reported. File sharing never overrides protection or recursively deletes candidates.

The completion receipt binds the compactor version and every candidate manifest
hash. An unchanged repeat reads only metadata, with no payload scan or replacement.
This receipt is a housekeeping optimization, not a reader-integrity certificate:
normal reader verification still checks content on reuse. A new or changed manifest
invalidates the receipt; source bytes are verified again before further sharing.
Metrics and cleanup issues remain separate from content exceptions and public
release identity. Issues are also saved in `.local/reader-retention/report.json`.

```powershell
py -3 -m unittest discover -s tests -p test_reader_retention.py -v
py -3 tools/benchmark_reader_retention.py
```

The benchmark runs the normal wiki update, hashes actual candidate files before
and after independently of the compactor, and measures an immediate cleanup repeat.
It writes ignored evidence and the final operator report under `.local/`. Reported
unique-inode bytes are file lengths, not filesystem allocation or free-disk space.
Retention of unique obsolete cache content remains open.
