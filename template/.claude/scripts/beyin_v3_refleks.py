"""Reflexes: scoped, evidence-weighted behaviours that load only when their context is active.

event --(repetition + time)--> reflex --(same direction across changing conditions)--> core

A reflex is a vault Markdown file under `<companion>/Refleksler/<id>.md`. Its weight is the sum
of its evidence, each item halving every HALF_LIFE days; it is never stored, always computed.
A reflex whose weight falls below FADE_WEIGHT and that has not fired for FADE_DAYS is faded:
not loaded, still searchable, never deleted. Core reflexes never fade.

Scopes become active from the prompt (project dictionary), from the files a session edits and
from the session's own recent turns. Each reflex is said once per session, again only when its
file changes or the context is compacted. Usage and session state are machine-local runtime
files; the vault holds only what the user could also edit by hand. No model, no network.
"""
import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from beyin_v3_companion import directory

FOLDER = 'Refleksler'
DICTIONARY = '_sozluk.md'
HALF_LIFE = 60.0          # days
FADE_WEIGHT = 0.25
FADE_DAYS = 90
SESSION_TURNS = 6         # an active scope stays active this many prompts without a new mention
OPENING_CHARS = 1500
TURN_CHARS = 3000
CORE_MIN_EVIDENCE = 3
CORE_MIN_SPAN = 30        # days between first and last positive evidence
CORE_QUIET_CONTRA = 60    # no contrary evidence in this many days
SIMILAR = 0.6             # token containment that counts as "probably the same reflex"
STRENGTH = {'kural': 1.0, 'duzeltme': 1.0, 'karar': 0.7, 'tekrar': 0.5, 'gozlem': 0.3, 'ters': -1.0}
TYPES = tuple(STRENGTH)
PROJECT_PARENTS = ('projeler', 'Projeler', 'projects', 'Projects', '🏰 300-Projects')
FRONT = re.compile(r'\A---\n(.*?)\n---\n', re.S)
EVIDENCE = re.compile(r'^- (\d{4}-\d{2}-\d{2}) · ([^·]+?) · (.+)$')
STOP = frozenset('ve veya ile ama bir bu şu o da de mi için gibi daha en çok az her hiç ne nasıl '
                 'olarak olan yap yapma etme the a an of to in on for and or not'.split())


# ---------- text ----------

def fold(text):
    text = str(text).replace('I', 'ı').replace('İ', 'i').lower()
    return text.translate(str.maketrans('ığüşöçâîû', 'igusocaiu'))


def words(text):
    return [w for w in re.split(r"[^0-9a-z]+", fold(text)) if w]


def roots(text):
    """Coarse stems for similarity: Turkish suffixes vary, the first five letters rarely do."""
    return {w[:5] for w in words(text) if len(w) > 2 and w not in STOP}


def similarity(a, b):
    ra, rb = roots(a), roots(b)
    if not ra or not rb:
        return 0.0
    return len(ra & rb) / min(len(ra), len(rb))


def slug(text):
    s = re.sub(r'[^a-z0-9]+', '-', fold(text)).strip('-')
    return s[:48].rstrip('-') or 'refleks'


# ---------- files ----------

def folder(vault):
    target = directory(vault)
    if target is None:
        raise ValueError('Birden çok companion klasörü var; hangisinin kullanılacağı belirsiz')
    return target / FOLDER


def _atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.refleks-', dir=path.parent)
    with os.fdopen(fd, 'w', encoding='utf-8') as out:
        out.write(text)
    os.replace(tmp, path)


def _list(value):
    value = value.strip()
    if value.startswith('[') and value.endswith(']'):
        value = value[1:-1]
    return [item.strip().strip('"\'') for item in value.split(',') if item.strip().strip('"\'')]


