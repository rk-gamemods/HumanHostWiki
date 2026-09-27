"""Resolve selected C# enum/boolean fields without exporting source code."""
from collections import defaultdict
import re

from . import components, items_loot
from .schema import Fields
from .items_loot import observation
from .coded_contract import EXPECTED_FIELDS, AMMO_RULE
from ..code_dependencies import runtime, Document, SelectionError

NAME = "coded-values"
VERSION = 1
INPUTS = ()
KINDS = ("configuration",)


def readable(name):
    name = name.lstrip('_')
    if re.fullmatch(r'\d+(?:_\d+)?x\d+mm', name):
        return name.replace('_', '.')
    if name == '45ACP':
        return '.45 ACP'
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', name).replace('_', ' ').strip()


class Definitions:
    def __init__(self):
        self.types, self.enums = {}, {}

    def parse(self, data, assembly, path):
        from tree_sitter import Language, Parser
        import tree_sitter_c_sharp
        tree = Parser(Language(tree_sitter_c_sharp.language())).parse(data)
        self.collect(tree.root_node, assembly, path)

    def collect(self, node, assembly, path, prefix=''):
        for child in node.named_children:
            if child.type == 'file_scoped_namespace_declaration':
                prefix = child.child_by_field_name('name').text.decode()
            elif child.type in {'class_declaration', 'struct_declaration', 'enum_declaration', 'namespace_declaration'}:
                name = child.child_by_field_name('name').text.decode()
                qualified = '.'.join(filter(None, (prefix, name)))
                body = child.child_by_field_name('body')
                if body is None:
                    continue
                if child.type == 'enum_declaration':
                    values, number, error = {}, -1, None
                    for member in body.named_children:
                        if member.type == 'comment':
                            continue
                        if member.type != 'enum_member_declaration' or member.has_error:
                            error = 'unsupported-enum-declaration'
                            break
                        value = member.child_by_field_name('value')
                        try:
                            number = int(re.sub('[uUlL]+$', '', value.text.decode()).replace('_', ''), 0) if value else number + 1
                        except ValueError:
                            error = 'unsupported-enum-expression'
                            break
                        member_name = member.child_by_field_name('name').text.decode()
                        if number in values:
                            error = 'ambiguous-enum-value'
                            break
                        values[number] = member_name
                    self.enums[(assembly, qualified)] = {'values': values, 'error': error,
                        'evidence': {'path': path, 'assembly': assembly, 'type': qualified, 'line': child.start_point.row + 1}}
                else:
                    fields, bases = {}, []
                    for entry in child.named_children:
                        if entry.type == 'base_list':
                            bases = [n.text.decode() for n in entry.named_children]
                    for field in body.named_children:
                        if field.type != 'field_declaration' or field.has_error:
                            continue
                        declaration = next((n for n in field.named_children if n.type == 'variable_declaration'), None)
                        if declaration is None:
                            continue
                        typename = declaration.child_by_field_name('type').text.decode()
                        for variable in declaration.named_children:
                            if variable.type == 'variable_declarator':
                                fields[variable.child_by_field_name('name').text.decode()] = typename
                    self.types[(assembly, qualified)] = {'fields': fields, 'bases': bases,
                        'evidence': {'path': path, 'assembly': assembly, 'type': qualified}}
                    self.collect(body, assembly, path, qualified)
            elif child.type == 'ERROR':
                # Decompiled methods can contain contextual-keyword syntax the
                # grammar rejects. Only intact declaration nodes supply metadata.
                self.collect(child, assembly, path, prefix)

    def resolve(self, collection, assembly, owner, name):
        for prefix in [owner, *['.'.join(owner.split('.')[:i]) for i in range(len(owner.split('.')) - 1, -1, -1)]]:
            key = (assembly, '.'.join(filter(None, (prefix, name))))
            if key in collection:
                return key
        matches = [key for key in collection if key[1] == name or key[1].endswith('.' + name)]
        return matches[0] if len(matches) == 1 else None

    def field(self, assembly, owner, name, visited=frozenset()):
        key = (assembly, owner)
        if key in visited:
            return None
        definition = self.types.get(key, {})
        if name in definition.get('fields', {}):
            return assembly, owner, definition['fields'][name], {**definition['evidence'], 'member': name}
        for base in definition.get('bases', []):
            parent = self.resolve(self.types, assembly, owner, base)
            if parent:
                found = self.field(*parent, name, visited | {key})
                if found:
                    return found

    def selected(self, assembly, owner, fields, prefix=''):
        result = {}
        for name, schema in fields.items():
            found = self.field(assembly, owner, name)
            if not found:
                continue
            declaring_assembly, declaring_type, typename, evidence = found
            pointer = prefix + '/' + name
            while isinstance(schema, list):
                schema = schema[0]
                pointer += '/*'
                typename = typename[:-2] if typename.endswith('[]') else re.sub(r'^(?:List|IList)<(.+)>$', r'\1', typename)
            key = self.resolve(self.enums, declaring_assembly, declaring_type, typename)
            if key or typename == 'bool':
                result[pointer] = {'enum': key, 'evidence': evidence}
            nested = schema.selected if isinstance(schema, Fields) else schema if isinstance(schema, dict) else None
            target = self.resolve(self.types, declaring_assembly, declaring_type, typename) if nested else None
            if target:
                result.update(self.selected(*target, nested, pointer))
        return result


