"""Reader paths retain their capacity roles and rejection boundaries."""

from dataclasses import asdict, replace
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from tests._support import fixture_dir
from wikibuild import capacity, capacity_projection
from wikibuild.capacity_projection import classify_reader_path
from wikibuild.storage import ContractError, digest, json_bytes


class ReaderPathClassificationTests(unittest.TestCase):
    def test_accepted_paths_keep_their_roles(self):
        sha = "a" * 64
        cases = [
            ("items", f"data/{sha}.json", "leaf"),
            ("hub", f"fonts/{sha}/Newsreader-Italic.woff2", "leaf"),
            ("hub", f"fonts/{sha}/fonts.css", "leaf"),
            ("hub", f"fonts/{sha}/OFL-newsreader.txt", "leaf"),
            ("items", "reader.js", "runtime"),
            ("hub", "reader.css", "runtime"),
            ("loot", "snapshots/build-0-0123456789ab.json", "snapshot"),
            ("hub", "snapshots/build-001-aabbccddeeff.json", "snapshot"),
            ("items", "reader.json", "configuration"),
            ("items", "index.html", "mutable"),
            ("hub", "404.html", "mutable"),
            ("loot", ".nojekyll", "mutable"),
            ("items", "groups/item-2/index.html", "mutable"),
            ("hub", "reference/guides/getting-started.md", "mutable"),
            ("items", "reference/item/0000.md", "mutable"),
            ("loot", "reference/loot-source/10000.md", "mutable"),
            ("items", "reference/guides/0001.md", "mutable"),
        ]
        for topic, path, expected in cases:
            with self.subTest(topic=topic, path=path):
                self.assertEqual(classify_reader_path(topic, path), expected)
                self.assertEqual(classify_reader_path(topic, path), expected)

    def test_near_misses_keep_the_exact_error(self):
        sha = "a" * 64
        cases = [("items", path) for path in (
            "", "reader.JS", "nested/reader.js", "reader.js\n", "reader.json/",
            f"data/{sha[:-1]}.json", f"data/{sha.upper()}.json", f"data/{sha}.JSON",
            "snapshots/build--1-0123456789ab.json", "snapshots/build-1-0123456789abc.json",
            "groups/Item/index.html", "groups/2item/index.html", "groups/item/other.html",
            "reference/item/001.md", "reference/Item/0001.md", "reference/item/0001.txt",
            "reference/guides/start.md", f"fonts/{sha}/fonts.css", "../reader.js",
            f"runtime/{sha}/reader.js",
        )]
        cases += [("hub", path) for path in (
            f"fonts/{sha}/font.ttf", f"fonts/{sha}/font_name.woff2",
            f"fonts/{sha[:-1]}/font.woff2", f"fonts/{sha}/nested/font.woff2",
            "reference/guides/Start.md", "reference/guides/start/index.md",
        )]
        for topic, path in cases:
            with self.subTest(topic=topic, path=path), self.assertRaises(ContractError) as raised:
                classify_reader_path(topic, path)
            self.assertEqual(str(raised.exception),
                             f"Unexpected reader output for capacity projection: {topic}/{path}")


