"""Per-session cards; Last-Session.md is rebuilt from them and never edited by hand.

Each session writes only its own card under `<companion>/Oturumlar/`. `derle` regenerates
Last-Session.md from scratch (same cards -> same output), so parallel sessions and a git
merge of two machines can never overwrite each other: the next `derle` repairs everything.
"""
import re
from datetime import datetime
from pathlib import Path

from beyin_v3_companion import directory, read_limits
from beyin_v3_origin import origin_fields
from beyin_v3_sync import atomic, parse, render
from beyin_v3_vault import file_lock

CARD_CAP = 900          # per-card share of the summary
HEAD = re.compile(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) · (.+?) · ([0-9a-f]{8})\s*$")
PROJE = re.compile(r"^Proje: (.+)$", re.M)
INTRO = ("# Son oturum\n\n"
         "Bu dosya `beyin.py oturum derle` ile `Oturumlar/` kartlarından üretilir; elle düzenleme. "
         "Kendi kartını `beyin.py oturum yaz` ile yaz, başka oturumun kartına dokunma.\n")


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower().translate(str.maketrans("çğıöşü", "cgiosu"))).strip("-")
    return s[:40] or "oturum"


def _companion(vault):
    target = directory(vault)
    if target is None:
        raise ValueError("Birden çok companion klasörü var; hangisinin kullanılacağı belirsiz")
    return target


def cards(vault):
    folder = _companion(vault) / "Oturumlar"
    out = []
    for p in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        try:
            metadata, text = parse(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        m = HEAD.match(text.splitlines()[0]) if text.strip() else None
        if not m:
            continue
        pm = PROJE.search(text)
        out.append({"path": p, "when": m.group(1), "label": m.group(2), "sid": m.group(3),
                    "project": pm.group(1).strip() if pm else m.group(2), "text": text.strip(),
                    "metadata": metadata})
    out.sort(key=lambda c: c["when"], reverse=True)
    return out


def _shorten(card):
    text = card["text"]
    if len(text) <= CARD_CAP:
        return text
    cut = text[:CARD_CAP].rsplit("\n", 1)[0]
    return cut + f"\n- … (tamamı: `Oturumlar/{card['path'].name}`)"


def _budget(state):
    # Stay under the hygiene limit so a generated summary never triggers its own warning.
    limit = read_limits(state)[0].get("Last-Session.md", 3000) if state else 3000
    return max(1000, limit - 200) if limit else 2800


def derle(vault, state=None, *, timeout=2.0):
    path = _companion(vault) / "Last-Session.md"
    with file_lock(vault, path, timeout=timeout):
        return _derle(vault, state, path)


def _derle(vault, state, path):
    allc = cards(vault)
    picked, seen = [], set()
    for c in allc:                      # newest card of each project first, so agents never shadow each other
        if c["project"] not in seen:
            seen.add(c["project"])
            picked.append(c)
    picked += [c for c in allc if c not in picked]
    picked.sort(key=lambda c: c["when"], reverse=True)
    try:  # yarım kalan işler (devir kartları) en üstte; hata özeti asla düşürmez
        from beyin_v3_devir import ozet
        devir = ozet(vault)
    except Exception:
        devir = ""
    budget = _budget(state)  # render() devir bölümünü zaten sayar; ayrıca düşülmez
    shown = [(c, _shorten(c)) for c in picked]

    def render(count):
        rest = [c for c, _ in shown[count:]]
        tail = ""
        if rest:
            tail = "\n\n## Diğer kartlar\n" + "\n".join(
                f"- {c['when']} · {c['label']} · {c['sid']} → `Oturumlar/{c['path'].name}`" for c in rest[:8])
        return INTRO + "\n" + (devir + "\n" if devir else "") + "\n\n".join(block for _, block in shown[:count]) + tail + "\n"

    # The link list counts against the budget too: drop the oldest full card until it all fits.
    count = len(shown)
    while count and len(render(count)) > budget:
        count -= 1
    atomic(path, render(count))
    return {"cards": len(allc), "shown": count}


def yaz(vault, state, session, etiket, body, proje=None, now=None, harness=None, model=None):
    sid = re.sub(r"[^0-9a-f]", "", str(session).lower())[:8]
    if len(sid) != 8:
        raise ValueError("session: Receipt session kimliğinin ilk 8 onaltılık karakteri gerekli")
    etiket = " ".join(str(etiket).split())
    if not etiket or "·" in etiket:
        raise ValueError("etiket boş olamaz ve '·' içeremez")
    if not body.strip():
        raise ValueError("kart gövdesi boş")
    fields = origin_fields(harness, session, model)
    summary = _companion(vault) / "Last-Session.md"
    with file_lock(vault, summary):
        now = now or datetime.now().astimezone()
        mine = next((c for c in cards(vault) if c["sid"] == sid and c["label"] == etiket), None)
        folder = summary.parent / "Oturumlar"
        path = mine["path"] if mine else folder / f"{now:%Y-%m-%d}-{now:%H%M}-{sid}-{slug(etiket)}.md"
        when = mine["when"] if mine else f"{now:%Y-%m-%d %H:%M}"
        line = f"Proje: {' '.join(proje.split())}\n" if proje and proje.strip() else ""
        metadata = dict(mine["metadata"]) if mine else {}
        metadata.update(fields)
        metadata.setdefault("harness", "manual")
        with file_lock(vault, path):
            atomic(path, render(metadata, f"## {when} · {etiket} · {sid}\n{line}{body.strip()}\n"))
        from beyin_v3_devir import kapat
        closed = kapat(vault, sid, "oturum kartı yazıldı")
        result = _derle(vault, state, summary)
    return dict(result, card=path.relative_to(Path(vault).resolve()).as_posix(), updated=bool(mine), devir_closed=closed)


def close_handoff(vault, state, sid, reason):
    from beyin_v3_devir import kapat, open_paths

    if not open_paths(vault, sid):
        return 0
    summary = _companion(vault) / "Last-Session.md"
    with file_lock(vault, summary):
        count = kapat(vault, sid, reason)
        if count:
            _derle(vault, state, summary)
        return count


def liste(vault):
    return [f"{c['when']} · {c['project']} · {c['label']} · {c['sid']}" for c in cards(vault)]
