"""Audit every published code label and edge using source text and raw values.

Deliberately independent of the extraction adapter and its tree-sitter walker.
This checks named enum constants, not gameplay behavior.
"""
from collections import Counter
import re
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wikibuild import bounded

# An enum lookup reads one committed decompiled source file.
GIT_TIMEOUT = 60


def check(source, commit, rows):
    texts, definitions = {}, {}
    def text(path):
        if path not in texts:
            result = bounded.run(['git', '-C', str(source), 'show', f'{commit}:{path}'], timeout=GIT_TIMEOUT)
            result.check_returncode()
            texts[path] = result.stdout.decode('utf-8')
        return texts[path]
    for row in rows:
        if row.get('fact_scope') != 'source-enumeration':
            continue
        evidence = row['evidence'][0]
        declared = '\n'.join(text(evidence['path']).splitlines()[evidence['line'] - 1:])
        match = re.search(r'\benum\s+' + re.escape(evidence['type'].split('.')[-1]) + r'\s*(?::[^{}]+)?\{([^{}]+)\}', declared)
        if not match or match.start() > 200:
            raise ValueError('Missing source enum at recorded locator: ' + row['source_id'])
        members, number = {}, -1
        body = re.sub(r'/\*.*?\*/|//[^\n]*', '', match[1], flags=re.S)
        for member in body.split(','):
            if not member.strip():
                continue
            parts = member.strip().split('=')
            number = int(re.sub('[uUlL]+$', '', parts[1].strip()).replace('_', ''), 0) if len(parts) == 2 else number + 1
            if number in members:
                raise ValueError('Ambiguous source enum')
            members[number] = parts[0].strip()
        if members.get(evidence['numeric_value']) != evidence['member']:
            raise ValueError('Source enum numeric mapping differs: ' + row['source_id'])
        definitions[row['source_id']] = row
    counts, fields = Counter(), set()
    for row in rows:
        for pointer, label in row.get('fact_labels', {}).items():
            value = row['facts']
            for part in pointer.strip('/').split('/'):
                value = value[int(part)] if isinstance(value, list) else value[part]
            links = [link for link in row['relationships'] if link['predicate'] == 'coded-value' and link['source_field'] == pointer]
            if links:
                if len(links) != 1:
                    raise ValueError('Ambiguous code edge: ' + row['source_id'])
                target = definitions[links[0]['target_source_id']]
                if value != target['evidence'][0]['numeric_value'] or label != target['facts']['value']:
                    raise ValueError('Fact label/edge does not match its source numeric value')
                counts['enum_occurrences'] += 1
                component = row.get('component') or {'class': row['kind']}
                fields.add((component['class'], pointer))
            elif type(value) is int and value in (0, 1) and label == ('Yes' if value else 'No'):
                counts['boolean_occurrences'] += 1
            else:
                raise ValueError('Unresolved or unsupported code label: ' + row['source_id'] + pointer)
    # Validate ammo targets against exact captured Addressables, not display-name guesses.
    ammo = [row for row in definitions.values() if row['evidence'][0]['type'] == 'Weapon_Range.AmmoType']
    if ammo:
        import json
        addresses = {key: set(record.get('targets', [])) for line in text('Catalog/addressables.jsonl').splitlines()
                     for record in [json.loads(line)] for key in record.get('keys', []) if isinstance(key, str)}
        for row in ammo:
            links = [link for link in row['relationships'] if link['predicate'] == 'ammunition-item']
            actual = {target for link in links for target in link['target_source_ids']}
            name = row['evidence'][0]['member'].lstrip('_').replace('_', '.')
            if name == '45ACP':
                tokens = {'.45ACP', '45ACP', '.45', '45', 'D45'}
            else:
                tokens = {name, name.removesuffix('mm')}
            expected = {target for key, targets in addresses.items() for token in tokens
                        if key == f'RWI_{token}_AmmoBox_Icon' or re.fullmatch(r'BHC_' + re.escape(token) + r'_[^_]+_Icon', key)
                        for target in targets}
            if actual != expected or (row['evidence'][0]['numeric_value'] < 7 and not actual):
                raise ValueError('Ammunition item edges differ: ' + row['source_id'])
            counts['ammunition_targets'] += len(actual)
    return {**counts, 'enum_value_entries': len(definitions), 'enum_fields': len(fields), 'status': 'passed'}
