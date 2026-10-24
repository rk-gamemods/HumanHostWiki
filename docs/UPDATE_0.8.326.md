# Human Host 0.8.326 source review

Reviewed on 2026-10-24, Steam build 26180432. The local source comparison is
`2b4e884f2e32821566eb062aba8e7b1522d4a851` (0.8.323 / 25986463) to
`202c27fe16cb9d771121eb8d6081b975047795ee`. The installed PlayerSettings bytes
match the captured version evidence. Game source and raw catalogs remain in the
separate local capture repository.

The normal update completed with zero source, identity or authored-content
exception groups. All 22 checked external articles were populated. Existing
extraction contracts and identity rules handled this capture without changes.
The selected local release is
`48488e690f58db3bd9824c43bd309a73b128f5417715bf80de79a5ee9a0b00a2`;
its publication status is owned by the separate publication receipt.

## Source and identity dispositions

The identity run records 36 changed, 35 new, one not-present and 27,267 unchanged
observations. Independent review covered every changed and new selection,
their relationships and the new absence against both captured commits.

- New selections comprise six merchant configurations, six map-marker
  configurations, 20 English text records and three referenced prefab identities.
  The text records correctly receive new identities where their source IDs were
  previously used by different objects.
- Merchant placement and biome-stock changes retain their captured references.
  Bearing's stock reference resolves through its evidenced GameObject alias to
  the item. Wasteland's merchant GUID remains empty despite Merchant_10-12
  assets existing; asset names do not establish a biome-stock link.
- Copper-alloy and high-speed-steel cuboid size changes retain the serialized
  dimensions. Changed technical summaries match the capture's coverage counts.
- The MotionBlur type summary becomes not-present. Its three prior typed
  component instances have no current counterpart in the complete object
  index. No identity merge or replacement reference is justified.

Capture has zero decoding failures. Three editor-only field-layout gaps remain
explicit because their declaring assemblies are absent from the shipped player.
Two shader-prewarm GUIDs remain unresolved at component `#12766`, fields
`/_PreWarmShadersRef/20` and `/21`. These are capture gaps, not invented wiki
targets. Merchant voice associations remain outside the selected extraction
contract. Optional unmatched community article titles stay unlinked.

## Validation

- `tools/check_game_version.py`: passed for 0.8.326 and the installed input hash.
- `tools/check_extraction.py --all`: 23,971 observations and 376,512 assertions
  passed, including 2,731 referenced prefab identities and 526 type summaries.
  The included coded-value audit passed 33,988 boolean occurrences, 24,227 enum
  occurrences, 42 ammunition targets and 110 enum entries across 32 used fields.
- `tools/check_history.py`: all 27,338 normalized observations passed 467,513
  assertions over facts, semantic hashes, canonical targets and provenance.
- `tools/check_reader.py`: all 259,956 current and historical observations passed
  2,339,626 assertions across 36,566 emitted files.
- `tools/run_tests.py --all -j 4`: 65 modules, 997 tests, six platform skips and
  zero failed modules on Windows. This includes pre-promotion failure, retry,
  writer-exclusion and publication-gate fixtures.
- Local browser checks passed the current version/build banner, global Crude Axe
  search, item provenance, 0.8.323 historical selection and its Anvil cross-topic
  link. Expanded source details at a 390-pixel viewport had equal client and
  scroll widths of 375 pixels, with the semantic hash wrapping normally.

T3 preview screenshots timed out twice; Chrome through the supported computer-use
surface supplied the visual checks. No reader change was needed. These checks
establish captured data and reader integrity; no fresh Unity gameplay test ran.

## Measured update cost

Capture took 236.08 seconds. The full wiki update took 1,372.56 seconds, including
507.35 seconds for reader projection, 250.83 for coordinated release preparation
and 521.49 for reader retention. Independent audits and the integration suite ran
concurrently, so these are observed wall times rather than isolated benchmarks.
The timing receipts own the precise measurements. No performance change was
included in this data update.
