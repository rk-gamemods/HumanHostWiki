# Human Host 0.8.323 source review

Reviewed on 2026-10-16, Steam build 25986463. The local source comparison is
`072c9ca90af0d9fe156df062db952d11cfd5b6d1` (0.8.319 / 25752290) to
`2b4e884f2e32821566eb062aba8e7b1522d4a851`. Game source and raw catalogs remain
in the separate local capture repository.

The initial wiki run reported 55 source exception groups and one identity group.
Review established these dispositions:

- Select the new map/compass discovery, fog-template and collision/pre-smash
  configuration fields. Explicitly exclude rendering, UI and diagnostic state.
- Support native `Map_POI`, `Map_Compass_Bar` and `Map_Fog_Of_War`; account for
  the mesh modifier and text-width follower as presentation-only components.
- Preserve both reviewed Sound_Mgr layouts: the older two material-name strings
  and the replacement `_FallbackFootSFX`. A missing layout or invalid type still
  requires review.
- Classify the 99 former CompassPro observations as not present. Their component
  source IDs and types are absent from the complete current index; their prefab
  GameObjects surviving at the same paths do not prove component presence.
  Do not merge their identities into the 101 native Map_POI observations.
- Recover Top_Info enum declarations from ILSpy compiler-local syntax through a
  same-width in-memory spelling substitution and one parser pass. Retain original
  source bytes, hashes, lines and offsets.

The [precheck](PIPELINE.md) now runs before network, rendering, release and
retention. It stops on source exceptions before identity processing, and on
identity exceptions before expensive output work. It preserves the selected
release and shares the normal stage caches.

Measured on this checkout: the initial full wiki run took 1071.86 seconds.
A fresh clean precheck took 67.25 seconds (31.72 extraction, 35.15 identity);
its unchanged repeat took 1.11 seconds with the same report identity and no
source bytes reread. A cached reproduction of the original 55 source groups took
0.58 seconds. These are observed timings, not a runtime guarantee.

Independent checks passed all 23,939 selected observations with 376,311 assertions
and all 27,304 normalized observations with 467,105 assertions. The current
precheck has zero source or identity exception groups. This establishes captured
data and lineage integrity; runtime gameplay remains separately scoped.

The generated reader passed independent conservation and reverse-edge checks for
232,618 current and historical observations (2,093,582 assertions). Capture has
zero decode failures and three explicit editor-only field-layout gaps, whose
declaring assemblies are absent from the shipped player. The final full update
took 879.80 seconds; this measurement included concurrent independent auditing.
