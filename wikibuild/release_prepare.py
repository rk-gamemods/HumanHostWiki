"""Measure complete Git proposals and roll full entrypoints before any promotion."""

from dataclasses import asdict
from pathlib import Path
import uuid

from . import capacity_projection, entrypoints, git_transaction, physical, publication_git, release_output, release_partitions
from .storage import ContractError, git, within


def prepare(root, project, candidate, release_id, inventory, previous):
    # Import at the coordinator boundary; neither placement nor the writer calls
    # release orchestration. A failed proposal never acquires a pending journal.
    from . import capacity_inventory, release
    limits = physical.budgets(project)
    original = entrypoints.active(inventory.partitions)
    existing = {part.id for part in inventory.partitions}
    proposed, rolled = inventory.partitions, set()
    logical = {repo["id"]: repo for repo in project["repositories"]}
    while True:
        fronts = entrypoints.active(proposed)
        initial = physical.repositories(project, physical.registry(proposed))
        by_id = {repo["id"]: repo for repo in initial}
        bases = {topic: physical.base(project, by_id[identity]) for topic, identity in fronts.items()}
        projection = capacity_projection.build(Path(candidate["path"]), release_id, project["github_owner"],
                                               proposed, inventory.stored, limits, entrypoints=bases)
        registry = physical.registry(projection.partitions)
        ordered = physical.repositories(project, registry)
        control, groups = entrypoints.publication_groups(ordered, fronts, original)
        order = [identity for group in groups for identity in group] + [control]
        by_id = {repo["id"]: repo for repo in ordered}
        ordered = [by_id[identity] for identity in order]
        created = {part.id for part in projection.partitions} - existing
        stage = within(root, ".local/rs/" + uuid.uuid4().hex[:12])
        stage.mkdir(parents=True)
        plans, repositories, writers, destinations, new_repositories = {}, {}, {}, {}, []
        for repo in ordered:
            target = within(root, repo["path"])
            if repo["id"] in created:
                target, entry = release_partitions.seed(root, stage, repo, logical[repo["logical_topic"]])
                new_repositories.append(entry)
            prepared = stage / repo["id"]
            prepared.mkdir()
            destinations[repo["id"]] = target
            writers[repo["id"]] = release_output.Writer(target, prepared, repo, release_id)
        for placement, data in projection.writes():
            writers[placement.partition].add(placement.artifact.path, data, allocated=True)
        overflow = set()
        for repo in ordered:
            identity, topic = repo["id"], repo.get("logical_topic", repo["id"])
            writer, target = writers[identity], destinations[identity]
            if identity == fronts[topic]:
                release.project_topic(Path(candidate["path"]), repo, writer, projection)
            elif identity == original[topic] and topic in rolled:
                entrypoints.retire(writer, project, topic, bases[topic], release_id, candidate["path"])
            elif repo["role"] == "partition":
                release_partitions.landing(writer, project, repo)
            changes, summary = writer.finish(limits.file_bytes)
            if any(meta["bytes"] > limits.file_bytes for meta in changes.values()):
                raise ContractError(f"Generated control file exceeds the configured file budget: {identity}")
            commit = git_transaction.prepare(target, stage / identity, changes, f"Update wiki reference {release_id[:12]}")
            prior = previous["repositories"].get(identity) if previous else None
            old_pages = prior["pages"] if prior else None
            site_tree = git(target, "rev-parse", commit["commit"] + ":site")
            pages = (old_pages if prior and prior["tree"] == site_tree else
                     publication_git.commit(target, site_tree, old_pages, f"Publish wiki release {release_id}"))
            measured = capacity_inventory.history_size(target, [commit["commit"], pages])
            front = identity == fronts[topic]
            # Reserve one final successor transition before a front is sealed.
            # Fresh front control content must fit too; repeatedly creating new
            # empty repositories cannot cure an indivisible control footprint.
            site_limit = limits.site_bytes - (limits.site_reserve_bytes if front else 0)
            history_limit = limits.history_bytes - (limits.history_reserve_bytes if front else 0)
            if changes and (summary["site_bytes"] > site_limit or measured["history_bytes"] > history_limit):
                if front and topic not in rolled:
                    overflow.add(topic)
                else:
                    raise ContractError(f"Prepared repository exceeds capacity after control files and Git history: {identity}")
            plans[identity] = {"path": repo["path"], "git": commit}
            repositories[identity] = {"path": repo["path"], "github_name": repo["github_name"],
                                     "commit": commit["commit"], "tree": commit["tree"], **summary,
                                     "pages": pages, "pages_parent": old_pages,
                                     "history_bytes": measured["history_bytes"]}
        if overflow:
            proposed = entrypoints.rollover(proposed, inventory.topics, overflow)
            rolled.update(overflow)
            continue
        for identity, record in repositories.items():
            target = destinations[identity]
            git(target, "update-ref", f"refs/wiki-releases/{release_id}/source", record["commit"])
            git(target, "update-ref", f"refs/wiki-releases/{release_id}/pages", record["pages"])
        return {"stage": stage.relative_to(root).as_posix(), "order": order, "plans": plans,
                "new_repositories": new_repositories}, {
                    "repositories": repositories, "physical": registry, "entrypoints": fronts,
                    "capacity": {"budgets": asdict(limits), "phases": list(projection.phase_ids),
                                 "new_repositories": sorted(created), "rolled_topics": sorted(rolled),
                                 "prepared_sizes_checked": True}}
