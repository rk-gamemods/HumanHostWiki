"""Large-record selection must preserve drift detection and byte integrity."""

import copy
import hashlib
import io
import json
import unittest

from wikibuild.source_record import read_record
from wikibuild.storage import ContractError


def fixture():
    row = {"id": "fixture#1", "script": {"class": "Fixture", "assembly": "Test"},
           "fields": {"geometry": [{"x": 1, "y": 2}] * 90000,
                      "speed": 3.5, "新/field": {"future": True}}, "references": []}
    encode = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    data = encode(row) + b"\n"
    members = {key: ({name: len(encode(value)) for name, value in row[key].items()}
                     if key == "fields" else len(encode(row[key]))) for key in row}
    return row, data, {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "members": members}


class SourceRecordTests(unittest.TestCase):
    def test_selective_read_bounds_requests_preserves_names_and_verifies_all_bytes(self):
        row, data, location = fixture()
        stream, requests = io.BytesIO(data), []
        def read(size):
            requests.append(size)
            return stream.read(size)
        selected = read_record(read, location, {"speed"})
        self.assertEqual({"geometry": None, "speed": 3.5, "新/field": None}, selected["fields"])
        self.assertEqual(row["script"], selected["script"])
        self.assertEqual(len(data), stream.tell())
        self.assertLessEqual(max(requests), 64 * 1024)
        self.assertEqual(row, read_record(io.BytesIO(data).read, location))

    def test_changes_in_skipped_values_fail_hash_verification(self):
        _, data, location = fixture()
        changed = data.replace(b'"x": 1', b'"x": 9', 1)
        self.assertIsNone(read_record(io.BytesIO(changed).read, location, {"speed"}))

    def test_malformed_index_cannot_hide_rename_or_shift_value(self):
        _, data, location = fixture()
        for mutation in ("rename", "missing", "extra", "overlap", "bool", "nested", "trailing"):
            bad = copy.deepcopy(location)
            members = bad["members"]["fields"]
            if mutation == "rename":
                members["other"] = members.pop("speed")
            elif mutation == "missing":
                members.pop("speed")
            elif mutation == "extra":
                members["extra"] = 4
            elif mutation == "overlap":
                members["geometry"] += 1
            elif mutation == "bool":
                members["speed"] = True
            elif mutation == "nested":
                members["geometry"] = {}
            else:
                bad["bytes"] -= 1
                bad["sha256"] = hashlib.sha256(data[:-1]).hexdigest()
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                read_record(io.BytesIO(data).read, bad, {"speed"})

    def test_legacy_record_and_partial_reads_remain_supported(self):
        row, data, location = fixture()
        location.pop("members")
        self.assertEqual(row, read_record(io.BytesIO(data).read, location, {"speed"}))
        self.assertIsNone(read_record(io.BytesIO(data[:-10]).read, location, {"speed"}))


if __name__ == "__main__":
    unittest.main()