class ProjectionPhaseTests(unittest.TestCase):
    def setUp(self):
        self.root = fixture_dir(self, "cp-phase")
        self.owner, self.release = "fixture", "a" * 64
        self.topics = [capacity.Topic(topic, "Wiki-" + topic) for topic in ("hub", "items")]
        self.bases = {topic.id: f"https://fixture.github.io/{topic.github_name}/" for topic in self.topics}

    def candidate(self, *, fonts=False, articles=False):
        files = {}
        def output(name, data):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            files[name] = {"bytes": len(data), "sha256": digest(data)}
        font_set = None
        if fonts:
            contents = {"fonts.css": b"font", "Face.woff2": b"font-bytes", "OFL.txt": b"license"}
            metadata = {name: {"bytes": len(data), "sha256": digest(data)} for name, data in contents.items()}
            folder = "fonts/" + digest(json_bytes(metadata)) + "/"
            font_set = {"base": self.bases["hub"] + folder, "files": metadata}
            for name, data in contents.items():
                output("hub/" + folder + name, data)
        snapshot = "build-1-" + "b" * 12
        for topic in self.topics:
            data = b'{"a":{}}'
            sha = digest(data)
            ref = {"path": f"data/{sha}.json", "sha256": sha, "bytes": len(data),
                   "first": "a", "last": "a", "count": 1}
            output(topic.id + "/" + ref["path"], data)
            output(topic.id + "/reader.js", b"script")
            output(topic.id + "/reader.css", b"style")
            index = {"schema_version": 1, "entries": [ref], "semantics": [], "provenance": [],
                     "search": [], "backlinks": [], "cards": [], "player": [], "guides": []}
            output(topic.id + "/snapshots/" + snapshot + ".json", json_bytes(index))
            output(topic.id + "/reader.json", json_bytes({"schema_version": 1,
                   "versions": [{"snapshot_id": snapshot}], "fonts": font_set,
                   "features": ["shard-directories-v1", "entrypoint-rollover-v1"],
                   "external_articles": {"schema_version": 1, "entries": [ref]} if articles else None}))
            output(topic.id + "/index.html", b"shell")
        inputs = {"project": {"repositories": [{"id": topic.id, "github_name": topic.github_name}
                                               for topic in self.topics]}, "bases": self.bases}
        manifest = {"schema_version": 1, "candidate_id": digest(json_bytes(inputs)), "inputs": inputs, "files": files}
        (self.root / "candidate.json").write_bytes(json_bytes(manifest))
        return manifest

    def build(self, **kwargs):
        partitions = tuple(capacity.partition(topic, 0, sealed=kwargs.pop("sealed", False)) for topic in self.topics)
        return capacity_projection.build(self.root, self.release, self.owner, partitions, **kwargs)

    def fingerprint(self, projection):
        def encode(value):
            if isinstance(value, Path):
                return value.relative_to(self.root).as_posix()
            if isinstance(value, bytes):
                return value.hex()
            raise TypeError(type(value))
        record = asdict(projection)
        record["writes"] = [(asdict(placement), data.hex()) for placement, data in projection.writes()]
        return digest(json.dumps(record, sort_keys=True, separators=(",", ":"), default=encode).encode())

    def test_complete_projection_and_write_bytes(self):
        self.candidate()
        self.assertEqual(self.fingerprint(self.build()), "1177d8c0db7084ab2f3096d92e4040c9558858fce2aba0c97de2fdb4644df90c")

    def test_complete_relocated_fonts_articles_and_entrypoints(self):
        self.candidate(fonts=True, articles=True)
        entrypoints = {topic: base + "successor/" for topic, base in self.bases.items()}
        self.assertEqual(self.fingerprint(self.build(sealed=True, entrypoints=entrypoints)), "e609fde976117cb01e7e1e2467cfcfb09a4b8aee191b0bba6b4d7be86747c302")

    def test_configuration_metadata_and_font_errors_are_exact(self):
        self.candidate(fonts=True)
        cases = [("hub", lambda value: value["fonts"].update(base="wrong/"), "Font set differs from candidate content"),
                 ("items", lambda value: value.update(fonts=None), "Topics disagree on the shared font set")]
        for topic, change, expected in cases:
            self.candidate(fonts=True)
            path = self.root / topic / "reader.json"
            value = json.loads(path.read_bytes())
            change(value)
            data = json_bytes(value)
            path.write_bytes(data)
            marker = self.root / "candidate.json"
            manifest = json.loads(marker.read_bytes())
            manifest["files"][topic + "/reader.json"] = {"sha256": digest(data), "bytes": len(data)}
            marker.write_bytes(json_bytes(manifest))
            with self.subTest(topic=topic), self.assertRaises(ContractError) as raised:
                self.build()
            self.assertEqual(str(raised.exception), expected)

    def test_payload_addition_and_located_references_preserve_exact_records(self):
        payloads, data = {}, b"payload"
        name = "site/data/" + digest(data) + ".json"
        artifact = capacity_projection.add_payload(payloads, "items", name, data=data)
        self.assertEqual(artifact, capacity.Artifact("items", name, digest(data), len(data)))
        self.assertEqual(payloads, {artifact.key: capacity_projection.Payload(artifact, data=data)})
        self.assertEqual(capacity_projection.add_payload(payloads, "items", name, data=data), artifact)
        with self.assertRaises(ContractError) as raised:
            capacity_projection.add_payload(payloads, "items", name, data=b"changed")
        self.assertEqual(str(raised.exception), "Conflicting projected object")
        relative = name.removeprefix("site/")
        part = capacity.partition(self.topics[1], 1)
        located = {artifact.key: capacity.Placement(artifact, "items")}
        self.assertEqual(capacity_projection.located_reference(located, {}, self.owner, "items", relative,
                                                               artifact.sha256, artifact.bytes), relative)
        located[artifact.key] = capacity.Placement(artifact, part.id)
        self.assertEqual(capacity_projection.located_reference(located, {part.id: part}, self.owner, "items", relative,
                                                               artifact.sha256, artifact.bytes), self.bases["items"].replace("Wiki-items/", "Wiki-items-Part-0001/") + relative)
        for sha, size in (("0" * 64, len(data)), (digest(data), len(data) + 1)):
            with self.assertRaises(ContractError) as raised:
                capacity_projection.located_reference(located, {part.id: part}, self.owner, "items", relative, sha, size)
            self.assertEqual(str(raised.exception), f"Snapshot dependency differs from allocated object: items/{relative}")

    def test_metadata_verification_and_directory_feature_gate_are_exact(self):
        manifest = self.candidate()
        configs = {topic.id: (self.root / topic.id / "reader.json", manifest["files"][topic.id + "/reader.json"])
                   for topic in self.topics}
        source, metadata = configs["items"]
        self.assertEqual(capacity_projection.verified_metadata(source, metadata), source.read_bytes())
        batch, token = [("items", b"{}")], object()
        emit = Mock(return_value=token)
        self.assertIs(capacity_projection.project_directories(configs, batch, emit), token)
        emit.assert_called_once_with(batch)
        source.write_bytes(source.read_bytes() + b" ")
        with self.assertRaises(ContractError) as raised:
            capacity_projection.verified_metadata(source, metadata)
        self.assertEqual(str(raised.exception), "Reader metadata changed during capacity projection")
        value = json.loads(source.read_bytes())
        value["features"] = []
        data = json_bytes(value)
        source.write_bytes(data)
        configs["items"] = source, {"sha256": digest(data), "bytes": len(data)}
        emit.reset_mock()
        with self.assertRaises(ContractError) as raised:
            capacity_projection.project_directories(configs, batch, emit)
        self.assertEqual(str(raised.exception), "Reader runtime does not support shard directories; regenerate the candidate")
        emit.assert_not_called()

    def test_metadata_objects_allocate_before_resolving_and_repeat_identically(self):
        payloads, events = {}, []
        def add(topic, name, **kwargs):
            return capacity_projection.add_payload(payloads, topic, name, **kwargs)
        def allocate(objects):
            events.append(tuple(objects))
        def reference(topic, name, sha, size):
            self.assertTrue(events)
            return topic + "/" + name
        batch = [("items", b"{}"), ("hub", b"[]")]
        expected = [{"path": topic + "/objects/" + digest(data) + ".json", "sha256": digest(data), "bytes": len(data)}
                    for topic, data in batch]
        self.assertEqual(capacity_projection.project_metadata_objects(batch, add, allocate, reference), expected)
        self.assertEqual(capacity_projection.project_metadata_objects(batch, add, allocate, reference), expected)
        self.assertEqual(events[0], events[1])
        self.assertEqual([payloads[item.key].read() for item in events[0]], [b"{}", b"[]"])

    def test_font_files_need_configuration_and_one_partition(self):
        manifest = self.candidate(fonts=True)
        projection = self.build()
        configs = {topic.id: (self.root / topic.id / "reader.json", manifest["files"][topic.id + "/reader.json"])
                   for topic in self.topics}
        located = {item.artifact.key: item for item in projection.placements}
        partitions = {part.id: part for part in projection.partitions}
        expected = json.loads(configs["hub"][0].read_bytes())["fonts"]
        self.assertEqual(capacity_projection.project_fonts(manifest, configs, self.bases, located, partitions, self.owner), expected)
        key = next(key for key in located if key.startswith("hub/site/fonts/"))
        located[key] = replace(located[key], partition="different")
        with self.assertRaises(ContractError) as raised:
            capacity_projection.project_fonts(manifest, configs, self.bases, located, partitions, self.owner)
        self.assertEqual(str(raised.exception), "Font set spans multiple partitions")
        source = configs["hub"][0]
        value = json.loads(source.read_bytes())
        value["fonts"] = None
        data = json_bytes(value)
        source.write_bytes(data)
        configs["hub"] = source, {"sha256": digest(data), "bytes": len(data)}
        with self.assertRaises(ContractError) as raised:
            capacity_projection.project_fonts(manifest, configs, self.bases, located, partitions, self.owner)
        self.assertEqual(str(raised.exception), "Font files have no configuration")


if __name__ == "__main__":
    unittest.main()
