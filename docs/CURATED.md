# Checked authored explanations

ADR-0001 sections 4 and 7 own the requirements. The normal update checks optional
authored explanations and includes unresolved checks in its final operator report.

Topic repositories own optional `curated/<claim-id>.json` definitions. The shared
runner reads committed definitions, selected normalized facts and explicitly
declared source-code dependencies. It never executes expressions or imported
Python/JavaScript from authored content. Rendering remains offline.

Each definition names a stable entry key, a starting captured snapshot, literal
text segments and named scalar facts. Fact checks declare an exact JSON type and
optional equality or numeric bounds. A text segment can insert one checked fact.
Code-backed explanations also pin SHA-256 hashes of named captured `.cs` files.
The declared checks establish only their stated scope; they cannot confer runtime
verification or verify every fact on the entry's page.

## Author an explanation

Save a definition under the entry's owning topic repository, outside generated
`site/` and `reference/` paths. For example, the following definition inserts only
the Crude Axe's captured `MaxStack` configuration value:

```json
{
  "schema_version": 1,
  "entity": "e-045871a35c62b6aa04edaddb21311d64",
  "title": "Maximum stack configuration",
  "since": "build-25548639-0bf00fe33781",
  "scope": "selected-data",
  "text": ["Configured maximum stack size: ", {"fact": "stack"}, "."],
  "facts": {"stack": {"path": "/MaxStack", "type": "integer", "min": 1}},
  "code": []
}
```

`since` prevents applying a newly authored explanation to earlier captures.
An unknown starting snapshot produces an exception. Fact paths are JSON pointers
relative to the selected entry's facts; `~0` and `~1` escape `~` and `/`.
Each dependency may name another stable `entity`. Supported types are `integer`,
`number`, `string` and `boolean`; booleans do not count as numbers. `equals`
compares both value and JSON scalar type. `min` and `max` accept numeric bounds.
Lists, objects, missing fields and mismatched types fail the declared check.

For a reviewed explanation that also depends on code, use `scope: "code-backed"`
and list captured C# paths with their SHA-256 hashes in `code`. Changes to those
files invalidate the explanation until reviewed. This establishes declared
dependency stability, not runtime behavior or completeness of the author's claim.

An optional `symbol` on a code dependency restricts its hash to a declared C#
type, field, property, constructor or method plus conservative enclosing context.
For example: `{"kind":"method","type":"Game.Generator","member":"Generate","parameters":["float"]}`.
Compute its hash with `py -3 -m wikibuild.code_dependencies --help`; use the pinned
packages in `requirements-source.txt` only when such a check is declared.
Missing/ambiguous declarations and parser errors mark the claim unverified.
Helpers and constants must be declared separately; this does not infer a call
graph or prove runtime behavior. Whole-file checks and selected-data checks
remain available without those packages. This optional checker is not required
for baseline reconciliation or publication.

Definitions are limited to 32 KiB, 64 fact dependencies, 32 code dependencies and
128 text segments. Rendered text is limited to 16 KiB, checked before concatenation.
Oversized or malformed definitions and text produce content exceptions.
Multiple explanations still share their entry pack's configured size limit;
indivisible record capacity remains a separate completion gate.

Review and commit authored changes in their topic repository. Then, from the
umbrella, adopt the reviewed child commit with `py -3 wiki.py lock` and run
`py -3 wiki.py update --operator-report`. Subsequent game updates need no prose
edits for values that still satisfy the declared checks. Failed checks await user
direction after supported work completes; they do not invoke a model.

This implementation attaches explanations to existing entries. Dedicated
guide pages, guide search and global gameplay-verification badges remain open.

## State and failure contract

`wikibuild/curated_rules.py` owns the declarative schema and pure check/render
policy. `wikibuild/curation.py` owns committed definition discovery, selected
dependency reads, immutable check receipts and exception reporting. The reader
embeds results in existing entry packs; topic ownership and entity history stay
with their existing owners.

Input identity includes definition hashes, selected identity runs and the checker
contract. Durable results live under `curation/runs/`; `curation/latest.json` is
a diagnostic pointer, separate from release/publication pointers. A successful
check records its snapshot, Steam build, identity run, definition revision,
dependency hashes and rendered text. A later failed check retains the last
successful check and its text as historical evidence, labels the explanation
unverified, and logs a content exception. Independent facts and explanations
continue. Invalid new definitions are logged without publishing arbitrary input.
Missing or changed owned receipts are execution failures.

The writer lock excludes simultaneous updates. Repeated inputs reuse their
receipt without rereading selected models or code. New inputs stream normalized
models once per changed snapshot and retain only declared dependencies. Historical
checks reuse their receipts when definitions, models, capture metadata, checker
and retained last-success evidence are unchanged.
Code reads share one Git batch process per snapshot and never copy source code
into wiki content. Source commits and definitions are rechecked before promotion.
The reader fingerprints the check result and keeps historical release bytes
accessible through the existing immutable release mechanism.

## Validation

```powershell
py -3 -m unittest discover -s tests -p test_curation.py -v
py -3 -m unittest discover -s tests -p test_pipeline.py -v
node tests/reader_captures.test.js
```

Check changed values, unchanged inputs, failed bounds/types, missing entities or
fields, code changes, extractor corrections, malformed definitions, historical
selection, unknown templates, tampered receipts, interrupted final promotion and
unchanged reruns. Failed checks must affect only their explanation, preserve its
last successful check, and reach the final operator report. Browser and Markdown
renderers must treat authored text as literal text.
