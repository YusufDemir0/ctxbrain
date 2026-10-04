"""Per-turn capture of the user's own decision and rule sentences. Local, no model, no approval.

Runs on every user prompt, before the reply, so leaving a session mid-conversation loses nothing
already said. Only sentences that state a decision or a standing rule are written; everything
else in the prompt stays as unpersisted as before. Secrets are always redacted here, whatever the
opt-in write filter says, because this path writes without the user choosing each line.
"""
from datetime import datetime
import json
from pathlib import Path
import re
import unicodedata

DIRECTORY = 'knowledge/yakalanan'
MAX_PROMPT = 4000      # a longer prompt is a paste or a log, not a statement
MAX_SENTENCE = 300
MAX_PER_PROMPT = 3
MIN_WORDS = 3

# Matched against folded text: casefolded, accents stripped, dotless i as i.
RULE = re.compile(r"\b(bundan (sonra|boyle)|her zaman|hicbir zaman|asla|unutma|aklinda (tut|bulunsun)"
                  r"|from now on|always|never|remember that|do not ever|don'?t ever)\b")
DECISION = re.compile(r"\b(karar (verdi[km]|verelim|aldi[km])|kararim(iz)?\b|(sec|tercih et)(tik|tim|elim)"
                      r"|kullanalim|kullanacagiz|olmali|olmamali|daha iyi olur|yerine \S+ (kullan|yap)"
                      r"|we decided|i decided|let'?s (use|go with)|we('ll| will) use|i prefer|we prefer)")
# People often type questions without a question mark; question words count as one.
QUESTION = re.compile(r"\b(mi|mu|misin|musun|miyiz|muyuz|nasil|niye|nicin|hangi|hangisi|nerede|ne zaman"
                      r"|why|how|what|which|should (we|i))\b")
FENCE = re.compile(r"```.*?(```|$)", re.S)


def enabled(state):
    """Machine-local, default on; outside .beyin-preferences.json so a rollback never sees a new key.
    An unreadable setting turns capture off: this path writes user text without per-line consent."""
    path = Path(state) / 'capture.json'
    if not path.exists():
        return True
    try:
        data = json.loads(path.read_text(encoding='utf-8')) if not path.is_symlink() else None
    except (ValueError, OSError):
        return False
    return isinstance(data, dict) and data.get('enabled') is True


def save(state, value):
    from beyin_v3_sync import atomic
    atomic(Path(state) / 'capture.json', json.dumps({'schema': 1, 'enabled': bool(value)}))
    return bool(value)


def fold(text):
    text = unicodedata.normalize('NFKD', text.casefold())
    return ''.join(c for c in text if not unicodedata.combining(c)).replace('ı', 'i')


def statements(prompt):
    """(kind, sentence) pairs worth keeping from one prompt, in prompt order."""
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT:
        return []
    text = FENCE.sub(' ', prompt)
    lines = [line for line in text.splitlines() if not line.lstrip().startswith(('>', '<', '$', '#'))]
    found = []
    for sentence in re.split(r'(?<=[.!…])\s+|\n+', '\n'.join(lines)):
        sentence = ' '.join(sentence.split())
        if len(sentence.split()) < MIN_WORDS or sentence.endswith('?'):
            continue
        folded = fold(sentence)
        if QUESTION.search(folded):
            continue
        kind = 'kural' if RULE.search(folded) else 'karar' if DECISION.search(folded) else None
        if kind:
            if len(sentence) > MAX_SENTENCE:
                sentence = sentence[:MAX_SENTENCE - 1].rstrip() + '…'
            found.append((kind, sentence))
            if len(found) == MAX_PER_PROMPT:
                break
    return found


def capture(vault, state, prompt, session_id, now=None):
    """Append new statements to today's capture note; returns how many were written."""
    found = statements(prompt)
    return _append(vault, state, found, session_id, now) if found else 0


def _directory(vault):
    directory = Path(vault) / DIRECTORY
    for part in (Path(vault) / 'knowledge', directory):
        if part.is_symlink():
            raise ValueError('capture directory must not be a symlink')
    return directory


def _append(vault, state, found, session_id, now=None):
    from beyin_v3_secrets import redact, record
    now = now or datetime.now().astimezone()
    directory = _directory(vault)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (now.strftime('%Y-%m-%d') + '.md')
    if path.is_symlink():
        raise ValueError('capture note must not be a symlink')
    header = ('---\n' + json.dumps({'type': 'capture', 'captured_by': 'ctxbrain'}, indent=2) +
              '\n---\n# Yakalama ' + now.strftime('%Y-%m-%d') + '\n\n')
    try:
        with open(path, 'x', encoding='utf-8') as out:
            out.write(header)
        existing = ''
    except FileExistsError:
        existing = path.read_text(encoding='utf-8')
    session = str(session_id or 'unknown')[:8]
    lines, redacted = [], 0
    for kind, sentence in found:
        sentence, count = redact(sentence, state)
        redacted += count
        if ' · ' + sentence + '\n' in existing or any(line.endswith(' · ' + sentence) for line in lines):
            continue
        lines.append(f"- {now.strftime('%H:%M')} · {kind} · `{session}` · {sentence}")
    if redacted:
        record(state, redacted)
    if lines:
        with open(path, 'a', encoding='utf-8') as out:
            out.write('\n'.join(lines) + '\n')
    return len(lines)


