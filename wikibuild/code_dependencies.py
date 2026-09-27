"""Hash explicitly declared C# symbols without publishing their source text.

This checks syntactic dependency stability, not runtime behavior or inferred
transitive dependencies. Callers must declare helpers/constants their claim uses.
"""

from importlib import metadata
from pathlib import Path
import re

from .storage import ContractError, digest, json_bytes


TYPES = {"class_declaration", "struct_declaration", "interface_declaration",
         "record_declaration", "enum_declaration"}
KINDS = {"method": "method_declaration", "field": "field_declaration",
         "property": "property_declaration", "constructor": "constructor_declaration"}


class SelectionError(ValueError):
    """A changed or unsupported source cannot satisfy this declared check."""


def runtime(required=False):
    path = Path(__file__).resolve().parents[1] / "requirements-source.txt"
    pins = dict(line.split("==") for line in path.read_text().splitlines() if line and not line.startswith("#"))
    versions = {}
    for name in pins:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    if required and versions != pins:
        raise ContractError("Named C# checks require the pinned parser packages; run py -3 -m pip install -r requirements-source.txt")
    return {"required": pins, "installed": versions}


def validate(selector):
    if not isinstance(selector, dict) or not isinstance(selector.get("kind"), str) or selector["kind"] not in {*KINDS, "type"}:
        raise ContractError("Unknown C# symbol selector kind")
    required = {"type", "kind"}
    if selector["kind"] != "type":
        required.add("member")
    if selector["kind"] in {"method", "constructor"}:
        required.add("parameters")
    if set(selector) != required:
        raise ContractError("C# symbol selector has unknown or missing fields")
    for name in ("type", "member"):
        if name in selector and (not isinstance(selector[name], str) or not 1 <= len(selector[name]) <= 512
                                 or any(char in selector[name] for char in "\r\n\0")):
            raise ContractError("C# selector needs a bounded qualified type/member name")
    if "parameters" in selector:
        values = selector["parameters"]
        if not isinstance(values, list) or len(values) > 32 or any(
                not isinstance(value, str) or not 1 <= len(value) <= 256 or
                any(char in value for char in "\r\n\0") for value in values):
            raise ContractError("C# selector needs bounded parameter types")
    return selector


def key(dependency):
    if "symbol" not in dependency:
        return dependency["path"]
    return dependency["path"] + "#" + digest(json_bytes(dependency["symbol"]))


