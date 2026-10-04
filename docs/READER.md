# Static reader contract

The reader consumes pinned normalized runs and input receipts. It never reads the
game catalog, invokes an LLM or grants a gameplay verification badge. Its output is
a validated release candidate under `.local/readers/`; promotion to topic Git
repositories and coordinated publication remain the release coordinator's job.

| Owner | Responsibility |
| --- | --- |
| `wikibuild/reader.py` | Pin history, partition selected records, validate artifacts and atomically select a complete candidate |
| `wikibuild/curation.py` / `curated_rules.py` | Check committed authored explanations and retain scoped results; see [CURATED.md](CURATED.md) |
| `wikibuild/external_links.py` | Match selected search metadata against pinned external article observations; see [EXTERNAL_LINKS.md](EXTERNAL_LINKS.md) |
| `wikibuild/pages.py` | Pure HTML/Markdown presentation and safe links |
| `wikibuild/web/reader.js` | Version selection, bounded topic search, grouped records, entry navigation and provenance |
| `wikibuild/web/reader.css` | Responsive presentation without external fonts, scripts or services |

Each topic has one reader shell and grouped Markdown for Git navigation. Semantic
revisions, provenance and entry/search records live in content-addressed JSON
packs. Unchanged packs are shared across snapshots. A snapshot index names exact
packs and identity runs. The browser loads only the selected topic/version and
requested group or entity shard. Source code and the source asset index are never
presentation inputs. The optional explanation checker reads only its declared
captured code dependencies and passes hashes to the presentation layer. Compact
asset identifiers and evidence locators remain visible.

During release, [capacity projection](CAPACITY.md) can replace oversized lists of
pack references with hashed directory pages. The runtime selects matching branches
for entry/provenance lookup and loads search directories sequentially. It continues
to read flat indexes from earlier releases. Directory support is declared in the
candidate's reader features so new metadata cannot be paired with an older runtime.

Release configurations also page large capture lists through the
[capture catalog contract](CAPACITY.md). The default capture remains inline.
Opening an older snapshot reads its exact catalog record; the version selector
and entry history load additional choices only when requested. A failed history
batch can retry from the same position without changing the selected snapshot.

The renderer uses standard-library Python and native browser APIs. It adds no
framework dependency or server/database requirement. Diagnostic links carry snapshot
and candidate identity. Committed sites carry snapshot and coordinated release
identity; the [release loader](RELEASE.md) selects that release's immutable runtime
and indexes. The `/entry/<entity-key>/` route uses the shared static-site
fallback shell, avoiding a generated document per Unity object. GitHub Pages
supports a [custom `404.html`](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-custom-404-page-for-your-github-pages-site);
deployment verification must test the rendered
route as well as ordinary static files. Group navigation remains at real paths.

The last-success pointer changes only after output manifests, semantic hashes,
snapshot membership and link targets pass. Existing candidate files must match
their recorded hashes exactly. Unknown files are refused, never overwritten.
The caller holds the shared writer lock. Interrupted staging is ignored; complete
candidates can be validated and reused. Nothing here deletes historical output.
The configuration pins [Steam availability evidence](AVAILABILITY.md) separately
from snapshot facts. A change only to this evidence reuses validated immutable
packs through hard links and skips model projection. Shared files are never edited
in place; controls and reference links receive new files in private staging.
The normal update also shares verified identical files across existing candidates
under the [local retention contract](RETENTION.md#immutable-reader-files).
New local cache directories use the first 24 hexadecimal hash characters to keep
Windows paths short; full identities remain in manifests and pointers. A prefix
collision fails the full-identity check. Existing full-hash directories remain
supported. Both staging and final file paths must fit Windows path capacity.

Tests must cover two snapshots, additions/removals/uncaptured states, unchanged
revision reuse, cross-topic links retaining the selected snapshot, explicit gaps,
bounded shard splitting, escaping hostile labels, changed/unknown output and
failure before promotion. A real browser check must exercise search, version
selection, entry links and readable selected facts. [RELEASE.md](RELEASE.md),
[PUBLICATION.md](PUBLICATION.md) and [CAPACITY.md](CAPACITY.md) own promotion and
physical allocation. [ACCEPTANCE.md](ACCEPTANCE.md) owns verification dispositions.

External article checks live in separate packs keyed by capture and entity, with
topic checks in a small control object. They do not change semantic revisions or
gameplay freshness. Observation-only changes skip model projection; Steam-only
changes reuse the article mapping too. Capacity projection relocates these packs
and bounds their reference lists before recording the release configuration.
The browser verifies their hashes and emits links only for populated article
revisions. Missing, empty and unavailable results remain explicit. An optional
article-load failure does not replace the page's gameplay facts.

Optional [authored explanations](CURATED.md) are attached to entry packs and
grouped Markdown. Their checks remain separate from page gameplay verification.
Search records omit explanation text to keep topic search small. A failed check
shows its reason and last successful text without hiding generated facts.
