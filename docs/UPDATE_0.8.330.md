# Human Host 0.8.330 source review

Reviewed on 2026-11-07, Steam build 26507141. The local source comparison is
`202c27fe16cb9d771121eb8d6081b975047795ee` (0.8.326 / 26180432) to
`c9f85a54326a8071d40d1243927b1f2fdbb980a0`. The installed PlayerSettings bytes
match the captured version evidence. Game source and raw catalogs remain in the
separate local capture repository.

The first precheck reported 19 source groups with 58 occurrences. After the
dispositions below, the normal update completed with zero blocking groups. All 22
checked external articles were populated. The selected local release is
`02636eccacd2dd1727a3f3b6be5af8eb9192a0626d54387120364fc5398e4031`;
its publication status is owned by the separate publication receipt.

## Source dispositions

- **New fields (16 groups).** The six new `Terrain_Loader_Manager` streaming
  settings are selected as world-system facts: smart-load release interval,
  the suspension switch and the four travel-intent thresholds that release
  suspended terrain while the player travels. Outline-style indexes, loot-sparkle
  materials and new event bindings (`On_PickPropHint_*`, `On_Save_*`) are
  presentation or service wiring and are excluded by name.
- **Ammunition address rule (7).** Every reviewed `Item_Slot_Mgr` helper kept
  identical tokens. The file gained `using EPOOutline;`, which the conservative
  dependency hash includes. None of the 39 `EPOOutline` type names occurs in the
  helpers, so the six hashes were rebaselined. The join again finds 42
  ammunition targets, as in 0.8.326.
- **Merchant prefabs (20).** The build ships none of the eight `mt_*` merchant
  bundles that the Addressables catalog still names. Merchants were never
  playable: the shipped `Merchant_Mgr` object has `m_IsActive: false` in every
  capture from 0.8.319 on, and `Merchant_Mgr.My_Start` does nothing unless the
  object is active. The extractor now reports drift inside such a switched-off
  feature separately and without blocking (see [operator report](PIPELINE.md#operator-report)).
  Links keep their unresolved status; no target is invented.

## Identity dispositions

The game-input run recorded 46 changed, 35 new, 4 not-present, 39 uncaptured and
27,248 unchanged observations.

- `Merchant_Mgr` moved from scene object `#12767` to `#12810`. Its component
  matched, but its seven biome-stock rows lost their only other corroboration,
  the merchant-prefab links. Seven reviewed corrections in
  `identity/corrections.json` keep each stock row on its prior entity by
  unchanged field path and biome name.
- The 39 uncaptured observations all come from the unshipped `mt_*` bundles.
- New observations are 28 English text records: 20 merchant voice lines and
  the new frame-generation, VRAM-warning, multiplayer and co-op notices.
- Not present: the `Merchant_Ins` and `Merchant_LookAt` type summaries (their
  bundles are absent), the replaced "Coming soon" notice, and the
  `TND.DLSS.DLSS_HDRP` type, replaced by the new `TND.FrameGen` assemblies.

## Validation

- `tools/check_game_version.py`: passed for 0.8.330 and the installed input hash.
- `tools/check_extraction.py --all`: 23,974 observations and 376,454 assertions
  passed, including 2,722 referenced prefab identities and 523 type summaries.
  The coded-value audit passed 33,966 boolean and 24,191 enum occurrences,
  42 ammunition targets and 110 enum entries across 32 fields.
- `tools/check_history.py`: 27,329 normalized observations passed 467,206 assertions.
- `tools/check_reader.py`: 287,285 current and historical observations passed
  2,585,589 assertions across 37,601 files.
- `tools/check_release.py`: passed for the selected release.
- The unchanged repeat reproduced the same release in 65.7 seconds.
- Local browser checks passed the version/build banner, global Crude Axe search,
  item provenance, 0.8.326 historical selection with its Anvil cross-topic link,
  and the merchant-stock "switched off" notice. Expanded source details at a
  390-pixel width had equal client and scroll widths of 375 pixels.

The hidden preview tab ignored viewport resizing, so the 390-pixel check loaded
the page in a same-origin 390-pixel frame. These checks establish captured data
and reader integrity; no Unity gameplay test ran.

## Measured update cost

Capture took 251.21 seconds. The full wiki update took 2,280.72 seconds:
331.67 for reader projection, 193.59 for release preparation and 1,742.29 for
reader retention. Retention took 521.49 seconds in 0.8.326 with one fewer reader
candidate (60 now), so candidate growth does not explain the difference. The run
used below-normal priority on a shared desktop; the cause is unconfirmed. The
timing receipts own the precise measurements.
