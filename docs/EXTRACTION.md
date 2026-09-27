# Selected extraction contracts

Extraction reads the existing codebase in place. A discovery pass over the object
index selects records and counts coverage; it does not turn the index into wiki
articles. Every published fact must come from an explicit field contract.

## Owners

| Surface | Responsibility |
| --- | --- |
| `wikibuild/source.py` | Pinned Git reads, verified byte ranges, dependencies and old-snapshot fallback |
| `wikibuild/adapters/components.py` | One index pass, bounded record batches and technical type summaries |
| `wikibuild/adapters/catalog_policy.py` | Explicit infrastructure accounting and payload omissions |
| `wikibuild/adapters/schema.py` | Nested types, field selection, nulls, references and grouped exceptions |
| Topic files in `wikibuild/adapters/` | Selected fields, known omissions and domain relationships |
| `wikibuild/adapters/entries.py` | Recipe/skill/status entries from selected nested definitions |
| `wikibuild/extraction.py` | Output hashes, reuse, coverage checks and last-success promotion |
| `tools/check_extraction.py` | Independent comparison with committed source records |

The parent's `tools/game_catalog/catalog.py` writes record offsets and hashes into
the existing object index. It creates no duplicate record file. The reader uses
those ranges only after hashing their bytes. Local differences fall back to pinned
Git data; disagreement between the pinned index hash and pinned record is a failure.
Snapshots without range metadata remain readable through streaming Git.

## Adding or correcting a contract

1. Inspect the generated views and selected raw records. Record the assembly,
   component class, field path, type and meaningful relationships.
2. Change the owning topic module. Select only evidenced fields. Explicitly name
   excluded presentation/runtime fields; an exclusion must not hide unexamined
   gameplay data. New fields stay visible as exceptions until classified.
3. Use nested contracts for arrays and objects. Preserve list indices as evidence;
   unsupported entries retain null gaps. Reference contracts emit resolved targets
   or explicit gaps without copying serialized pointers into facts.
4. Add a fixture that changes the relevant value or shape and proves independent
   supported data survives. Extend the independent checker for new derivations.
5. Run the focused checks, a real extraction and an unchanged repeat. Inspect the
   exception report and source comparisons before treating the contract as supported.

Adding a class or field changes the extraction contract hash. Current invalidation
conservatively reruns the selected extraction when any selected dependency changes.
It reuses identical content objects; an unchanged run reads zero source data.
Finer invalidation should be added only with complete dependency evidence and a
measurement showing the extra state is worthwhile.

## Interpretation and coverage

Serialized values are labeled as extracted configuration. A field named `rate` or
`chance` is not automatically a probability, and an integer is not automatically
a verified enum label. Runtime rules require code evidence and separate checks.

Item labels use English tooltip records. Skill/effect labels use the English
`Language_Text` entry. Missing or ambiguous labels retain internal identifiers.
Cross-build identity and removal history belong to the identity stage, not these
observation keys or build-scoped Unity IDs.

Technical summaries contain type, assembly, class, count and at most eight example
IDs. Local counts must equal capture coverage. `topic_coverage` remains `partial`
even when every topic has some records. It must not imply complete mechanics,
verified pages or a coordinated release. The unresolved component classes remain
in the exception report while supported contracts finish normally.
