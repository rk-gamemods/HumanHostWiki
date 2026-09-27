# Source snapshot receipts

`wiki.py refresh` registers a clean local source commit and writes one small JSON
receipt here. An identity combines the Steam build and snapshot commit. It pins
the input inventory's Git blob, normalized metadata hashes, extractor versions,
Steam depots and known decoding gaps. Raw catalog files remain in the original
local codebase repository.

`input-registered` means the input identity was checked. It does not mean topic
pages were generated or verified. Missing display-version information and
unknown latest-game-build status remain explicit. See the
[ADR provenance contract](../docs/adr/0001-versioned-public-wiki.md#4-data-and-provenance-contracts).
