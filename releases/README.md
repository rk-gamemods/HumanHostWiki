# Coordinated wiki releases

This directory has no release manifests yet. A registered source snapshot or
navigation preview must never be promoted here as a completed wiki release.

A future immutable release manifest pins the source snapshot, umbrella generator
and contract revisions, each participating topic/hub commit, historical route
map, output hashes and validation receipts. Topic publication succeeds first;
the hub's release pointer is promoted last. See the
[ADR release protocol](../docs/adr/0001-versioned-public-wiki.md#6-refresh-build-and-coordinated-release).

Git commits across repositories and Pages deployments are not one atomic
transaction. The manifest makes a coherent set explicit; persisted stage
receipts must support retry and rollback to an earlier validated set.
