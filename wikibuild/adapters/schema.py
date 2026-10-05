"""Small explicit field contracts. Unsupported values never become facts."""

from dataclasses import dataclass, field
from collections import Counter
import math
import re


NUMBER = (int, float)
V2 = {"x": NUMBER, "y": NUMBER}
V3 = {"x": NUMBER, "y": NUMBER, "z": NUMBER}
UNITY = set("m_Enabled m_GameObject m_Name m_Script".split())
OMIT = object()


@dataclass(frozen=True)
class Ref:
    predicate: str


@dataclass(frozen=True)
class EnglishText:
    """Project an English _Infos entry into its parent's text facts."""
    field: str
    optional: tuple = ()
    excluded: frozenset = frozenset()


@dataclass(frozen=True)
class NumberWithSentinel:
    """Opt-in to exact catalog-encoded float markers used by a source contract."""
    markers: frozenset


@dataclass(frozen=True)
class IndexCounts:
    """Composition counts from explicit prototype indices, without placement rows."""
    table: str
    excluded: str


@dataclass(frozen=True)
class Fields:
    selected: dict
    excluded: frozenset = frozenset()


@dataclass(frozen=True)
class Component:
    assembly: str
    name: str
    kind: str
    topic: str
    fields: Fields
    notes: str = "Serialized configuration; runtime code and settings may modify these values."
    summary_only: bool = False
    identity: dict = field(default_factory=dict)


def fields(selected, excluded=""):
    return Fields(selected, frozenset(excluded.split()))


def numbers(names):
    return dict.fromkeys(names.split(), NUMBER)


def component(assembly, name, kind, topic, selected, excluded="", **kwargs):
    return Component(assembly, name, kind, topic,
                     Fields(selected, frozenset(excluded.split()) | UNITY), **kwargs)


