"""The writer fields shared by receipts, cards and semantic notes."""
import hashlib
import json
from pathlib import Path
import re

from beyin_v3_vault import file_lock


def origin_fields(harness=None, session=None, model=None):
    if session is not None and (not isinstance(session, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', session)):
        raise ValueError('invalid origin session')
    if model is not None and (not isinstance(model, str) or not model.strip()
                              or len(model) > 200 or not model.isprintable()):
        raise ValueError('invalid origin model')
    return {key: value for key, value in (('harness', harness), ('session', session), ('model', model))
            if value is not None}


def receipt_session(session_id):
    return hashlib.sha256(str(session_id).encode('utf-8')).hexdigest()[:24]


def _append_frontmatter(text, fields):
    from beyin_v3_sync import parse

    newline = '\r\n' if '\r\n' in text else '\n'
    yaml_fields = ''.join(f'{key}: {json.dumps(value, ensure_ascii=False)}{newline}' for key, value in fields.items())
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != '---':
        return '---' + newline + yaml_fields + '---' + newline + text
    metadata, _ = parse(text)
    if metadata.keys() & {'harness', 'session', 'model'}:
        return text  # An earlier writer owns this origin.
    end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == '---')
    header = ''.join(lines[1:end])
    if header.lstrip().startswith('{'):
        closing_brace = header.rindex('}')
        additions = json.dumps(fields, ensure_ascii=False)[1:-1]
        header = header[:closing_brace] + (', ' if metadata else '') + additions + header[closing_brace:]
    else:
        header += yaml_fields
    return lines[0] + header + ''.join(lines[end:])


def tag_edited_notes(vault, harness, payload):
    from beyin_v3_hygiene import edited_paths
    from beyin_v3_sync import atomic

    session = payload.get('session_id')
    session = receipt_session(session) if isinstance(session, str) and session not in ('', 'unknown') else None
    try:
        fields = origin_fields(harness, session, payload.get('model'))
    except ValueError:
        fields = origin_fields(harness, session)
    for path in edited_paths(payload):
        try:
            relative = path.resolve().relative_to(Path(vault).resolve())
            if relative.parts[0] != 'knowledge' or path.suffix != '.md' or path.is_symlink() or not path.is_file():
                continue
            with file_lock(vault, path, timeout=0):
                raw = path.read_bytes()
                original = raw.decode('utf-8')
                bom = '\ufeff' if original.startswith('\ufeff') else ''
                updated = bom + _append_frontmatter(original.removeprefix('\ufeff'), fields)
                if updated != original:
                    atomic(path, updated, expected=raw)
        except (OSError, ValueError, RuntimeError, IndexError):
            continue  # Unsupported metadata, a busy file or a concurrent editor wins.
