"""Independent audit expansion; browser consumers keep capture pages lazy."""

from tools.audit_shard_index import leaves


def expand(config, fetch):
    if "capture_catalog" not in config:
        return config
    assert "versions" not in config and "snapshots" not in config
    root = fetch(config["capture_catalog"])
    assert root["schema_version"] == 1 and root["kind"] == "wiki-capture-catalog"
    maps = {}
    for field in ("by_id", "by_order"):
        values = {}
        for ref in leaves(root[field], fetch):
            page = fetch(ref)
            assert len(page) == ref["count"] and min(page) == ref["first"] and max(page) == ref["last"]
            assert not values.keys() & page.keys()
            values.update(page)
        assert len(values) == root["count"]
        maps[field] = values
    versions, snapshots = [], {}
    for ordinal in reversed(range(root["count"])):
        identity = maps["by_order"][f"{ordinal:016d}"]
        record = maps["by_id"][identity]
        assert record["version"]["snapshot_id"] == identity and record["ordinal"] == ordinal
        assert identity not in snapshots
        versions.append(record["version"])
        snapshots[identity] = record["index"]
    assert maps["by_id"][config["default_snapshot"]] == config["default_capture"]
    return {**{k: v for k, v in config.items() if k not in {"capture_catalog", "default_capture"}},
            "versions": versions, "snapshots": snapshots}
