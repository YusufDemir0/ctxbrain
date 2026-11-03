"""Per-session cards; Last-Session.md is rebuilt from them and never edited by hand.

Each session writes only its own card under `<companion>/Oturumlar/`. `derle` regenerates
Last-Session.md from scratch (same cards -> same output), so parallel sessions and a git
merge of two machines can never overwrite each other: the next `derle` repairs everything.
"""
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from beyin_v3_companion import directory, read_limits

CARD_CAP = 900          # per-card share of the summary
HEAD = re.compile(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) · (.+?) · ([0-9a-f]{8})\s*$")
PROJE = re.compile(r"^Proje: (.+)$", re.M)
INTRO = ("# Son oturum\n\n"
         "Bu dosya `beyin.py oturum derle` ile `Oturumlar/` kartlarından üretilir; elle düzenleme. "
         "Kendi kartını `beyin.py oturum yaz` ile yaz, başka oturumun kartına dokunma.\n")


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower().translate(str.maketrans("çğıöşü", "cgiosu"))).strip("-")
    return s[:40] or "oturum"


def _atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".oturum-", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(text)
    os.replace(tmp, path)


def _companion(vault):
    target = directory(vault)
    if target is None:
        raise ValueError("Birden çok companion klasörü var; hangisinin kullanılacağı belirsiz")
    return target


def cards(vault):
    folder = _companion(vault) / "Oturumlar"
    out = []
    for p in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        text = p.read_text(encoding="utf-8")
        m = HEAD.match(text.splitlines()[0]) if text.strip() else None
        if not m:
            continue
        pm = PROJE.search(text)
        out.append({"path": p, "when": m.group(1), "label": m.group(2), "sid": m.group(3),
                    "project": pm.group(1).strip() if pm else m.group(2), "text": text.strip()})
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


def derle(vault, state=None):
    allc = cards(vault)
    picked, seen = [], set()
    for c in allc:                      # newest card of each project first, so agents never shadow each other
        if c["project"] not in seen:
            seen.add(c["project"])
            picked.append(c)
    picked += [c for c in allc if c not in picked]
    picked.sort(key=lambda c: c["when"], reverse=True)
    budget = _budget(state)
    shown = [(c, _shorten(c)) for c in picked]

    def render(count):
        rest = [c for c, _ in shown[count:]]
        tail = ""
        if rest:
            tail = "\n\n## Diğer kartlar\n" + "\n".join(
                f"- {c['when']} · {c['label']} · {c['sid']} → `Oturumlar/{c['path'].name}`" for c in rest[:8])
        return INTRO + "\n" + "\n\n".join(block for _, block in shown[:count]) + tail + "\n"

    # The link list counts against the budget too: drop the oldest full card until it all fits.
    count = len(shown)
    while count and len(render(count)) > budget:
        count -= 1
    _atomic(_companion(vault) / "Last-Session.md", render(count))
    return {"cards": len(allc), "shown": count}


def yaz(vault, state, session, etiket, body, proje=None, now=None):
    sid = re.sub(r"[^0-9a-f]", "", str(session).lower())[:8]
    if len(sid) != 8:
        raise ValueError("session: Receipt session kimliğinin ilk 8 onaltılık karakteri gerekli")
    etiket = " ".join(str(etiket).split())
    if not etiket or "·" in etiket:
        raise ValueError("etiket boş olamaz ve '·' içeremez")
    if not body.strip():
        raise ValueError("kart gövdesi boş")
    now = now or datetime.now().astimezone()
    mine = [c for c in cards(vault) if c["sid"] == sid and c["label"] == etiket]
    folder = _companion(vault) / "Oturumlar"
    path = mine[0]["path"] if mine else folder / f"{now:%Y-%m-%d}-{now:%H%M}-{sid}-{slug(etiket)}.md"
    when = mine[0]["when"] if mine else f"{now:%Y-%m-%d %H:%M}"
    line = f"Proje: {' '.join(proje.split())}\n" if proje and proje.strip() else ""
    _atomic(path, f"## {when} · {etiket} · {sid}\n{line}{body.strip()}\n")
    result = derle(vault, state)
    return dict(result, card=path.relative_to(Path(vault).resolve()).as_posix(), updated=bool(mine))


def liste(vault):
    return [f"{c['when']} · {c['project']} · {c['label']} · {c['sid']}" for c in cards(vault)]
