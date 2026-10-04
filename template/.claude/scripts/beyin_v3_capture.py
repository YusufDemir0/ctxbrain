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
    if not found:
        return 0
    from beyin_v3_secrets import redact, record
    now = now or datetime.now().astimezone()
    directory = Path(vault) / DIRECTORY
    for part in (Path(vault) / 'knowledge', directory):
        if part.is_symlink():
            raise ValueError('capture directory must not be a symlink')
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
