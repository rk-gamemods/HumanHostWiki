# Local release-staging retention

`wikibuild/release_retention.py` owns removal of duplicate release payloads under
`.local/rs/`. The normal `wiki.py update` calls it after supported publication
work, while holding the existing writer lock. It makes no network calls and
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
declared in a validated journal are candidates for removal; there is no recursive
directory deletion.

An interruption after some unlinks is safe to retry: committed copies remain,
and already absent staging files need no action. Completion records under
`.local/releases/retention/` bind the stage to its journal hash and release ID.
An unchanged repeat checks those records without Git reads or payload scans.
Cleanup counts stay in invocation metrics, so they cannot change release IDs
or generate new public commits. The operator report lists any cleanup issues
after the wiki content report. `.local/releases/retention/report.json` retains
their current reasons separately from content exceptions.

Failed preparation attempts without committed release receipts remain retained.
Reader candidates, extraction caches, identity model caches, test fixtures and
old diagnostic indexes are outside this cleaner's scope. Their retention policies
remain unfinished; removing them requires their own recovery and ownership proof.

Focused checks:

```powershell
py -3 -m unittest discover -s tests -p test_release_retention.py -v
py -3 -m unittest discover -s tests -p test_pipeline.py -v
```

The retention suite uses a real Git repository to verify conservation, no-op
repeats, independently detected changed bytes, pending transactions, path escape
and interrupted deletion. The full pipeline fixture verifies cleanup after
publication while content exceptions remain available for user direction.
