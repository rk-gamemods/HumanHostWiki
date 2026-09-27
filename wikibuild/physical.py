"""Generated physical repositories retain their configured logical topic owner."""

from . import capacity
from .storage import ContractError


def budgets(project):
    try:
        result = capacity.Budgets(**project.get("capacity", {}))
    except TypeError as exc:
        raise ContractError("Unknown capacity budget setting") from exc
    result.validate()
    return result


def registry(partitions):
    return {part.id: {"topic": part.topic, "ordinal": part.ordinal, "sealed": part.sealed}
            for part in sorted(partitions, key=lambda part: part.id)}


def repositories(project, allocated=None):
    """Derive physical identities from logical names; reject redirected checkouts."""
    logical = {repo["id"]: repo for repo in project["repositories"]}
    if allocated is None:
        return list(project["repositories"])
    result, names = [], set()
    for identity, record in sorted(allocated.items()):
        owner = logical.get(record.get("topic"))
        if owner is None or type(record.get("sealed")) is not bool:
            raise ContractError("Physical repository has unknown logical ownership")
        part = capacity.partition(capacity.Topic(owner["id"], owner["github_name"]), record.get("ordinal"))
        if part.id != identity or part.github_name.casefold() in names:
            raise ContractError("Physical repository identity conflicts with its logical owner")
        names.add(part.github_name.casefold())
        if part.ordinal == 0:
            result.append(dict(owner))
        else:
            result.append({"id": part.id, "path": part.path, "github_name": part.github_name,
                           "role": "partition", "logical_topic": part.topic, "ordinal": part.ordinal,
                           "title": f"{owner['title']} storage {part.ordinal}", "owns": [],
                           "coverage": f"Immutable reference objects owned by {owner['title']}"})
    if {repo["id"] for repo in result if repo["role"] != "partition"} != set(logical):
        raise ContractError("Physical registry omits a logical entrypoint")
    return result


def base(project, repo):
    return f"https://{project['github_owner']}.github.io/{repo['github_name']}/"