def parse(text, path=None):
    match = FRONT.match(text)
    meta = {}
    if match:
        for line in match.group(1).splitlines():
            if ':' in line:
                key, value = line.split(':', 1)
                meta[key.strip()] = value.strip()
        body = text[match.end():]
    else:
        body = text
    statement, _, tail = body.partition('\n## Kanıt')
    evidence = []
    for line in tail.splitlines():
        m = EVIDENCE.match(line.strip())
        if m:
            kind = fold(m.group(2).strip()).replace(' ', '')
            if kind in STRENGTH:
                evidence.append({'date': m.group(1), 'type': kind, 'text': m.group(3).strip()})
    rid = meta.get('id') or (Path(path).stem if path else '')
    return {'id': rid, 'durum': meta.get('durum', 'aktif'), 'kapsam': _list(meta.get('kapsam', '')),
            'tetik': _list(meta.get('tetik', '')), 'metin': ' '.join(statement.split()),
            'kanit': evidence, 'path': path,
            'sha': hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}


TYPE_LABEL = {'duzeltme': 'düzeltme', 'gozlem': 'gözlem'}


def render(reflex):
    front = ['---', f"id: {reflex['id']}", f"durum: {reflex['durum']}",
             f"kapsam: [{', '.join(reflex['kapsam'])}]"]
    if reflex['tetik']:
        front.append(f"tetik: [{', '.join(reflex['tetik'])}]")
    # Reflexes reach the model only through their trigger, never through general retrieval.
    front += ['kind: reflex', 'visibility: private', '---']
    lines = [f"- {e['date']} · {TYPE_LABEL.get(e['type'], e['type'])} · {e['text']}" for e in reflex['kanit']]
    return '\n'.join(front) + '\n' + reflex['metin'] + '\n\n## Kanıt\n' + '\n'.join(lines) + '\n'


def load(vault):
    base = folder(vault)
    out = []
    if base.is_dir():
        for path in sorted(base.glob('*.md')):
            if path.name.startswith('_') or path.is_symlink():
                continue
            reflex = parse(path.read_text(encoding='utf-8'), path)
            if reflex['metin']:
                out.append(reflex)
    return out


# ---------- project dictionary ----------

def project_folders(vault):
    vault = Path(vault).resolve()
    found = {}
    for parent in PROJECT_PARENTS:
        base = vault / parent
        if base.is_dir() and not base.is_symlink():
            for child in sorted(base.iterdir()):
                if child.is_dir() and not child.name.startswith(('.', '_')):
                    found.setdefault(child.name, base.name + '/' + child.name)
    return found


def dictionary(vault):
    """{project key: [aliases]}. The file wins; project folders fill in what it does not name."""
    result = {}
    path = folder(vault) / DICTIONARY
    if path.is_file():
        for line in path.read_text(encoding='utf-8').splitlines():
            m = re.match(r'^\s*-\s*([^:]+):\s*(.*)$', line)
            if m:
                key = m.group(1).strip()
                result[key] = [a.strip() for a in m.group(2).split(',') if a.strip()]
    for name in project_folders(vault):
        result.setdefault(name, [])
    return {key: sorted({key, key.replace('-', ' '), *aliases}, key=len, reverse=True) for key, aliases in result.items()}


def write_dictionary(vault, entries):
    lines = ['---', 'kind: reflex-dictionary', 'visibility: private', '---',
             '# Proje sözlüğü',
             '',
             'Refleksler kapsamı etkin olduğunda yüklenir. Bir proje, adı ya da aşağıdaki takma adlardan',
             'biri istemde geçince veya oturumda klasörüne dokunulunca etkinleşir. Takma ad ekleyebilirsin.',
             '']
    lines += [f"- {key}: {', '.join(aliases)}" for key, aliases in sorted(entries.items())]
    _atomic(folder(vault) / DICTIONARY, '\n'.join(lines) + '\n')