# In-chat management. A prompt that starts with "ctx:" is handled by the hook itself and never
# reaches the model: no agent decides what is forgotten, and no tokens are spent.
COMMAND = re.compile(r'^\s*ctx\s*:\s*(.*)$', re.S | re.I)
ENTRY = re.compile(r'^- (\d\d:\d\d) · (\w+) · `[^`]*` · (.+)$')
RECENT = 50
SHOWN = 10
HELP = ('ctxbrain komutları (modele gitmez):\n'
        '  ctx: liste           son yakalananlar, en yeni 1 numara\n'
        '  ctx: unut son        en son yakalananı sil\n'
        '  ctx: unut 3          listedeki 3 numarayı sil\n'
        '  ctx: unut <kelime>   tek eşleşen kaydı sil\n'
        '  ctx: kaydet <cümle>  kaçırılan bir kararı elle kaydet\n'
        '  ctx: kapat / ctx: aç yakalamayı kapat veya aç')


def recent(vault, limit=RECENT):
    """Captured entries, newest first: (path, raw line, date, time, kind, sentence)."""
    directory = _directory(vault)
    if not directory.is_dir():
        return []
    found = []
    for path in sorted(directory.glob('????-??-??.md'), reverse=True):
        if path.is_symlink():
            continue
        for line in reversed(path.read_text(encoding='utf-8').splitlines()):
            match = ENTRY.match(line)
            if match:
                found.append((path, line, path.stem) + match.groups())
                if len(found) == limit:
                    return found
    return found


def _show(index, entry):
    return f'{index:>2}. {entry[2]} {entry[3]} {entry[4]}: {entry[5]}'


def _remove(entry):
    from beyin_v3_sync import atomic
    path, line = entry[0], entry[1]
    lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
    for position, current in enumerate(lines):
        if current.rstrip('\n') == line:
            del lines[position]
            break
    else:
        raise ValueError('entry changed on disk; run ctx: liste again')
    atomic(path, ''.join(lines))


def command(vault, state, prompt, session_id, now=None):
    """The reply to a "ctx:" prompt, or None when the prompt is not a command."""
    match = COMMAND.match(prompt) if isinstance(prompt, str) else None
    if not match:
        return None
    verb, _, rest = match.group(1).strip().partition(' ')
    verb, rest = fold(verb), rest.strip()
    if verb in ('', 'liste', 'list'):
        entries = recent(vault)
        if not entries:
            return 'Henüz yakalanan bir şey yok.\n\n' + HELP
        state_line = 'Yakalama açık.' if enabled(state) else 'Yakalama KAPALI (ctx: aç).'
        return (state_line + ' Son yakalananlar, en yeni üstte:\n' +
                '\n'.join(_show(i, e) for i, e in enumerate(entries[:SHOWN], 1)) +
                '\n\nSilmek için: ctx: unut <numara>')
    if verb in ('unut', 'sil', 'forget'):
        entries = recent(vault)
        if rest in ('', 'son', 'last'):
            chosen = entries[:1]
        elif rest.isdigit():
            chosen = entries[int(rest) - 1:int(rest)] if int(rest) >= 1 else []
        else:
            chosen = [e for e in entries if fold(rest) in fold(e[5])]
            if len(chosen) > 1:
                return ('Birden çok kayıt eşleşti; numarayla sil:\n' +
                        '\n'.join(_show(entries.index(e) + 1, e) for e in chosen))
        if not chosen:
            return 'Eşleşen kayıt yok. ctx: liste ile numaraları gör.'
        _remove(chosen[0])
        return 'Silindi: ' + chosen[0][5]
    if verb in ('kaydet', 'save'):
        if len(rest.split()) < 2:
            return 'Kaydedilecek cümleyi yaz: ctx: kaydet <cümle>'
        sentence = ' '.join(rest.split())
        if len(sentence) > MAX_SENTENCE:
            sentence = sentence[:MAX_SENTENCE - 1].rstrip() + '…'
        written = _append(vault, state, [('not', sentence)], session_id, now)
        return 'Kaydedildi.' if written else 'Bu cümle bugün zaten kayıtlı.'
    if verb in ('kapat', 'off'):
        save(state, False)
        return 'Yakalama kapatıldı. Açmak için: ctx: aç'
    if verb in ('ac', 'on'):
        save(state, True)
        return 'Yakalama açıldı.'
    return HELP
