"""Real reader candidates prove located-reference fidelity and historical reuse."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch
from urllib.parse import urljoin

import test_reader
from tools.check_capacity_projection import audit
from tools.audit_shard_index import leaves
from wikibuild import capacity, capacity_projection, packs, reader, release, release_content, shard_index
from wikibuild.storage import ContractError, digest, json_bytes


class CapacityProjectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_reader.ReaderTests()
        self.fixture.setUp()
        test_reader.install_guide(self.fixture)
        self.addCleanup(self.fixture.doCleanups)
        self.project = self.fixture.project
        self.project["github_owner"] = "wiki-fixture"
        for repo in self.project["repositories"]:
            repo["github_name"] = "Wiki-" + repo["id"]
        self.bases = release.bases(self.project)
        self.candidate = reader.build(self.fixture.root, self.project, self.fixture.runs, bases=self.bases)
        self.path = Path(self.candidate["path"])
        self.topics = [capacity.Topic(repo["id"], repo["github_name"]) for repo in self.project["repositories"]]
        self.originals = tuple(capacity.partition(topic, 0) for topic in self.topics)
        self.release_id = "a" * 64

    def build(self, partitions=None, stored=(), **kwargs):
        return capacity_projection.build(self.path, self.release_id, "wiki-fixture",
                                         self.originals if partitions is None else partitions, stored, **kwargs)

    def materialize(self, projection, output):
        partitions = {part.id: part for part in projection.partitions}
        writes = 0
        for placed, data in projection.writes():
            part = partitions[placed.partition]
            # This adapter stands for the later journaled release writer. Use
            # exclusive creation so a changed historical file fails the test.
            target = output / part.github_name / placed.artifact.path.removeprefix("site/")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(data)
            writes += 1
        return writes

    def inspect(self, projection, output):
        """Follow URLs as the browser does; do not use production reference code."""
        counts = {"snapshots": 0, "packs": 0, "relocated": 0}
        for topic, config_ref in projection.configurations.items():
            def fetch(ref):
                url = urljoin(self.bases[topic], ref["path"])
                self.assertTrue(url.startswith("https://wiki-fixture.github.io/"))
                relative = url.removeprefix("https://wiki-fixture.github.io/")
                data = (output / relative).read_bytes()
                self.assertEqual(len(data), ref["bytes"])
                self.assertEqual(hashlib.sha256(data).hexdigest(), ref["sha256"])
                return json.loads(data)

            from tools.audit_capture_catalog import expand
            config = expand(fetch(config_ref), fetch)
            self.assertEqual(config["topic"], topic)
            self.assertEqual(config["release_id"], projection.release_id)
            original = json.loads((self.path / topic / "reader.json").read_bytes())
            for name in ("versions", "default_snapshot", "topics", "official_links"):
                self.assertEqual(config[name], original[name])
            for extension, name in config["runtime"].items():
                relative = urljoin(self.bases[topic], name).removeprefix("https://wiki-fixture.github.io/")
                self.assertEqual((output / relative).read_bytes(), (self.path / topic / ("reader." + extension)).read_bytes())
            for snapshot, ref in config["snapshots"].items():
                index = fetch(ref)
                before = json.loads((self.path / topic / "snapshots" / (snapshot + ".json")).read_bytes())
                for kind in ("entries", "semantics", "provenance", "search", "backlinks", "cards", "player", "guides"):
                    if kind not in before:
                        continue
                    if kind != "guides":
                        index[kind] = list(leaves(index[kind], fetch))
                    self.assertEqual(len(index[kind]), len(before[kind]))
                    for actual, expected in zip(index[kind], before[kind]):
                        counts["relocated"] += actual["path"] != expected["path"]
                        self.assertEqual({k: v for k, v in actual.items() if k != "path"},
                                         {k: v for k, v in expected.items() if k != "path"})
                        self.assertEqual(fetch(actual), json.loads((self.path / topic / expected["path"]).read_bytes()))
                        counts["packs"] += 1
                    index[kind] = before[kind]
                self.assertEqual(index, before)
                counts["snapshots"] += 1
        return counts

    def test_original_locations_preserve_legacy_snapshot_and_configuration_bytes(self):
        result = self.build()
        self.assertFalse(result.created)
        for topic in self.topics:
            expected = json.loads((self.path / topic.id / "reader.json").read_bytes())
            expected.update(release_id=self.release_id, publication="prepared-git-release", snapshots={}, runtime={})
            for source in (self.path / topic.id / "snapshots").glob("*.json"):
                raw = source.read_bytes()
                name = "objects/" + hashlib.sha256(raw).hexdigest() + ".json"
                self.assertEqual(result.payloads[topic.id + "/site/" + name].read(), raw)
                expected["snapshots"][source.stem] = {"path": name, "sha256": digest(raw), "bytes": len(raw)}
            for extension in ("js", "css"):
                raw = (self.path / topic.id / ("reader." + extension)).read_bytes()
                expected["runtime"][extension] = f"runtime/{hashlib.sha256(raw).hexdigest()}/reader.{extension}"
            self.assertEqual(result.payloads[topic.id + f"/site/releases/{self.release_id}.json"].read(), json_bytes(expected))

    def test_forced_rollover_references_preserve_two_snapshots_and_replay_writes_nothing(self):
        sealed = tuple(replace(part, sealed=True) for part in self.originals)
        # Fit each font/runtime file and the complete font set, but not that
        # set plus the hub runtime in one partition. Rollover stays mandatory.
        limits = capacity.Budgets(file_bytes=150_000, site_bytes=401_000, history_bytes=501_000,
                                  site_reserve_bytes=1000, history_reserve_bytes=1000)
        result = self.build(sealed, budgets=limits)
        self.assertGreater(len(result.created), len(self.topics))
        self.assertEqual(tuple(part for part in result.partitions if part.ordinal == 0), sealed)
        output = self.fixture.root / "physical-sites"
        self.assertEqual(self.materialize(result, output), len(result.placements))
        checked = self.inspect(result, output)
        self.assertEqual(checked["snapshots"], 6)
        self.assertGreater(checked["relocated"], 0)
        self.assertEqual(checked["packs"], checked["relocated"])
        before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in output.rglob("*") if p.is_file()}
        replay = self.build(result.partitions, result.placements, budgets=limits)
        self.assertFalse(replay.created)
        self.assertEqual(replay.placements, result.placements)
        self.assertEqual(replay.partitions, result.partitions)
        self.assertEqual(replay.configurations, result.configurations)
        # The write boundary skips reused payloads entirely.
        with patch.object(capacity_projection.Payload, "read", side_effect=AssertionError("reused payload read")):
            self.assertEqual(self.materialize(replay, output), 0)
        self.assertEqual(before, {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in output.rglob("*") if p.is_file()})

    def test_second_release_reuses_dependencies_and_retains_historical_urls(self):
        first = self.build(tuple(replace(part, sealed=True) for part in self.originals))
        output = self.fixture.root / "physical-sites"
        self.materialize(first, output)
        before = {p: p.read_bytes() for p in output.rglob("*") if p.is_file()}
        self.release_id = "b" * 64
        second = self.build(tuple(replace(part, sealed=True) for part in first.partitions), first.placements)
        self.assertEqual(len(second.placements) - len(second.reused), len(self.topics))
        self.assertEqual(len(second.created), len(self.topics))
        self.materialize(second, output)
        self.inspect(first, output)
        self.inspect(second, output)
        self.assertTrue(all(path.read_bytes() == data for path, data in before.items()))

    def test_changed_leaf_is_rejected_at_the_write_boundary(self):
        result = self.build()
        leaf = next(value for value in result.payloads.values() if value.source and "/data/" in value.artifact.path)
        leaf.source.write_bytes(leaf.source.read_bytes() + b" ")
        with self.assertRaisesRegex(ContractError, "changed before release write"):
            list(result.writes())

    def test_fonts_relocate_together_and_changed_bytes_fail_before_writing(self):
        result = self.build(tuple(replace(part, sealed=True) for part in self.originals))
        fonts = [item for item in result.placements if item.artifact.path.startswith("site/fonts/")]
        self.assertTrue(fonts)
        self.assertEqual({item.artifact.topic for item in fonts}, {"hub"})
        self.assertEqual(len({item.partition for item in fonts}), 1)
        self.assertNotEqual(fonts[0].partition, "hub")
        configs = [json.loads(result.payloads[topic.id + f"/site/releases/{self.release_id}.json"].read())
                   for topic in self.topics]
        self.assertTrue(all(config["fonts"] == configs[0]["fonts"] for config in configs))
        self.assertIn("Wiki-hub-Part-0001/fonts/", configs[0]["fonts"]["base"])
        audit(self.path, result, "wiki-fixture")
        font = next(result.payloads[item.artifact.key] for item in fonts if item.artifact.path.endswith(".woff2"))
        font.source.write_bytes(font.source.read_bytes() + b"\r\n")
        with self.assertRaisesRegex(ContractError, "changed before release write"):
            list(result.writes())

    def test_namespace_or_modified_candidate_is_rejected_without_writes(self):
        with self.assertRaisesRegex(ContractError, "publication namespace"):
            capacity_projection.build(self.path, self.release_id, "another-owner", self.originals)
        (self.path / "items/reader.json").write_bytes(b"{}")
        with self.assertRaisesRegex(ContractError, "modified"):
            self.build()

    def test_wrong_dependency_size_is_rejected_even_with_valid_candidate_file_hashes(self):
        source = self.path / "items/snapshots" / (self.fixture.new["snapshot_id"] + ".json")
        value = json.loads(source.read_bytes())
        value["entries"][0]["bytes"] += 1
        source.write_bytes(json_bytes(value))
        # A syntactically intact candidate is insufficient: projection must
        # check that each dependency agrees with the allocated leaf object.
        marker = self.path / "candidate.json"
        manifest = json.loads(marker.read_bytes())
        manifest["files"][source.relative_to(self.path).as_posix()] = {
            "sha256": digest(source.read_bytes()), "bytes": source.stat().st_size}
        marker.write_bytes(json_bytes(manifest))
        with self.assertRaisesRegex(ContractError, "dependency differs"):
            self.build()

    def test_oversized_real_reader_index_splits_replays_and_loads_on_demand(self):
        # Scale the index with the larger file budget required by real fonts.
        keys = ["e-" + f"{number:032x}" for number in range(800)]
        # Internal names also force nontrivial, distinct player packs to page.
        run = self.fixture.make_run("300", [self.fixture.observation(key, "Item_Internal " + key) for key in keys])
        candidate = reader.build(self.fixture.root, self.project, [run, *self.fixture.runs],
                                 bases=self.bases, max_pack_bytes=1024)
        self.path = Path(candidate["path"])
        original_index = self.path / "items/snapshots" / (run["snapshot_id"] + ".json")
        self.assertGreater(original_index.stat().st_size, 150_000)
        limits = capacity.Budgets(file_bytes=150_000, site_bytes=501_000, history_bytes=601_000,
                                  site_reserve_bytes=1000, history_reserve_bytes=1000)
        result = self.build(tuple(replace(part, sealed=True) for part in self.originals), budgets=limits)
        directories = [item for item in result.payloads.values() if item.data and
                       json.loads(item.data).get("kind") == "wiki-shard-directory"]
        self.assertTrue(directories)
        self.assertTrue(all(item.artifact.bytes <= limits.file_bytes for item in result.payloads.values()))
        audit(self.path, result, "wiki-fixture")
        output = self.fixture.root / "split-sites"
        self.materialize(result, output)
        self.assertEqual(self.inspect(result, output)["snapshots"], 9)
        replay = self.build(result.partitions, result.placements, budgets=limits)
        self.assertFalse(replay.created)
        self.assertEqual(list(replay.writes()), [])
        # The production JS reader follows the generated directories through a
        # fetch adapter over materialized files, with no browser or network.
        node = shutil.which("node")
        if node:
            control = self.fixture.root / "directory-reader.json"
            control.write_text(json.dumps({"root": str(output), "base": self.bases["items"],
                                           "configuration": result.configurations["items"],
                                           "snapshot": run["snapshot_id"], "key": keys[37], "count": len(keys)}))
            checked = subprocess.run([node, str(Path(__file__).with_name("reader_shards.test.js")), str(control)],
                                     capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        # A later release and fresh partitions must retain old directory URLs.
        before = {path: path.read_bytes() for path in output.rglob("*") if path.is_file()}
        self.release_id = "b" * 64
        later = self.build(tuple(replace(part, sealed=True) for part in result.partitions), result.placements, budgets=limits)
        self.materialize(later, output)
        self.inspect(result, output)
        self.inspect(later, output)
        self.assertTrue(all(path.read_bytes() == data for path, data in before.items()))
        # An older candidate is still readable, but its old runtime must never
        # receive the new directory format through a manual release invocation.
        marker = self.path / "candidate.json"
        manifest = json.loads(marker.read_bytes())
        source = self.path / "items/reader.json"
        configuration = json.loads(source.read_bytes())
        del configuration["features"]
        source.write_bytes(packs.compact(configuration))
        manifest["files"]["items/reader.json"] = {"sha256": digest(source.read_bytes()), "bytes": source.stat().st_size}
        marker.write_bytes(json_bytes(manifest))
        with self.assertRaisesRegex(ContractError, "runtime does not support"):
            self.build(budgets=limits)

    def test_same_directory_requested_twice_in_one_plan_is_written_once(self):
        data = packs.compact({"schema_version": 1, "kind": "wiki-shard-directory", "shards": []})
        def repeated(indexes, limit, emit):
            self.assertEqual(emit([("items", data)]), emit([("items", data)]))
            return indexes
        with patch.object(shard_index, "compact", side_effect=repeated):
            result = self.build()
        key = "items/site/objects/" + digest(data) + ".json"
        self.assertEqual(sum(item.artifact.key == key for item, _ in result.writes()), 1)
        self.assertNotIn(key, result.reused)

    def test_capture_catalog_preserves_physical_history_and_browser_selection(self):
        # Enough captures to force paging above the real font/runtime budget.
        runs = [self.fixture.make_run(str(build), []) for build in reversed(range(1000, 1400))]
        self.path = Path(reader.build(self.fixture.root, self.project, runs, bases=self.bases)["path"])
        limits = capacity.Budgets(file_bytes=150_000, site_bytes=501_000, history_bytes=601_000,
                                  site_reserve_bytes=1000, history_reserve_bytes=1000)
        result = self.build(tuple(replace(part, sealed=True) for part in self.originals), budgets=limits)
        output = self.fixture.root / "capture-sites"
        self.materialize(result, output)
        self.assertEqual(audit(self.path, result, "wiki-fixture")["snapshots"], 1200)
        self.assertEqual(self.inspect(result, output)["snapshots"], 1200)
        self.assertTrue(all(item.artifact.bytes <= limits.file_bytes for item in result.payloads.values()))
        self.assertTrue(all("capture_catalog" in json.loads(result.payloads[topic.id + f"/site/releases/{self.release_id}.json"].read())
                            for topic in self.topics))
        node = shutil.which("node")
        if node:
            control = self.fixture.root / "capture-reader.json"
            control.write_text(json.dumps({"root": str(output), "base": self.bases["items"],
                "configuration": result.configurations["items"], "selected": runs[-3]["snapshot_id"],
                "expected": [run["snapshot_id"] for run in runs]}))
            checked = subprocess.run([node, str(Path(__file__).with_name("reader_captures.test.js")), str(control)],
                                     capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        replay = self.build(result.partitions, result.placements, budgets=limits)
        self.assertEqual(list(replay.writes()), [])
        self.assertEqual(replay.configurations, result.configurations)
        before = {path: path.read_bytes() for path in output.rglob("*") if path.is_file()}
        self.release_id = "b" * 64
        newer = self.fixture.make_run("1400", [])
        self.path = Path(reader.build(self.fixture.root, self.project, [newer, *runs], bases=self.bases)["path"])
        later = self.build(tuple(replace(part, sealed=True) for part in result.partitions), result.placements, budgets=limits)
        self.materialize(later, output)
        self.assertEqual(self.inspect(later, output)["snapshots"], 1203)
        self.assertTrue(all(path.read_bytes() == data for path, data in before.items()))
        old_objects = {key for key in result.payloads if "/objects/" in key}
        self.assertGreater(len(old_objects & set(later.reused)), 1200)

    def test_independent_auditor_rejects_changed_snapshot_membership(self):
        self.check_changed_snapshot_membership("entries")

    def test_independent_auditor_rejects_changed_card_membership(self):
        self.check_changed_snapshot_membership("cards")

    def test_independent_auditor_rejects_changed_player_membership(self):
        self.check_changed_snapshot_membership("player")

    def test_independent_auditor_rejects_changed_guide_membership(self):
        self.check_changed_snapshot_membership("guides")

    def check_changed_snapshot_membership(self, kind):
        result = self.build(tuple(replace(part, sealed=True) for part in self.originals))
        checked = audit(self.path, result, "wiki-fixture")
        self.assertGreater(checked["pack_references"], 0)
        key = next(key for key, payload in result.payloads.items()
                   if "/site/objects/" in key and json.loads(payload.read()).get(kind))
        old = result.payloads[key]
        value = json.loads(old.read())
        value[kind][0]["title" if kind == "guides" else "first"] = "corrupted-member-boundary"
        data = json_bytes(value)
        # Keep the forged payload internally self-consistent. The audit must
        # still reject disagreement with the candidate, even if hashes pass.
        changed = replace(old, data=data, artifact=replace(old.artifact, path="site/objects/" + digest(data) + ".json",
                                                         sha256=digest(data), bytes=len(data)))
        config_key = old.artifact.topic + f"/site/releases/{self.release_id}.json"
        old_config = result.payloads[config_key]
        config = json.loads(old_config.read())
        for reference in config["snapshots"].values():
            if reference["sha256"] == old.artifact.sha256:
                reference.update(path=reference["path"].replace(old.artifact.sha256, changed.artifact.sha256),
                                 sha256=changed.artifact.sha256, bytes=changed.artifact.bytes)
        config_data = json_bytes(config)
        changed_config = replace(old_config, data=config_data,
                                 artifact=replace(old_config.artifact, sha256=digest(config_data), bytes=len(config_data)))
        replacements = {key: changed, config_key: changed_config}
        payloads = {k: v for k, v in result.payloads.items() if k not in replacements}
        payloads.update({value.artifact.key: value for value in replacements.values()})
        placements = tuple(replace(item, artifact=replacements[item.artifact.key].artifact)
                           if item.artifact.key in replacements else item for item in result.placements)
        configurations = {topic: dict(ref) for topic, ref in result.configurations.items()}
        configurations[old.artifact.topic].update(sha256=changed_config.artifact.sha256, bytes=changed_config.artifact.bytes)
        result = replace(result, payloads=payloads, placements=placements, configurations=configurations)
        with self.assertRaises(AssertionError):
            audit(self.path, result, "wiki-fixture")


class ReferenceTransformTests(unittest.TestCase):
    def test_only_declared_pack_paths_change_and_bad_references_fail(self):
        sha = "a" * 64
        pack = {"path": "data/" + sha + ".json", "sha256": sha, "bytes": 3}
        value = {"schema_version": 1, **{kind: [] for kind in release_content.SHARD_KINDS},
                 "evidence": {"path": pack["path"]}, "entries": [pack]}
        before = json_bytes(value)
        result = release_content.snapshot(before, lambda path, *_: "https://example.invalid/" + path)
        self.assertEqual(json.loads(result)["evidence"], value["evidence"])
        self.assertEqual(release_content.snapshot(before, lambda path, *_: path), before)
        pack["path"] = "../../private"
        with self.assertRaisesRegex(ContractError, "content-addressed"):
            release_content.snapshot(json_bytes(value), lambda path, *_: path)

    def test_card_references_relocate_and_legacy_indexes_keep_exact_bytes(self):
        sha = "b" * 64
        pack = {"path": "data/" + sha + ".json", "sha256": sha, "bytes": 3}
        value = {"schema_version": 1, **{kind: [] for kind in release_content.SHARD_KINDS}, "cards": [pack]}
        result = release_content.snapshot(json_bytes(value), lambda path, *_: "https://example.invalid/" + path)
        self.assertEqual(json.loads(result)["cards"], [{**pack, "path": "https://example.invalid/" + pack["path"]}])
        del value["cards"]
        value["entries"] = [pack]
        before = json_bytes(value)
        self.assertEqual(release_content.snapshot(before, lambda path, *_: path), before)
        relocated = json.loads(release_content.snapshot(before, lambda path, *_: "https://example.invalid/" + path))
        self.assertNotIn("cards", relocated)
        self.assertEqual(relocated["entries"], [{**pack, "path": "https://example.invalid/" + pack["path"]}])
        for kind in ("entries", "semantics", "provenance", "search", "backlinks"):
            with self.subTest(missing=kind), self.assertRaises(KeyError):
                release_content.snapshot(json_bytes({key: val for key, val in value.items() if key != kind}),
                                         lambda path, *_: path)

    def test_configuration_requires_all_selected_snapshots_and_runtime(self):
        data = json_bytes({"schema_version": 1, "versions": [{"snapshot_id": "one"}]})
        with self.assertRaisesRegex(ContractError, "snapshot coverage"):
            release_content.configuration(data, "a" * 64, {}, {"js": "script", "css": "style"})
        with self.assertRaisesRegex(ContractError, "both reader runtimes"):
            release_content.configuration(data, "a" * 64, {"one": {}}, {"js": "script"})

    def test_player_references_relocate_and_legacy_indexes_keep_exact_bytes(self):
        sha = "c" * 64
        pack = {"path": "data/" + sha + ".json", "sha256": sha, "bytes": 3}
        value = {"schema_version": 1, **{kind: [] for kind in release_content.SHARD_KINDS}, "player": [pack]}
        result = json.loads(release_content.snapshot(json_bytes(value), lambda path, *_: "https://example.invalid/" + path))
        self.assertEqual(result["player"], [{**pack, "path": "https://example.invalid/" + pack["path"]}])
        del value["player"]
        before = json_bytes(value)
        self.assertEqual(release_content.snapshot(before, lambda path, *_: path), before)
        self.assertNotIn("player", json.loads(release_content.snapshot(before, lambda path, *_: path)))


if __name__ == "__main__":
    unittest.main()