def _alias_hit(alias, tokens, folded):
    alias_words = words(alias)
    if not alias_words:
        return False
    if len(alias_words) > 1:
        # The last word may carry a Turkish suffix too ("dış ses" -> "dış sesi").
        tail = r'[0-9a-z]*' if len(alias_words[-1]) >= 3 else r'(?![0-9a-z])'
        return re.search(r'(?<![0-9a-z])' + r'[^0-9a-z]+'.join(map(re.escape, alias_words)) + tail, folded) is not None
    word = alias_words[0]
    # Short names must match exactly; longer ones may carry a Turkish suffix ("ermay'ın" -> "ermay", "erpde").
    return any(t == word or (len(word) >= 4 and t.startswith(word)) for t in tokens)


def scopes_in(text, entries):
    folded = fold(text)
    tokens = set(re.split(r'[^0-9a-z]+', folded))
    return {key for key, aliases in entries.items() if any(_alias_hit(a, tokens, folded) for a in aliases)}


def scopes_in_path(vault, path, entries):
    try:
        target = Path(path).resolve()
        vault = Path(vault).resolve()
    except (OSError, TypeError, ValueError):
        return set()
    if target.is_relative_to(vault):
        parts = target.relative_to(vault).parts
        if len(parts) > 1 and parts[0] in PROJECT_PARENTS and parts[1] in entries:
            return {parts[1]}
        return scopes_in(' '.join(parts[:-1]), entries)
    return scopes_in(' '.join(target.parts[-6:-1]), entries)


# ---------- weight ----------

