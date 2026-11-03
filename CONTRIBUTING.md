# Katkı rehberi

ctxbrain'i kullanıcılar geliştirir: her kullanıcının beyni kendi vault'unda farklı büyür, ama
beynin nasıl öğrendiği, hatırladığı ve unuttuğu bu depodadır ve herkes için aynıdır. Bu belge,
bir değişikliği nasıl önereceğini ve hangi kurallara uyacağını anlatır.

## Önce okunacaklar

1. [README.md](README.md): ne yaptığı ve nasıl kullanıldığı.
2. [docs/v5/02-mimari.md](docs/v5/02-mimari.md): olay → refleks → çekirdek modeli ve gerekçeleri.
3. [docs/v5/01-avenox-denetimi.md](docs/v5/01-avenox-denetimi.md): upstream'den neyin neden
   alındığı ya da alınmadığı.

## Değişmez ilkeler

- **Beyin ve vault ayrıdır.** Depoya hiçbir kullanıcı verisi girmez: test verisi, ölçüm seti ve
  örnekler sentetiktir. Kendi vault'unda ölçtüğün sonuçları sayı olarak paylaşabilirsin, içeriğini
  değil.
- **Yerel ve model çağırmayan çekirdek.** Hook'lar ve CLI ağa çıkmaz (sürüm kontrolü hariç),
  model çağırmaz, pip bağımlılığı eklemez; Python standart kütüphanesi yeter. Model gerektiren her
  fikir bir "model yuvası" olarak tasarlanır ve deterministik bir karşılığı olur.
- **Markdown gerçeğin kendisidir.** İndeks yeniden üretilebilir bir önbellektir; kullanıcının
  elle düzenleyebileceği her şey vault'ta düz Markdown'dır, makineye özel durum vault dışındadır.
- **Kullanıcı verisini silme.** Taşıma, arşivleme, söndürme olur; silme olmaz. Toplu bir değişiklik
  önce kuru çalıştırma verir, sonra yedek alarak uygular.
- **Hook bir turu asla düşürmez.** Hook içindeki her yeni adım hata verirse sessizce geri çekilir
  (fail open) ve istemcinin süre sınırını aşmaz.
- **Çıkarım olgu değildir.** Kullanıcının söylediği, kaynaktan doğrulanan ve modelin çıkardığı
  bilgi farklı güvende tutulur. Refleksin ağırlığı kanıtından gelir, tahminden değil.
- **Kelimeye değil anlama.** Kullanıcının sözünü harfiyen daraltan özellikler yerine niyeti
  soran ya da alternatif sunan davranışlar tercih edilir.

## Bir değişikliği önermek

1. **Sorunu ölç.** Mümkünse kendi vault'unda sayıya dök (`scripts/evaluate_*.py` ya da benzeri
   bir betik). "Daha iyi oldu" değil "%35 tekrar %0'a indi" denir.
2. **Tasarımı yaz.** Küçük değişiklikte PR açıklaması yeter; davranışı değiştiren her şey için
   `docs/v5/` altına kısa bir not: sorun, neden bu çözüm, alternatifler, geri alma.
3. **Test yaz.** Yeni davranış `tests/v5_*_test.py` altında sentetik bir vault ile test edilir.
   Hook davranışı değişiyorsa kurulu CLI üzerinden uçtan uca bir test de eklenir.
4. **Tüm testleri çalıştır:**
   ```bash
   python3 -m unittest discover -s tests -p "v[35]_*test.py"
   python3 scripts/evaluate_v3_search.py
   python3 scripts/evaluate_v5_reflex.py
   ```
5. **Talimatları eşitle.** Ajanın davranışını değiştiren bir şey eklediysen dört yeri birlikte
   güncelle: `scripts/install_v3.py` içindeki AGENTS bloğu, `template/.agents/skills/beyin/SKILL.md`,
   `template/CLAUDE.md` ve README'nin ilgili bölümü.

## Nerede ne var

| Yol | Ne |
|---|---|
| `scripts/install_v3.py` | Kurulum, güncelleme, AGENTS bloğu |
| `scripts/beyin_v3.py` | CLI (`beyin.py` vault'ta buna yönlenir) |
| `scripts/beyin_entry.py` | Vault'taki `beyin.py`: update, rollback, recover |
| `scripts/build_v3_release.py` | Sürüm paketi |
| `template/.claude/scripts/beyin_v3_hook.py` | Tüm istemcilerin hook giriş noktası |
| `template/.claude/scripts/beyin_v3_refleks.py` | Refleksler, proje kapısı, oturum taslağı |
| `template/.claude/scripts/beyin_v3_capture.py` | Konuşmadan karar yakalama |
| `template/.claude/scripts/beyin_v3_companion.py` | Açılış bağlamı, companion dosyaları |
| `template/.claude/scripts/beyin_v3_sync.py` | Markdown → SQLite indeks |
| `template/.claude/scripts/beyin_v3.py` | Arama motoru, Türkçe kökleme, bağlam paketleme |
| `template/.claude/scripts/beyin_v3_oturum.py`, `beyin_v3_yapilacaklar.py` | Oturum kartları, yapılacaklar |
| `template/.agents/skills/` | Ajan skill'leri (`beyin`, `beyin-doktor`, `beyin-guncelle`) |
| `tests/` | `v3_*` motor testleri, `v5_*` refleks ve kapı testleri |

Kurulum `template/.claude/scripts/beyin_v3*.py` dosyalarını vault'a kopyalar; yeni bir modül bu
adla başlarsa pakete ve güncellemeye kendiliğinden girer.

## Sürüm

`VERSION` ve `docs/v5/releases/X.Y.Z.md` aynı sürümü anlatır. Paket
`scripts/build_v3_release.py` ile üretilir ve GitHub sürümüne `beyin-v3-X.Y.Z.zip` ve `.sha256`
olarak yüklenir; vault'lardaki `beyin.py update` yalnız bu iki dosyayı kabul eder.

## Commit ve PR

- Commit mesajı kısa bir özet satırı ve neden'i anlatan bir gövde.
- PR açıklamasında: ölçüm (önce/sonra), test sonucu, talimatların eşitlenip eşitlenmediği.
- Kullanıcı verisi, gerçek isimler, yollar ya da sırlar commit'e girmez.
