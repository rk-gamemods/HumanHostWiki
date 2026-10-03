"""Independent directory reader used only by release audits, never generation."""


def leaves(refs, fetch, active=()):
    for ref in refs:
        if "kind" not in ref:
            yield ref
            continue
        assert ref["kind"] == "wiki-shard-directory"
        assert ref["path"] not in active and len(active) < 32
        value = fetch(ref)
        assert value["schema_version"] == 1 and value["kind"] == ref["kind"]
        children = value["shards"]
        assert children and all(row["first"] <= row["last"] and row["count"] > 0 for row in children)
        assert min(row["first"] for row in children) == ref["first"]
        assert max(row["last"] for row in children) == ref["last"]
        assert sum(row["count"] for row in children) == ref["count"]
        yield from leaves(children, fetch, (*active, ref["path"]))