def _day(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def weight(reflex, today=None, last_fired=None):
    today = today or date.today()
    fired = _day(last_fired) if last_fired else None
    total = 0.0
    for item in reflex['kanit']:
        when = _day(item['date'])
        if when is None:
            continue
        # Firing without being corrected keeps the evidence fresh: a used reflex does not fade.
        fresh = max(when, fired) if fired and STRENGTH[item['type']] > 0 else when
        age = max(0, (today - fresh).days)
        total += STRENGTH[item['type']] * 0.5 ** (age / HALF_LIFE)
    return round(total, 3)


def state_of(reflex, today=None, last_fired=None):
    if reflex['durum'] == 'cekirdek':
        return 'cekirdek'
    today = today or date.today()
    w = weight(reflex, today, last_fired)
    dates = [d for d in (_day(e['date']) for e in reflex['kanit']) if d]
    latest = max([d for d in dates] + ([_day(last_fired)] if last_fired and _day(last_fired) else []), default=None)
    if w < FADE_WEIGHT and (latest is None or (today - latest).days >= FADE_DAYS):
        return 'sonmus'
    return 'aktif'


def core_candidate(reflex, today=None):
    """Same direction, enough times, across enough time and contexts, and no recent contradiction."""
    if reflex['durum'] == 'cekirdek':
        return False
    today = today or date.today()
    positive = [e for e in reflex['kanit'] if STRENGTH[e['type']] > 0 and _day(e['date'])]
    contrary = [e for e in reflex['kanit'] if e['type'] == 'ters' and _day(e['date'])]
    if len(positive) < CORE_MIN_EVIDENCE:
        return False
    days = sorted(_day(e['date']) for e in positive)
    if (days[-1] - days[0]).days < CORE_MIN_SPAN or len(set(days)) < 2:
        return False
    return not any((today - _day(e['date'])).days < CORE_QUIET_CONTRA for e in contrary)


# ---------- machine-local state ----------

def _read_json(path, default):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        return value if isinstance(value, type(default)) else default
    except (OSError, ValueError):
        return default


def _write_json(path, value):
    _atomic(Path(path), json.dumps(value, ensure_ascii=False, sort_keys=True))


def usage(state):
    return _read_json(Path(state) / 'refleks-kullanim.json', {})


def _session_path(state, session):
    digest = hashlib.sha256(str(session or 'unknown').encode('utf-8')).hexdigest()[:24]
    return Path(state) / 'refleks-oturum' / (digest + '.json')


def _prune_sessions(state, keep_days=7):
    base = Path(state) / 'refleks-oturum'
    if not base.is_dir():
        return
    limit = datetime.now().timestamp() - keep_days * 86400
    for path in base.glob('*.json'):
        try:
            if path.stat().st_mtime < limit:
                path.unlink()
        except OSError:
            pass


# ---------- triggering ----------

def _line(reflex, w, faded=False):
    scope = ', '.join(reflex['kapsam']) or 'genel'
    mark = 'çekirdek' if reflex['durum'] == 'cekirdek' else ('eski, doğrula' if faded else f'ağırlık {w:.1f}')
    return f"- [{reflex['id']} · {scope} · {mark}] {reflex['metin']}"


def _fit(lines, budget):
    out, used = [], 0
    for line in lines:
        if used + len(line) + 1 > budget:
            break
        out.append(line)
        used += len(line) + 1
    return out


def trigger(vault, state, session, event, prompt='', paths=(), source=None, today=None):
    """The reflex lines this event adds to the hook context, or ''. Never raises past the hook."""
    today = today or date.today()
    reflexes = load(vault)
    record_path = _session_path(state, session)
    record = _read_json(record_path, {})
    if event == 'SessionStart' or source in ('compact', 'clear'):
        record = {}
        _prune_sessions(state)
    projects = dict(record.get('projects', {}))
    delivered = dict(record.get('delivered', {}))
    if not reflexes and not projects:
        return ''
    entries = dictionary(vault)
    if event == 'UserPromptSubmit':
        projects = {k: v - 1 for k, v in projects.items() if v - 1 > 0}
        for key in scopes_in(prompt, entries):
            projects[key] = SESSION_TURNS
    for path in paths:
        for key in scopes_in_path(vault, path, entries):
            projects[key] = SESSION_TURNS
    used = usage(state)
    folded = fold(prompt)
    fired, faded, opening_core = [], set(), []
    for reflex in reflexes:
        scoped = set(reflex['kapsam'])
        in_scope = bool(scoped & set(projects))
        if state_of(reflex, today, used.get(reflex['id'])) == 'sonmus':
            # Forgotten, not lost: returning to its project brings it back, marked as old.
            if not in_scope:
                continue
            faded.add(reflex['id'])
        hit = (not scoped) or in_scope
        if not hit and reflex['tetik'] and prompt:
            hit = scopes_in(folded, {'t': reflex['tetik']}) != set()
        if hit and delivered.get(reflex['id']) != reflex['sha']:
            fired.append(reflex)
    fired.sort(key=lambda r: (r['durum'] != 'cekirdek', r['id'] in faded, -weight(r, today, used.get(r['id']))))
    budget = OPENING_CHARS if event == 'SessionStart' else TURN_CHARS
    lines = _fit([_line(r, weight(r, today, used.get(r['id'])), r['id'] in faded) for r in fired], budget)
    shown = fired[:len(lines)]
    if len(shown) < len(fired):
        lines.append(f'- (+{len(fired) - len(shown)} refleks daha sonraki turlarda; tamamı: `beyin.py refleks liste`)')
    if event == 'SessionStart':
        opening_core = [r for r in reflexes if core_candidate(r, today)][:3]
    for reflex in shown:
        delivered[reflex['id']] = reflex['sha']
        used[reflex['id']] = today.isoformat()
    if shown:
        _write_json(Path(state) / 'refleks-kullanim.json', used)
    _write_json(record_path, {'projects': projects, 'delivered': delivered})
    text = ''
    if lines:
        active = ', '.join(sorted(projects)) or 'genel'
        text += (f'Refleksler (etkin kapsam: {active}; kullanıcının kanıtla ağırlıklanmış davranışları, '
                 'çelişirse en olasıyı öner ve alternatifi söyle):\n' + '\n'.join(lines) + '\n')
    if opening_core:
        names = ', '.join(r['id'] for r in opening_core)
        text += (f'Refleks çekirdeğe aday (zaman ve tekrarla yönü değişmedi): {names}. '
                 'Uygunsa `beyin.py refleks yukselt <id>` çalıştır ve kullanıcıya bildir.\n')
    return text


# ---------- commands ----------

def find_similar(vault, text, kapsam=None, limit=3):
    scored = []
    for reflex in load(vault):
        if kapsam is not None and set(reflex['kapsam']) != set(kapsam):
            continue
        score = similarity(text, reflex['metin'])
        if score >= SIMILAR:
            scored.append((score, reflex))
    scored.sort(key=lambda item: -item[0])
    return scored[:limit]


def _check_type(kind):
    kind = fold(kind).replace(' ', '')
    if kind not in STRENGTH:
        raise ValueError('tur şunlardan biri olmalı: ' + ', '.join(TYPES))
    return kind


def _check_scopes(vault, kapsam):
    known = dictionary(vault)
    clean = []
    for item in kapsam or []:
        item = item.strip()
        if not item or fold(item) in ('genel', 'global'):
            continue
        if item not in known:
            raise ValueError(f"bilinmeyen kapsam: {item}. Bilinenler: {', '.join(sorted(known)) or '(yok)'}; "
                             f"sözlüğe eklemek için {FOLDER}/{DICTIONARY}")
        clean.append(item)
    return sorted(set(clean))


def ekle(vault, metin, kapsam=(), tur='duzeltme', refleks_id=None, tetik=(), tarih=None, yeni=False):
    """Add evidence to a reflex, or open a new one. Returns {'status', 'id', 'similar'}."""
    metin = ' '.join(str(metin).split())
    if not metin:
        raise ValueError('metin boş')
    kind = _check_type(tur)
    when = (_day(tarih) or date.today()).isoformat() if tarih else date.today().isoformat()
    scopes = _check_scopes(vault, kapsam)
    if refleks_id:
        path = folder(vault) / (refleks_id + '.md')
        if not path.is_file():
            raise ValueError(f'{refleks_id} adlı refleks yok')
        reflex = parse(path.read_text(encoding='utf-8'), path)
        reflex['kanit'].append({'date': when, 'type': kind, 'text': metin})
        _atomic(path, render(reflex))
        return {'status': 'kanit_eklendi', 'id': reflex['id'], 'similar': []}
    similar = find_similar(vault, metin, scopes)
    if similar and not yeni:
        return {'status': 'benzer_var', 'id': None,
                'similar': [{'id': r['id'], 'benzerlik': round(s, 2), 'metin': r['metin']} for s, r in similar]}
    base = slug(((scopes[0] + ' ') if scopes else '') + metin)
    rid, n = base, 2
    while (folder(vault) / (rid + '.md')).exists():
        rid, n = f'{base}-{n}', n + 1
    reflex = {'id': rid, 'durum': 'aktif', 'kapsam': scopes, 'tetik': [t for t in tetik if t.strip()],
              'metin': metin, 'kanit': [{'date': when, 'type': kind, 'text': metin}]}
    _atomic(folder(vault) / (rid + '.md'), render(reflex))
    return {'status': 'olusturuldu', 'id': rid, 'similar': []}


def set_core(vault, refleks_id, core=True):
    path = folder(vault) / (refleks_id + '.md')
    if not path.is_file():
        raise ValueError(f'{refleks_id} adlı refleks yok')
    reflex = parse(path.read_text(encoding='utf-8'), path)
    reflex['durum'] = 'cekirdek' if core else 'aktif'
    _atomic(path, render(reflex))
    return reflex['durum']


def report(vault, state, today=None):
    today = today or date.today()
    used = usage(state) if state else {}
    rows = []
    for reflex in load(vault):
        last = used.get(reflex['id'])
        rows.append({'id': reflex['id'], 'durum': state_of(reflex, today, last),
                     'aday': core_candidate(reflex, today), 'kapsam': reflex['kapsam'] or ['genel'],
                     'agirlik': weight(reflex, today, last), 'kanit': len(reflex['kanit']),
                     'son_tetik': last, 'metin': reflex['metin']})
    rows.sort(key=lambda r: (r['durum'] == 'sonmus', -r['agirlik']))
    return rows


# ---------- migration from Kurallar.md ----------

RULE = re.compile(r'^- \*\*(\d{4}-\d{2}-\d{2})(?: · ([^*]*?))?:?\*\*:?\s*(.*)$')


def rules(text):
    """(start, end, date, label, body) for each top-level bullet rule, with its indented lines."""
    lines = text.splitlines()
    found, i = [], 0
    while i < len(lines):
        m = RULE.match(lines[i])
        if not m:
            i += 1
            continue
        j = i + 1
        while j < len(lines) and lines[j].startswith(('  ', '\t')) and lines[j].strip():
            j += 1
        body = ' '.join([m.group(3)] + [l.strip() for l in lines[i + 1:j]])
        found.append((i, j, m.group(1), (m.group(2) or '').strip(), ' '.join(body.split())))
        i = j
    return found


def plan_migration(vault):
    """Which Kurallar.md rules belong to exactly one project. Rules naming no project, or several,
    stay where they are: moving a rule out of the always-loaded file must never hide it."""
    target = directory(vault)
    if target is None:
        raise ValueError('Birden çok companion klasörü var')
    path = target / 'Kurallar.md'
    if not path.is_file():
        return {'source': None, 'move': [], 'keep': 0}
    text = path.read_text(encoding='utf-8')
    entries = dictionary(vault)
    move, keep = [], 0
    for start, end, when, label, body in rules(text):
        # A labelled rule is scoped by its label alone ("2026-10-04 · ErmayWeb hedef kitle"): a general
        # rule often names a project only as its example. The body decides only for unlabelled rules.
        scopes = scopes_in(label, entries) if label else scopes_in(body, entries)
        if len(scopes) == 1:
            move.append({'start': start, 'end': end, 'date': when, 'label': label, 'text': body,
                         'kapsam': sorted(scopes)})
        else:
            keep += 1
    return {'source': path, 'move': move, 'keep': keep}


def migrate(vault, apply=False, today=None):
    plan = plan_migration(vault)
    summary = {'tasinacak': len(plan['move']), 'kalan': plan['keep'],
               'kapsamlar': {}, 'uygulandi': False}
    for item in plan['move']:
        key = item['kapsam'][0]
        summary['kapsamlar'][key] = summary['kapsamlar'].get(key, 0) + 1
    if not apply or not plan['move']:
        summary['ornek'] = [{'kapsam': i['kapsam'][0], 'kural': (i['label'] + ': ' if i['label'] else '') + i['text'][:90]}
                            for i in plan['move'][:8]]
        return summary
    source = plan['source']
    original = source.read_text(encoding='utf-8')
    today = today or date.today()
    archive = source.parent / 'Arşiv' / f'Kurallar-{today.isoformat()}-goc-oncesi.md'
    if not archive.exists():
        _atomic(archive, '---\nvisibility: private\n---\n' + original)
    created = []
    for item in plan['move']:
        label = re.sub(r'\s*\([^)]*\)\s*$', '', item['label']).strip()
        statement = f"{label}: {item['text']}" if label else item['text']
        reflex_id = ekle(vault, statement, item['kapsam'], 'kural', tarih=item['date'], yeni=True)['id']
        created.append(reflex_id)
    lines = original.splitlines()
    for item in sorted(plan['move'], key=lambda i: -i['start']):
        del lines[item['start']:item['end']]
    note = (f"\n> {today.isoformat()}: tek projeye ait {len(created)} kural `{FOLDER}/` altına refleks olarak taşındı; "
            f"yalnız o proje etkinken yüklenir. Göç öncesi tam metin: `Arşiv/{archive.name}`.\n")
    _atomic(source, '\n'.join(lines).rstrip('\n') + '\n' + note)
    summary.update({'uygulandi': True, 'arsiv': archive.relative_to(Path(vault).resolve()).as_posix(),
                    'olusturulan': created})
    return summary
