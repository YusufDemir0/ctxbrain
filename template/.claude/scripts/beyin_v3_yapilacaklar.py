"""Yapılacaklar.md: record work for later, list it, and move it to done when it is applied.

Format:
  - [ ] **Y-261019-k3f9** · 2026-10-19 15:02 · `proje` · iş metni
    - Not: bağlam
  - [x] **Y-261019-k3f9** · kayıt 2026-10-19 15:02 · uygulandı 2026-10-20 10:11 · `proje` · iş metni
    - Not: bağlam
    - Sonuç: ne yapıldı
"""
import re
import secrets
from datetime import datetime
from pathlib import Path

NAME = "Yapılacaklar.md"
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
PENDING = "## Yapılacak işler"
DONE = "## Uygulanan işlemler"
ITEM = re.compile(r"^- \[[ x]\] \*\*(Y-\d{6}-[a-z0-9]{4})\*\* · (.*)$")
STARTER = ("# Yapılacaklar\n\n"
           "\"Yapılacaklara ekle\" denince iş uygulanmaz, buraya kaydedilir; \"yapılacakları uygula\" "
           "denince bekleyenler yapılır ve sonuçlarıyla aşağıya taşınır. "
           "Komutlar: `beyin.py yapilacak ekle|liste|uygulandi`.\n\n"
           f"{PENDING}\n\n{DONE}\n")


def _now():
    return datetime.now().astimezone()


def _one_line(text):
    return " ".join(str(text).split())


def _file(vault):
    return Path(vault).resolve() / NAME


def _load(vault, create=False):
    path = _file(vault)
    if not path.exists():
        if not create:
            return None, 0, 0
        path.write_text(STARTER, encoding="utf-8")
    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        start, end = lines.index(PENDING), lines.index(DONE)
    except ValueError:
        raise ValueError(f"{NAME} içinde '{PENDING}' ve '{DONE}' başlıkları olmalı")
    return lines, start, end


def _blocks(lines, start, end):
    """(id, first, last) per item; an item and its indented lines form one block."""
    found, i = [], start + 1
    while i < end:
        match = ITEM.match(lines[i])
        if not match:
            i += 1
            continue
        j = i + 1
        while j < end and lines[j].startswith("  "):
            j += 1
        found.append((match.group(1), i, j))
        i = j
    return found


def _save(vault, lines):
    tidy = []
    for line in lines:
        if line.startswith("## ") and tidy and tidy[-1].strip():
            tidy.append("")
        if line.strip() or (tidy and tidy[-1].strip()):
            tidy.append(line)
    _file(vault).write_text("\n".join(tidy).rstrip("\n") + "\n", encoding="utf-8")


def ekle(vault, metin, proje="genel", not_=None):
    if not _one_line(metin):
        raise ValueError("iş metni boş")
    lines, start, end = _load(vault, create=True)
    stamp = _now()
    # A random suffix keeps ids unique when two machines record on the same day and git merges them.
    used = {m.group(1) for m in map(ITEM.match, lines) if m}
    while True:
        item_id = f"Y-{stamp:%y%m%d}-" + "".join(secrets.choice(ALPHABET) for _ in range(4))
        if item_id not in used:
            break
    entry = [f"- [ ] **{item_id}** · {stamp:%Y-%m-%d %H:%M} · `{_one_line(proje) or 'genel'}` · {_one_line(metin)}"]
    if not_ and _one_line(not_):
        entry.append(f"  - Not: {_one_line(not_)}")
    position = end
    while position > start + 1 and not lines[position - 1].strip():
        position -= 1
    lines[position:position] = entry if position > start + 1 else [""] + entry
    _save(vault, lines)
    return item_id


def bekleyenler(vault):
    lines, start, end = _load(vault)
    if lines is None:
        return []
    return [(item_id, lines[a:b]) for item_id, a, b in _blocks(lines, start, end)]


def uygulandi(vault, item_id, sonuc):
    if not _one_line(sonuc):
        raise ValueError("--sonuc boş olamaz")
    lines, start, end = _load(vault)
    match = next((b for b in _blocks(lines, start, end) if b[0] == item_id), None) if lines else None
    if match is None:
        raise ValueError(f"{item_id} yapılacak işler arasında yok")
    _, a, b = match
    block = lines[a:b]
    recorded, rest = ITEM.match(block[0]).group(2).split(" · ", 1)
    moved = [f"- [x] **{item_id}** · kayıt {recorded} · uygulandı {_now():%Y-%m-%d %H:%M} · {rest}"]
    moved += block[1:] + [f"  - Sonuç: {_one_line(sonuc)}"]
    del lines[a:b]
    insert = lines.index(DONE) + 1
    while insert < len(lines) and not lines[insert].strip():
        insert += 1
    lines[insert:insert] = moved if insert < len(lines) else [""] + moved
    if lines[lines.index(DONE) + 1].strip():
        lines.insert(lines.index(DONE) + 1, "")
    _save(vault, lines)


def _fold(text):
    text = text.replace("I", "ı").replace("İ", "i").lower()
    return text.translate(str.maketrans("ığüşöç", "igusoc"))


def hook_notice(vault, event, prompt=""):
    """One line of protocol for the agent, or ''. Reads a single file; never writes."""
    try:
        if event == "SessionStart":
            items = bekleyenler(vault)
            if not items:
                return ""
            projects = sorted({m.group(1) for _, b in items for m in [re.search(r"`([^`]+)`", b[0])] if m})
            return (f"Yapılacaklar: {len(items)} bekleyen iş ({', '.join(projects)}). "
                    "Liste: `beyin.py yapilacak liste`. Kullanıcı uygula demeden uygulama.\n")
        if event != "UserPromptSubmit":
            return ""
        text = _fold(prompt or "")
        mentions = "yapilacak" in text or re.search(r"\by-\d{6}-[a-z0-9]{4}\b", text)
        if mentions and "uygula" in text:
            return ("Yapılacaklar protokolü (uygulama): önce `beyin.py yapilacak liste` ile bekleyenleri gör. "
                    "Kullanıcı kimlik ya da proje söylediyse yalnız onları, söylemediyse hepsini uygula. "
                    "Her iş gerçekten bitince `beyin.py yapilacak uygulandi <ID> --sonuc \"<ne yapıldı>\"` çalıştır. "
                    "Yarım kalan ya da bu ortamda erişilemeyen işi işaretleme, nedenini söyle.\n")
        if mentions and re.search(r"kaydet|ekle|yaz", text):
            return ("Yapılacaklar protokolü (kayıt): işi UYGULAMA, kaydet. Her ayrı iş için "
                    "`beyin.py yapilacak ekle --proje <proje> \"<iş, tek cümle>\" [--not \"<bağlam>\"]` çalıştır, "
                    "sonra kimlikleri kısaca söyle.\n")
    except (OSError, ValueError):
        pass
    return ""
