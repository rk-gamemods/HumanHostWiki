# Captured application version

The Steam build ID identifies the captured distribution. The application version
is its developer-assigned label, read from the captured Unity `PlayerSettings`
object's `bundleVersion`. Unity 2022.3 documents that
[Application.version](https://docs.unity3d.com/2022.3/Documentation/ScriptReference/Application-version.html)
returns this setting. Neither label establishes gameplay verification.

## Ownership and evidence

The parent workspace's `tools/game_catalog/game_version.py` selects the field from
the catalog already decoded during a normal refresh. It adds no binary decode pass
or copy of the source index. `refresh.py` saves `Catalog/game-version.json` before
the snapshot's existing input-stability and atomic-promotion checks.

The record uses schema 1 and contains `version`, `status` and `evidence`. A recorded
version requires exactly one `PlayerSettings` object with a non-empty printable
label of at most 128 characters. Its evidence contains the game-relative source
path, input SHA-256, object ID and `/bundleVersion` field. The input must exist
exactly once in the hashed inventory. Missing or ambiguous settings, or an invalid
version field, produce `status: unknown`, a null version and an explicit reason.

`wikibuild/snapshots.py` reads this small optional record from the pinned source
commit. It validates its schema and evidence against that commit's input inventory,
then includes the selected label, evidence and metadata hash in the new receipt.
Malformed or mismatched evidence fails registration before any receipt is promoted.
Absent metadata keeps the previous `not-recorded-by-source-generator` representation
byte-for-byte. Existing receipts are never rewritten to infer an older label.

`wikibuild/reader.py` carries the value into capture summaries and snapshot indexes.
The reader shows it with the exact Steam build and keeps unknown labels explicit.
The status tooltip exposes the source locator and hash. Operator reports include
the captured version/status. [Availability observations](AVAILABILITY.md) remain
separate evidence about the latest observed Steam branch.

## Validation

The parent catalog tests cover unique selection, unknown states, input evidence
and repeatability. Wiki foundation tests exercise real Git registration, input-hash
mismatch and immutable older receipts. Reader tests cover projection and the
production JavaScript's version labels, evidence and historical unknown state.
Live capture, publication and unchanged-repeat evidence is recorded in
[IMPLEMENTATION.md](IMPLEMENTATION.md).
The parent's `tools/check_game_version.py` independently checks the recorded field,
serialized-file mapping, inventory entry and installed source hash without importing
the version selector or wiki registrar.

The existing captured `globalgamemanagers#1` object contains `0.8.315`. The installed
executable reports Unity `2022.3.62f3`, so executable metadata is not used as a game
version fallback. Unknown future layouts remain visible until their owner is adapted.