def prepare(source, issues):
    source.coded = {'definitions': Definitions(), 'fields': {}, 'used': {}, 'ammo': defaultdict(set), 'ammo_valid': False}
    contracts = [(s.assembly, s.name, s.fields.selected) for s in components.SPECS if not s.summary_only]
    contracts += [('Item_Info', 'Icon_Info', items_loot.ITEM_FIELDS), ('Use_F', 'Object_Interact', items_loot.SOURCE_FIELDS)]
    paths = [(assembly, f'{assembly}/{assembly}.decompiled.cs') for assembly in sorted({row[0] for row in contracts} | {'UI'})]
    available = [(assembly, path) for assembly, path in paths if path in source.blobs]
    for assembly, path in paths:
        if path not in source.blobs:
            source.dependencies[path] = {'missing': True}
    if not available:
        return
    runtime(required=True)
    definitions = source.coded['definitions']
    for assembly, path in available:
        with source.lines(path) as lines:
            data = b''.join(lines)
        definitions.parse(data, assembly, path)
        if assembly == 'UI':
            source.coded['ammo_valid'] = ammo_rule_valid(data)
    for assembly, name, fields in contracts:
        source.coded['fields'][(assembly, name)] = definitions.selected(assembly, name, fields)
    for assembly, name, pointer in EXPECTED_FIELDS:
        mapping = source.coded['fields'].setdefault((assembly, name), {})
        if pointer not in mapping or mapping[pointer]['enum'] is None:
            mapping[pointer] = {'error': 'Captured enum field declaration is missing, changed or ambiguous.'}
    # The game's Item_Slot_Mgr builds RWI_<caliber>_AmmoBox_Icon and
    # BHC_<caliber>_<material>_Icon addresses. Join exact captured addresses.
    if source.coded['ammo_valid'] and 'Catalog/addressables.jsonl' in source.blobs:
        for row in source.records('Catalog/addressables.jsonl'):
            for address in row.get('keys', []):
                if isinstance(address, str):
                    match = re.fullmatch(r'(?:RWI_(.+)_AmmoBox|BHC_(.+)_[^_]+)_Icon', address)
                    if match:
                        source.coded['ammo'][match[1] or match[2]].update(row.get('targets', []))


def ammo_rule_valid(data):
    try:
        document = Document(data)
        return all(document.select(rule['symbol'])['sha256'] == rule['sha256'] for rule in AMMO_RULE)
    except SelectionError:
        return False


def values(facts, pointer):
    parts = pointer.strip('/').split('/')
    def visit(value, rest, path):
        if not rest:
            yield path, value
        elif rest[0] == '*' and isinstance(value, list):
            for i, child in enumerate(value):
                yield from visit(child, rest[1:], path + '/' + str(i))
        elif isinstance(value, dict) and rest[0] in value:
            yield from visit(value[rest[0]], rest[1:], path + '/' + rest[0])
    yield from visit(facts, parts, '')


