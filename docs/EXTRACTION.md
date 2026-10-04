# Selected extraction contracts

Extraction reads the existing codebase in place. A discovery pass over the object
index selects records and counts coverage; it does not turn the index into wiki
articles. Every published fact must come from an explicit field contract.

## Owners

| Surface | Responsibility |
| --- | --- |
| `wikibuild/source.py` | Pinned Git reads, verified byte ranges, dependencies and old-snapshot fallback |
| `wikibuild/source_record.py` | Hash-verified large-record projection, member framing and bounded skipped reads |
| `wikibuild/adapters/components.py` | One index pass, bounded record batches and technical type summaries |
| `wikibuild/adapters/catalog_policy.py` | Explicit infrastructure accounting and payload omissions |
| `wikibuild/adapters/technical.py` | Reviewed technical exclusions and selected operating defaults, with field drift detection |
| `wikibuild/adapters/prefabs.py` | Individual identities for GameObjects referenced by selected domain relationships |
| `wikibuild/adapters/coded_values.py` | Captured enum declarations, boolean labels and named graph targets for selected fields |
| `wikibuild/adapters/coded_contract.py` | Reviewed coded-field inventory and ammunition address-rule guards |
| `wikibuild/adapters/acquisition.py` | Merchant stock/pricing and context-specific inventory templates |
| `wikibuild/adapters/inventory.py` | Item-quality, upgrade, slot restrictions and initial-character configuration |
| `wikibuild/adapters/combat.py` | Damage, attack timing, ammunition modifiers and combat preset links |
| `wikibuild/adapters/controls.py` | Serialized key/action bindings and camera control defaults |
| `wikibuild/adapters/characters.py` | Player/NPC controller, physical movement and corpse defaults |
| `wikibuild/adapters/animation.py` | Shared timing selection with exact default markers; no clips/callbacks |
| `wikibuild/adapters/navigation.py` | Map exploration, marker visibility and reviewed map UI exclusions |
| `wikibuild/adapters/environment.py` | Enviro module bindings and environment targets, separate from game weather rules |
| `wikibuild/adapters/schema.py` | Nested types, field selection, nulls, references and grouped exceptions |
| Topic files in `wikibuild/adapters/` | Selected fields, known omissions and domain relationships |
| `wikibuild/adapters/entries.py` | Recipe/skill/status and biome stock entries from selected nested definitions |
| `wikibuild/extraction.py` | Output hashes, reuse, coverage checks and last-success promotion |
| `tools/check_extraction.py` | Independent comparison with committed source records |
| `tools/check_coded_values.py` | Independent source-text audit of numeric mappings and ammunition item targets |

The parent's `tools/game_catalog/catalog.py` writes record offsets and hashes into
the existing object index. It creates no duplicate record file. The reader uses
those ranges only after hashing their bytes. Local differences fall back to pinned
Git data; disagreement between the pinned index hash and pinned record is a failure.
Snapshots without range metadata remain readable through streaming Git.

Component reads group at most 128 records and 2 MiB of encoded input per batch.
An oversized or unknown-size record is isolated, and the prior decoded batch is
released before reading another. New catalog indexes describe every member of
script records at least 1 MiB in size. The reader hashes the complete record,
checks canonical member names/boundaries and decodes the top-level fields selected
by its component contract. Unselected values are hashed in chunks of at most
64 KiB. Their names remain as null placeholders, so new-field reporting survives;
no selection code can treat these placeholders as real values. Nested selected
structures still pass through their complete existing field contracts.

This avoids materializing excluded corner-coordinate arrays in the current terrain
loader. The index is generated alongside the original local record, without a
second data file. A stale local range falls back to the pinned Git blob and applies
the same selection. That fallback still buffers one encoded JSONL line, while
ordinary local range reads do not. Legacy indexes without member metadata retain
full decoding. Selected large values are not capped or silently truncated.

## Adding or correcting a contract

Selected enum fields must have readable values and graph edges. `coded_values.py`
resolves their types from the captured C# declarations, including inherited and
nested fields. It emits only used named values, declaration locators and selected
relationships. Raw numbers remain in provenance; no method bodies enter the wiki.
Booleans display Yes/No. The reader humanizes field labels and preserves the
selected snapshot and release when following a value link.

The current inventory contains 31 enum field contracts. For example, the captured
`Weapon_Range.AmmoType` maps 5 to 7.62x54mm. Its named entry links to the factory
and material ammunition items using the captured Addressables and the game's
reviewed address-building rule. Those helpers have syntax hashes, so a changed
rule logs an exception instead of guessing that the old join is still valid.
Unknown enum values, missing declarations and ambiguous mappings also remain
exceptions. Adding labels cannot turn an unknown code into a supported fact.

Install the pinned source parser once with
`py -3 -m pip install -r requirements-source.txt`. The source parser versions,
adapter code, contract and captured input hashes participate in invalidation.
No LLM, remote classification or package installation occurs during an update.

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

Referenced prefab identities use one additional streaming pass over the index
after selected relationships are known. They contain identity metadata and inverse
links to cataloged component configurations, evidenced by each component's
`m_GameObject` reference. Unreferenced objects and binary payloads are not exported.
Relationship resolution prefers a direct object identity over component aliases,
after applying the predicate's expected kind. A model with several components is
one model; a headless corpse prefab does not require a living AI configuration.

Reviewed technical contracts read the component through the same bounded selector
as gameplay contracts, but emit only the existing type/count summary. A new field
still raises an exception. These decisions account for serialized fields without
claiming that every method's behavior has been interpreted.

Scene-prop composition uses an explicit `IndexCounts` contract. It counts valid
`protoRefIndex` values against the named prefab table and emits sorted counts,
total placements and unresolved placements. Unknown fields and invalid indices
still produce exceptions. Source-array locators and raw-record hashes prove the
derivation; individual placement rows and geometry are not wiki content. The
independent checker recomputes these counts directly from the pinned raw records.

`NumberWithSentinel` permits only explicitly named catalog-encoded float markers
on opted-in fields. Animancer timing uses `{"float":"nan"}` for default behavior;
it is preserved as source evidence, not converted to zero or a guessed duration.
Ordinary numeric contracts still reject non-finite values and encoded markers.

Use `py -3 tools/check_extraction.py --all` for the initial baseline: it compares
every selected gameplay observation, all referenced prefab identities and every
type summary with pinned source records. The default command samples the first,
middle and last observation in each gameplay family. Neither mode proves runtime
behavior. [Baseline reconciliation](BASELINE_RECONCILIATION.md) records the initial
source reviews as dated evidence. [ACCEPTANCE.md](ACCEPTANCE.md) owns current status.

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
