#!/usr/bin/env python3
"""Measure reflex triggering: does each labelled prompt activate exactly its project scopes?

The fixture holds a project dictionary and prompts labelled with the scopes they should activate
(an empty list means "no project": a meta question must load no project reflex). With --vault the
same prompts are scored against that vault's own dictionary, and the opening cost of Kurallar.md
before and after `refleks gocet` is reported. Nothing is written; results stay on this machine.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'template/.claude/scripts'))
import beyin_v3_refleks as refleks  # noqa: E402

DEFAULT = ROOT / 'tests/fixtures/v5/reflex_triggers.json'


def score(entries, cases):
    tp = fp = fn = exact = 0
    misses = []
    for case in cases:
        want, got = set(case['scopes']), refleks.scopes_in(case['prompt'], entries)
        tp += len(want & got)
        fp += len(got - want)
        fn += len(want - got)
        exact += want == got
        if want != got:
            misses.append({'prompt': case['prompt'], 'beklenen': sorted(want), 'bulunan': sorted(got)})
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {'vaka': len(cases), 'tam_isabet': exact, 'kesinlik': round(precision, 3),
            'duyarlilik': round(recall, 3), 'kacanlar': misses}


def opening_cost(vault):
    target = refleks.directory(vault)
    rules = target / 'Kurallar.md' if target else None
    if not rules or not rules.is_file():
        return None
    text = rules.read_text(encoding='utf-8')
    plan = refleks.plan_migration(vault)
    lines = text.splitlines()
    moved = sum(len('\n'.join(lines[i['start']:i['end']])) + 1 for i in plan['move'])
    return {'kurallar_karakter': len(text), 'gocten_sonra_karakter': len(text) - moved,
            'tasinacak_kural': len(plan['move']), 'kalan_kural': plan['keep']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, default=DEFAULT)
    parser.add_argument('--vault', type=Path, help="Score against this vault's dictionary and report opening cost")
    args = parser.parse_args()
    data = json.loads(args.fixture.read_text(encoding='utf-8'))
    if args.vault:
        entries = refleks.dictionary(args.vault)
        result = {'sozluk': 'vault', 'opening': opening_cost(args.vault)}
        cases = [c for c in data['cases'] if set(c['scopes']) <= set(entries)] if not data.get('vault_cases') else data['vault_cases']
        result['tetikleme'] = score(entries, cases)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            (vault / '🔮 850-Companion' / 'Refleksler').mkdir(parents=True)
            (vault / '🔮 850-Companion' / 'Refleksler' / '_sozluk.md').write_text(
                '\n'.join(f"- {k}: {', '.join(v)}" for k, v in data['dictionary'].items()) + '\n', encoding='utf-8')
            result = {'sozluk': 'fixture', 'tetikleme': score(refleks.dictionary(vault), data['cases'])}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['tetikleme']['kesinlik'] >= data.get('min_precision', 0) else 1


if __name__ == '__main__':
    raise SystemExit(main())
