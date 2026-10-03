# Steam build availability

Build availability is evidence about a Steam branch at a stated time. Matching
that build does not verify gameplay facts. `wikibuild/availability.py` owns these
observations; source capture receipts and gameplay verification remain separate.

The normal update reads the captured app and branch, refreshes availability when
its cache expires, then completes supported wiki work. It never updates the game
installation or requests an account login. A different available build is reported
as awaiting a matching local capture. The next operator invocation checks again;
there is no scheduler or background updater.

## Provider and setup

`wikibuild/steam_build.py` runs an isolated SteamCMD process with:

```text
+login anonymous +app_info_update 1 +app_info_print 2393970 +quit
```

Valve documents [app metadata inspection](https://partner.steamgames.com/doc/sdk/api/debugging#console_commands)
and the [SteamCMD client](https://partner.steamgames.com/doc/sdk/uploading#5).
The adapter checks exit status, anonymous connection confirmation, the requested
app/branch, numeric build identity and depot manifests. Response accumulation is
limited to 1 MiB while reading. The installed client owns its network retries;
progress remains visible. Its executable hash and the response hash accompany the
selected metadata. No credentials, machine paths or full app-info response enter
the public observation.

Run once on this Windows workspace:

```powershell
pwsh -NoProfile -File tools/Install-SteamMetadataClient.ps1
```

The setup script downloads Valve's bootstrap package into a unique
`.local/tools/steamcmd.staging-<guid>/` directory with a 60-second request timeout
and a 120-second overall download deadline. Each bootstrap invocation has a
600-second deadline; a timeout kills the process tree. If the first invocation
exits nonzero after updating, a second invocation must succeed. Setup verifies
the Valve Authenticode signature before execution and after updating, atomically
renames the staging directory to `.local/tools/steamcmd/`, writes its
`.install-complete` marker, then saves the path in `.local/steamcmd.json`.
The next run removes leftover staging directories and replaces an unmarked
installation only when every entry matches the installer's SteamCMD allowlist;
unknown files or linked directories require inspection and are preserved.
It preserves a different existing configured path. SteamCMD updates itself, so
its binary is recorded by hash per observation instead of being a pinned runtime
package. This is an optional metadata dependency; reader generation remains
standard-library Python and browser-native JavaScript.

`project.json.availability` enables the check and configures `cache_seconds`
(3600 by default) and `retry_seconds` (60 after an unavailable observation).
Durations must be integer seconds from 1 through 86400. A branch/rule change or
clock rollback bypasses the cache. Tests disable the real provider and inject
bounded responses; they must never depend on a live Steam session.

## Storage and failure

`availability/<sha256>.json` holds an immutable, selected observation and its UTC
check time. `availability/latest.json` selects it. Both belong to the umbrella.
Each release's reader configuration embeds its pinned observation, so an older
release retains the evidence used when it was generated. Historical entry pages
compare the selected build and branch with that observation and display its time.
They do not describe an old observation as a live check.

A failed remote check creates an explicit unavailable observation. It cannot reuse
an older success as a new check or grant a current badge. Detailed errors stay in
`.local/availability-error.json`; the operator report identifies that separate
failure while supported content processing continues. Malformed saved evidence
and changing generation rules remain execution failures, preserving the existing
release. The writer lock covers observation, generation and promotion.

An identical cached observation leaves its bytes, pointer and downstream outputs
unchanged. A new check time is a new input, even if the build is unchanged. When
availability is the only reader input that changed, the renderer reuses validated
immutable packs through hard links and rewrites only configuration and reference
links. It skips model projection and never advances gameplay verification dates.
Public Git allocation reuses the existing immutable objects.

## Evidence and limits

The anonymous metadata probe on 2026-09-27 returned public build `25548639` and
depot `2393972` manifest `8060226703539543058`. The first bootstrap printed app
metadata but exited 1; the updated client repeated the query with exit 0. Its
Steam console version was `1788292693`. A success requires the latter condition.

The Web API `ISteamApps/UpToDateCheck` returned `success: false` for this app and
was not adopted. The selected metadata does not provide a reliable in-game display
version. The captured [application version](GAME_VERSION.md) comes from the local
source snapshot. Gameplay verification remains open work.

Focused checks:

```powershell
py -3 -m unittest discover -s tests -p test_availability.py -v
node tests/reader_captures.test.js
```

These cover parsing, response limits, invalid process results, evidence integrity,
cache expiry, retry on later invocation, unknown status after failure, branch
comparison, pipeline continuation and reuse of immutable reader data. Live update,
publication and unchanged-repeat evidence belong in [IMPLEMENTATION.md](IMPLEMENTATION.md).