def enrich(source, row, issues):
    if not hasattr(source, 'coded'):
        return
    component = row.get('component')
    key = (component['assembly'], component['class']) if component else {
        'item': ('Item_Info', 'Icon_Info'), 'loot-source': ('Use_F', 'Object_Interact')}.get(row['kind'])
    for pointer, definition in source.coded['fields'].get(key, {}).items():
        base = row.get('source_field_base', '')
        if base and not pointer.startswith(base + '/'):
            continue
        for field, value in values(row['facts'], pointer[len(base):]):
            if 'error' in definition:
                issues.add('unresolved-coded-value', row['topic'], '/'.join(key) + field,
                           definition['error'], row['source_id'])
                row.setdefault('fact_labels', {})[field] = f'Unresolved code ({value})'
                continue
            enum = definition['enum']
            if enum is None:
                if value in (0, 1):
                    row.setdefault('fact_labels', {})[field] = 'Yes' if value else 'No'
                    if definition['evidence'] not in row['evidence']:
                        row['evidence'].append(definition['evidence'])
                else:
                    issues.add('unresolved-coded-value', row['topic'], '/'.join(key) + field,
                               'Serialized boolean is neither zero nor one.', row['source_id'])
                    row.setdefault('fact_labels', {})[field] = f'Unresolved code ({value})'
                continue
            declaration = source.coded['definitions'].enums[enum]
            name = declaration['values'].get(value) if type(value) is int else None
            if declaration['error'] or name is None:
                issues.add('unresolved-coded-value', row.get('topic', 'technical-reference'), '/'.join(key) + field,
                           declaration['error'] or 'Value is absent from the captured enum declaration.', row['source_id'])
                row.setdefault('fact_labels', {})[field] = f'Unresolved code ({value})'
                continue
            identity = 'code-enum/' + '/'.join(enum) + '/' + name
            label = readable(name)
            row.setdefault('fact_labels', {})[field] = label
            row['relationships'].append({'predicate': 'coded-value', 'source_field': field, 'target_source_id': identity})
            for evidence in [definition['evidence'], declaration['evidence']]:
                if evidence not in row['evidence']:
                    row['evidence'].append(evidence)
            source.coded['used'][identity] = (enum, name, value, label, declaration['evidence'])


def extract(source, issues):
    for identity, (enum, name, value, label, evidence) in sorted(source.coded['used'].items()):
        category = readable(enum[1].rsplit('.', 1)[-1])
        row = observation('configuration', identity, category + ': ' + label,
                          {'category': category, 'value': label}, evidence['path'], [])
        row['evidence'] = [{**evidence, 'member': name, 'numeric_value': value}]
        row['fact_scope'] = 'source-enumeration'
        row['name_status'] = 'source-label'
        row['notes'] = 'Named value from the captured source declaration. Numeric codes are preserved as technical provenance.'
        if enum == ('Hand_Tools', 'Weapon_Range.AmmoType'):
            tokens = {label.replace(' ', ''), label.replace(' ', '').removesuffix('mm').removesuffix('ACP')}
            tokens |= {token.lstrip('.') for token in tokens}
            if label == '.45 ACP':
                tokens.add('D45')
            targets = set().union(*(source.coded['ammo'].get(token, set()) for token in tokens))
            if value < 7 and not targets:
                issues.add('ammo-item-relationship', 'combat', 'Weapon_Range/AmmoType',
                           'Captured ammunition address rule changed or its item targets are missing.', identity)
            if targets:
                row['relationships'].append({'predicate': 'ammunition-item', 'source_field': '/ammo-address', 'target_source_ids': sorted(targets)})
                row['evidence'].append({'path': 'Catalog/addressables.jsonl', 'fields': ['keys', 'targets']})
                row['evidence'].append({'path': 'UI/UI.decompiled.cs', 'assembly': 'UI', 'type': 'Item_Slot_Mgr', 'member': 'Build_Ammo_Address'})
        yield row
