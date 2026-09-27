# External article observations

The ADR requires useful article backlinks with recorded populated, empty, missing
or unavailable checks. The provider and observation modules are implemented and
tested. **Normal-update integration, production topic routing and reader output
remain unfinished.** The acceptance command below does not publish anything or
process the pending game-content exceptions.

## Owners and data flow

`wikibuild/mediawiki.py` owns read-only MediaWiki requests, inventory pagination,
revision identity checks and the literal-content rule. It returns compact page
metadata and check results. Downloaded article bodies are discarded after hashing
and checking; no game source, asset index or game facts enter this adapter.

`wikibuild/external_links.py` owns immutable observations, cache reuse and offline
matching. Its `refresh` caller must hold the existing workspace writer lock.
`lookup` resolves an explicit article title. A `Matcher` indexes article leaf
titles once, then resolves entity names within caller-selected prefixes. Rendering
must use these pure lookup operations against a pinned observation.

Production source configuration and topic/entry routing will belong in
`project.json`. The real-site selection in `tools/check_external_links.py` is an
acceptance fixture, not an adopted routing policy. Integration must connect the
normal runner, final operator report, release identity and offline reader without
adding a separate operator maintenance step. An observation-only change should
reuse selected models and immutable gameplay packs.

## Selection and checks

A provider configuration supplies a canonical HTTPS `api.php` endpoint, namespace
number and name, exact titles and title prefixes. A prefix includes itself and
its slash-separated descendants. Namespace inventory is read in bounded pages;
only selected article bodies are requested. Revision requests use the IDs observed
in that inventory, so an intervening edit cannot silently substitute new content.

| Result | Evidence and behavior |
| --- | --- |
| `populated` | The pinned revision contains recognized literal prose, a numeric property or a numeric table row. A backlink points to that checked revision. |
| `empty` | The revision has no recognized article body after removing headings, images, navigation and placeholder lines. This includes navigation-only pages. |
| `missing` | A complete observed namespace inventory has no selected exact title or no matching entity leaf title. |
| `unavailable` | Retrieval failed, the inventory is incomplete, a title is ambiguous, a bound was reached, or the content/redirect format is unsupported. No backlink is emitted. |

These checks establish article presence and recognized content, not accuracy or
compatibility with a game build. The content rule accepts at least eight English
words outside excluded markup, a literal numeric property such as `Damage: 10`,
or a multi-cell numeric wiki-table row. Templates and HTML remain unavailable.
The rule is limited and its source digest versions the decision.

Names normalize Unicode compatibility forms, underscores, whitespace and case.
Matching does not infer plurals, renamed items, synonyms or category equivalence.
Multiple candidates remain unavailable. An incomplete inventory can establish an
explicit populated article but cannot establish a unique entity-name match or a
missing page. The remote index is an observed traversal, not an atomic transaction.

Simple whole-page redirects resolve only through selected, checked destinations.
Cycles, missing targets, fragments and other unrecognized redirects remain
unavailable. Cached redirects are resolved again against the current destination
checks, even when the redirect revision itself is unchanged.

## State, cost and recovery

Observations live at `external-links/<sha256>.json`; `latest.json` is an atomic
pointer. Each observation records source selection, implementation digests, UTC
check time, inventory completeness/hash, selected page metadata, content hashes
and check reasons. It does not retain article bodies. Missing results are derived
from the complete observed inventory and retained selection contract.

The default cache interval is one hour. Transient failures retry on the next
operator invocation after 60 seconds. There is no scheduler or retry loop.
Expired checks fetch the inventory again and reuse unchanged revision checks,
including deterministic unsupported-markup results. A source or rule change
invalidates that reuse. A recorded successful cache base survives outages so
recovery does not redownload every unchanged article. Old observations remain
available; retention must preserve referenced cache bases and release inputs.

Requests are serial anonymous GETs with a descriptive User-Agent and `maxlag=5`.
Limits per collection are 256 requests, 8 MiB response bytes, 1 MiB per response,
4,096 inventory pages and 64 KiB per selected article. A bounded read can consume
one extra byte to detect overflow. Revision batches contain at most ten articles
and 128 KiB of declared source content. Reads have a 30-second socket timeout;
HTTP redirects are refused. No external markup or expressions execute.

An unavailable batch does not stop later supported batches. An incomplete index
never grants a missing-page conclusion. Provider failures return unavailable
observations; invalid configuration, damaged saved receipts, changed inputs and
local persistence failures raise execution errors. Failed promotion leaves the
previous pointer intact. Repeating a fresh observation performs no network work
and preserves its bytes and timestamps.

## Validation

Run from the umbrella directory:

```powershell
py -3 -m unittest discover -s tests -p test_external_links.py -v
py -3 tools/check_external_links.py --online --root .local/external-link-acceptance
py -3 tools/check_external_links.py --report-only --root .local/external-link-acceptance
```

The live command writes isolated evidence and an unresolved-page list. It checks
selected populated and navigation-only pages, a no-request repeat and expiry,
then independently reads three pinned revisions and compares their page IDs,
revision IDs, byte lengths and SHA-256 hashes. Its one-second expiry policy is
test-only; check timestamps use actual UTC time. A changed live sample causes the
acceptance command to fail for inspection rather than update expected results.
The report-only command reads saved evidence without network requests or writes.

The focused tests cover missing/unavailable distinctions, partial inventories,
pagination, independent batch completion, title ambiguity, revision/source/rule
changes, redirects, content exclusions, response bounds, reuse after an outage,
clock rollback, receipt tampering and failed pointer promotion. They reject
network access during offline matching. The full normal-update, release, browser
and public-backlink checks remain required after integration.

Protocol references: [allpages](https://www.mediawiki.org/wiki/API:Allpages),
[revisions](https://www.mediawiki.org/wiki/API:Revisions) and
[API etiquette](https://www.mediawiki.org/wiki/API:Etiquette). The live fixture
targets the [recognized community wiki](https://wiki.nerdwerx.io/index.php/Human_Host:Main_Page).