class Selection:
    def __init__(self, record, spec, issues):
        self.record, self.spec, self.issues = record, spec, issues
        self.links = []
        self.evidence = []
        self.references = {ref["field"]: ref for ref in record.get("references", [])}

    def issue(self, code, path, message):
        # List indices identify evidence, but not a separate exception pattern.
        pattern = self.spec.name + re.sub(r"/\d+(?=/|$)", "/*", path)
        self.issues.add(code, self.spec.topic, pattern, message, self.record["id"])

    def select(self, value, schema, path=""):
        if isinstance(schema, EnglishText):
            result = {schema.field: None}
            if not isinstance(value, list):
                self.invalid(path)
                return result
            candidates = []
            known = {"languageType", schema.field, *schema.optional} | schema.excluded
            for index, entry in enumerate(value):
                pointer = f"{path}/{index}"
                if not isinstance(entry, dict):
                    self.invalid(pointer)
                    continue
                for key in sorted(entry.keys() - known):
                    self.issue("new-field", pointer + "/" + key,
                               "A new source field needs an extraction decision; known fields were processed.")
                if type(entry.get("languageType")) is not int:
                    self.invalid(pointer + "/languageType")
                    continue
                # Language/Language.decompiled.cs: LanguageType.English = 2.
                # This is the stored enum value, never the list position.
                if entry["languageType"] == 2:
                    candidates.append((pointer, entry))
            if len(candidates) != 1:
                self.issue("english-text", path,
                           "No unique English entry; the selected text is null.")
                self.evidence.append(path)
                return result
            pointer, entry = candidates[0]
            self.evidence.append(pointer + "/languageType")
            for key in (schema.field, *schema.optional):
                if key not in entry:
                    if key == schema.field:
                        self.issue("missing-field", pointer + "/" + key,
                                   "The English text field is absent; its fact is null.")
                    continue
                selected = self.select(entry[key], str, pointer + "/" + key)
                result[key] = None if selected is OMIT else selected
            return result
        if isinstance(schema, IndexCounts):
            table = self.record.get("fields", {}).get(schema.table)
            if not isinstance(value, list) or not isinstance(table, list):
                return self.invalid(path)
            counts, unresolved = Counter(), 0
            entry_schema = fields({"protoRefIndex": int}, schema.excluded)
            for index, entry in enumerate(value):
                evidence_start = len(self.evidence)
                selected = self.select(entry, entry_schema, f"{path}/{index}")
                # One source-array locator plus the raw-record hash proves the
                # derivation. Repeated placement locators add no catalog facts.
                del self.evidence[evidence_start:]
                key = selected.get("protoRefIndex") if selected is not OMIT else None
                if key is None:
                    unresolved += 1
                elif not 0 <= key < len(table):
                    unresolved += 1
                    self.issue("prototype-index-range", f"{path}/{index}/protoRefIndex",
                               "A placement index is outside its prototype table; other counts were retained.")
                else:
                    counts[key] += 1
            self.evidence.append(path)
            return {"counts": [{"protoRefIndex": key, "count": count} for key, count in sorted(counts.items())],
                    "total_count": len(value), "unresolved_count": unresolved}
        if isinstance(schema, dict):
            schema = Fields(schema)
        if isinstance(schema, Fields):
            if not isinstance(value, dict):
                return self.invalid(path)
            result = {}
            for key, child in schema.selected.items():
                pointer = path + "/" + key.replace("~", "~0").replace("/", "~1")
                if key not in value:
                    self.issue("missing-field", pointer, "A known field is absent; dependent facts were omitted.")
                    if isinstance(child, EnglishText):
                        result[child.field] = None
                    continue
                selected = self.select(value[key], child, pointer)
                if isinstance(child, EnglishText):
                    result.update(selected)
                elif selected is not OMIT:
                    result[key] = selected
            for key in sorted(value.keys() - schema.selected.keys() - schema.excluded):
                self.issue("new-field", path + "/" + key,
                           "A new source field needs an extraction decision; known fields were processed.")
            return result
        if isinstance(schema, list):
            if not isinstance(value, list):
                return self.invalid(path)
            result = []
            for index, entry in enumerate(value):
                selected = self.select(entry, schema[0], f"{path}/{index}")
                # Preserve source list positions. Null explicitly marks a gap.
                result.append(None if selected is OMIT else selected)
            return result
        if isinstance(schema, NumberWithSentinel):
            if isinstance(value, dict):
                if (set(value) == {"float"} and isinstance(value["float"], str)
                        and value["float"] in schema.markers):
                    self.evidence.append(path)
                    return {"float": value["float"]}
                return self.invalid(path)
            return self.select(value, NUMBER, path)
        if isinstance(schema, Ref):
            if not isinstance(value, dict):
                return self.invalid(path)
            if "m_PathID" in value:
                if type(value.get("m_PathID")) is not int or type(value.get("m_FileID")) is not int:
                    return self.invalid(path)
                expected = {"m_PathID", "m_FileID"}
                null = value["m_PathID"] == 0
            elif "m_AssetGUID" in value and isinstance(value["m_AssetGUID"], str):
                expected = {"m_AssetGUID", "m_SubObjectName", "m_SubObjectType"}
                null = not value["m_AssetGUID"]
            else:
                return self.invalid(path)
            for key in sorted(value.keys() - expected):
                self.issue("new-field", path + "/" + key,
                           "A new source field needs an extraction decision; known fields were processed.")
            if null:
                self.evidence.append(path)
                return OMIT
            ref = self.references.get(path)
            if ref is None:
                self.issue("unresolved-reference", path, "A selected relationship could not be resolved.")
                self.links.append({"predicate": schema.predicate, "source_field": path, "status": "missing"})
            elif ref.get("status") != "null":
                status = ref.get("status", "unknown")
                if status != "resolved":
                    self.issue("unresolved-reference", path, "A selected relationship could not be resolved.")
                self.links.append({"predicate": schema.predicate, "source_field": path, "status": status,
                                   "target_source_ids": sorted(ref.get("targets", [ref["target"]] if "target" in ref else [])),
                                   **({"guid": ref["guid"]} if "guid" in ref else {})})
            self.evidence.append(path)
            return OMIT
        if not isinstance(value, schema) or isinstance(value, bool):
            return self.invalid(path)
        if isinstance(value, float) and not math.isfinite(value):
            self.issue("invalid-number", path, "A numeric field is not finite; its fact was omitted.")
            return OMIT
        self.evidence.append(path)
        return value

    def invalid(self, path):
        self.issue("unsupported-field-type", path, "A field has an unsupported type; its fact was omitted.")
        return OMIT