class Document:
    def __init__(self, data):
        runtime(required=True)
        from tree_sitter import Language, Parser
        import tree_sitter_c_sharp
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SelectionError("code-encoding-error") from exc
        self.data = data
        self.tree = Parser(Language(tree_sitter_c_sharp.language())).parse(data)
        if self.tree.root_node.has_error:
            raise SelectionError("code-parse-error")
        self.types = {}
        self._collect(self.tree.root_node, "", [], [])

    def text(self, node):
        return self.data[node.start_byte:node.end_byte].decode("utf-8")

    def tokens(self, node):
        result, stack = [], [node]
        while stack:
            current = stack.pop()
            if current.type == "comment":
                continue
            if current.child_count:
                stack.extend(reversed(current.children))
            else:
                result.append([current.type, self.text(current)])
        return result

    def _collect(self, container, namespace, owners, context):
        children = container.named_children
        # Imports/aliases and assembly/namespace attributes affect interpretation.
        # Keep them as conservative dependencies even for a single member check.
        extras = [self.tokens(node) for node in children
                  if node.type not in TYPES | {"namespace_declaration", "file_scoped_namespace_declaration", "comment"}
                  and not owners]
        context = context + extras
        for node in children:
            if node.type == "file_scoped_namespace_declaration":
                namespace = self.text(node.child_by_field_name("name"))
                context = context + [self.tokens(node)]
            elif node.type == "namespace_declaration":
                name = self.text(node.child_by_field_name("name"))
                body = node.child_by_field_name("body")
                header = [self.tokens(child) for child in node.children if child != body]
                self._collect(body, ".".join(filter(None, (namespace, name))), owners, context + header)
            elif node.type in TYPES:
                name = self.text(node.child_by_field_name("name"))
                body = node.child_by_field_name("body")
                header = [self.tokens(child) for child in node.children if child != body]
                qualified = ".".join(filter(None, [namespace, *owners, name]))
                self.types.setdefault(qualified, []).append((node, context + header))
                if body is not None:
                    self._collect(body, namespace, [*owners, name], context + header)

    def _parameters(self, node):
        parameters = node.child_by_field_name("parameters")
        if parameters is None:
            return []
        result = []
        # Grammar 0.23.5 exposes a final params array directly on parameter_list.
        variadic_type = parameters.child_by_field_name("type")
        variadic_name = parameters.child_by_field_name("name")
        for parameter in parameters.named_children:
            if parameter.type == "comment" or parameter in (variadic_type, variadic_name):
                continue
            if parameter.type != "parameter":
                raise SelectionError("unsupported-code-parameters")
            kind = parameter.child_by_field_name("type")
            if kind is None:
                raise SelectionError("unsupported-code-parameters")
            prefix = "".join(self.text(child) for child in parameter.children
                             if child.type == "modifier")
            result.append(re.sub(r"\s+", "", prefix + self.text(kind)))
        if variadic_type is not None:
            if variadic_name is None or not any(child.type == "params" for child in parameters.children):
                raise SelectionError("unsupported-code-parameters")
            result.append("params" + re.sub(r"\s+", "", self.text(variadic_type)))
        return result

    def select(self, selector):
        validate(selector)
        owners = self.types.get(selector["type"], [])
        if len(owners) != 1:
            raise SelectionError("code-type-missing" if not owners else "code-type-ambiguous")
        owner, context = owners[0]
        if selector["kind"] == "type":
            matches = [owner]
        else:
            body = owner.child_by_field_name("body")
            matches = []
            for node in body.named_children if body is not None else []:
                if node.type != KINDS[selector["kind"]]:
                    continue
                if selector["kind"] == "field":
                    declaration = next((child for child in node.named_children if child.type == "variable_declaration"), None)
                    names = [self.text(child.child_by_field_name("name")) for child in declaration.named_children
                             if child.type == "variable_declarator"] if declaration else []
                else:
                    name = node.child_by_field_name("name")
                    names = [self.text(name)] if name is not None else []
                if selector["member"] not in names:
                    continue
                if "parameters" in selector and self._parameters(node) != [re.sub(r"\s+", "", p) for p in selector["parameters"]]:
                    continue
                matches.append(node)
        if len(matches) != 1:
            raise SelectionError("code-member-missing" if not matches else "code-member-ambiguous")
        node = matches[0]
        return {"sha256": digest(json_bytes([context, self.tokens(node)])),
                "line": node.start_point.row + 1, "end_line": node.end_point.row + 1,
                "symbol": selector, "result": "passed"}


def main():
    """Inspect a captured dependency without emitting source or changing state."""
    import argparse
    from .source import Source
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--revision", required=True, help="Captured Git commit")
    parser.add_argument("--path", required=True, help="C# path within the capture")
    parser.add_argument("--type", required=True, help="Qualified declaring type")
    parser.add_argument("--kind", required=True, choices=["type", *KINDS])
    parser.add_argument("--member")
    parser.add_argument("--parameter", action="append", default=[])
    args = parser.parse_args()
    selector = {"type": args.type, "kind": args.kind}
    if args.member is not None:
        selector["member"] = args.member
    if args.kind in {"method", "constructor"}:
        selector["parameters"] = args.parameter
    elif args.parameter:
        parser.error("Parameters apply only to methods and constructors")
    try:
        validate(selector)
        with Source(args.source, args.revision) as source:
            with source.lines(args.path) as lines:
                selected = Document(b"".join(lines)).select(selector)
            print(json_bytes({"dependency": {"path": args.path, "symbol": selector, "sha256": selected["sha256"]},
                              "source_file_sha256": source.dependencies[args.path]["sha256"],
                              "line": selected["line"], "end_line": selected["end_line"],
                              "parser": runtime(required=True)}).decode("utf-8"), end="")
    except (ContractError, SelectionError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
