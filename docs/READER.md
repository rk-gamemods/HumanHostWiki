# Static reader contract

The reader consumes pinned normalized runs and input receipts. It never reads the
game catalog, invokes an LLM or grants a gameplay verification badge. Its output is
a validated release candidate under `.local/readers/`; promotion to topic Git
repositories and coordinated publication remain the release coordinator's job.

| Owner | Responsibility |
| --- | --- |
| `wikibuild/reader.py` | Pin history, partition selected records, validate artifacts and atomically select a complete candidate |
| `wikibuild/pages.py` | Pure HTML/Markdown presentation and safe links |
| `wikibuild/web/reader.js` | Version selection, bounded topic search, grouped records, entry navigation and provenance |
| `wikibuild/web/reader.css` | Responsive presentation without external fonts, scripts or services |

Each topic has one reader shell and grouped Markdown for Git navigation. Semantic
revisions, provenance and entry/search records live in content-addressed JSON
packs. Unchanged packs are shared across snapshots. A snapshot index names exact
packs and identity runs. The browser loads only the selected topic/version and
requested group or entity shard. Source code and the source asset index are never
reader inputs. Compact asset identifiers and evidence locators remain visible.

The renderer uses standard-library Python and native browser APIs. It adds no
framework dependency or server/database requirement. Links carry snapshot and
candidate identity. The `/entry/<entity-key>/` route uses the shared static-site
fallback shell, avoiding a generated document per Unity object. GitHub Pages
supports a [custom `404.html`](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-custom-404-page-for-your-github-pages-site);
deployment verification must test the rendered
route as well as ordinary static files. Group navigation remains at real paths.

The last-success pointer changes only after output manifests, semantic hashes,
snapshot membership and link targets pass. Existing candidate files must match
their recorded hashes exactly. Unknown files are refused, never overwritten.
The caller holds the shared writer lock. Interrupted staging is ignored; complete
candidates can be validated and reused. Nothing here deletes historical output.
New local cache directories use the first 24 hexadecimal hash characters to keep
Windows paths short; full identities remain in manifests and pointers. A prefix
collision fails the full-identity check. Existing full-hash directories remain
supported. Both staging and final file paths must fit Windows path capacity.

Tests must cover two snapshots, additions/removals/uncaptured states, unchanged
revision reuse, cross-topic links retaining the selected snapshot, explicit gaps,
bounded shard splitting, escaping hostile labels, changed/unknown output and
failure before promotion. A real browser check must exercise search, version
selection, entry links and readable selected facts. Public release verification,
capacity-driven repository allocation, curated claims and external-link checking
remain separate completion gates.
