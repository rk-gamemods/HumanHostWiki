"""Independent conservation checks for located external-article metadata."""

from tools.audit_shard_index import leaves


def compare(original, projected, resolve):
    if original is None:
        assert projected is None
        return 0
    assert projected is not None
    value = resolve(projected) if "path" in projected else projected
    assert {key: item for key, item in value.items() if key != "entries"} == {
        key: item for key, item in original.items() if key != "entries"}
    actual = list(leaves(value["entries"], resolve))
    assert len(actual) == len(original["entries"])
    for after, before in zip(actual, original["entries"]):
        assert {key: item for key, item in after.items() if key != "path"} == {
            key: item for key, item in before.items() if key != "path"}
        resolve(after)
    return len(actual)


def reachable(projected, resolve):
    if projected is not None:
        value = resolve(projected)
        for reference in leaves(value["entries"], resolve):
            resolve(reference)
