# ctxbrain

AI kodlama ajanları için yerel, Türkçe öncelikli kalıcı hafıza. Claude Code, Codex veya
Google Antigravity'de bir klasörü açtığında, önceki oturumlarda verdiğin kararlar ve
yazdığın notlar o oturuma geri gelir. Notlar düz Markdown dosyalarıdır: Obsidian'da veya
herhangi bir editörde açılır, git ile eşitlenir.

Python 3.11+ yeterli. Sunucu, API anahtarı, pip paketi veya model çağrısı yok.

> ctxbrain, [avenoxai/avenoxbeyin](https://github.com/avenoxai/avenoxbeyin) V3.7.1 üzerine
> kurulmuş bağımsız bir projedir (MIT; orijinal lisans ve atıf korunur). Motorun hook,
> senkronizasyon ve kurulum katmanı oradan gelir. Orijinal belge:
> [docs/upstream/avenoxbeyin-README.md](docs/upstream/avenoxbeyin-README.md).

## Ne yapar

- **Konuşurken karar yakalar.** Her mesajında, cevap üretilmeden önce, karar ve kural
  bildiren cümlelerin ("…kullanalım", "…seçtik", "…olmamalı", "bundan sonra…",
  "asla…", "unutma…") `knowledge/yakalanan/YYYY-MM-DD.md` dosyasına yazılır. Onay
  istemez; oturumu yarıda kapatsan da o ana kadarki kararlar kalır. Sorular, kod
  blokları, uzun yapıştırmalar ve alt ajan bildirimleri atlanır, sırlar her zaman
  maskelenir.
- **Yakalananları sen yönetirsin, ajan değil.** Sohbete `ctx:` ile başlayan bir komut
  yazarsan hook onu kendisi işler ve modele hiç göndermez (token harcanmaz).
- **Türkçeyi anlar.** İsim ve fiil çekimleri köke iner ("kullanıyoruz" ↔ "kullandık"),
  ünsüz yumuşaması tanınır ("kilidi" ↔ "kilit"), ~50 teknik terim iki dilde eşleşir
  ("database" ↔ "veritabanı", "cache" ↔ "önbellek"), kısaltmalar önekle bulunur
  ("postgres" ↔ "PostgreSQL").
- **İlgili notu getirir.** Her mesajda sorunla ilgili notlar sınırlı bir bağlam olarak
  eklenir; ajan ayrıca `beyin.py context` ile açıkça arayabilir.
- **Paralel oturumlar birbirini ezmez.** Her oturum kendi kartını
  `🔮 850-Companion/Oturumlar/` altına yazar; `Last-Session.md` bu kartlardan üretilen kısa
  özettir. İki terminal, iki ajan ya da iki makine aynı anda çalışsa da devir notu kaybolmaz.
- **Yapılacaklar listesi.** "Bunu yapılacaklara ekle" dediğinde ajan işi yapmaz,
  `Yapılacaklar.md`'ye tarih ve kimlikle kaydeder. "Yapılacakları uygula" dediğinde
  bekleyenleri yapar ve her birini sonucuyla "Uygulanan işlemler" bölümüne taşır. Oturum
  başında bekleyen iş sayısı hatırlatılır.

## Nerede işe yarar

Hook'lar yalnız **vault klasörü** bir ajan istemcisinde açıkken tam çalışır.

| Kullanım | Durum |
|---|---|
| Vault'u Claude Code'da açıp planlama, karar, öğrenme oturumları | Tüm özellikler |
| Yeni proje: önce vault'ta karar ver, sonra kodu repoda yaz | Kararlar yakalanır, sonra aranır |
| Başka bir repoda çalışırken | Yakalama ve her mesaj bağlamı yok; ajan `context` ile arayabilir |
| claude.ai sohbet sekmesi | Çalışmaz (hook yok) |

## Kurulum

```bash
git clone https://github.com/YusufDemir0/ctxbrain.git
cd ctxbrain
python3 scripts/install_v3.py --vault "/tam/yol/Vault"
```

Vault klasörü boş bir klasör de olabilir, Obsidian vault'un da. Windows'ta `python3` yerine `py -3`. Kurulum yalnız vault içine yazar, global ayarlara
dokunmaz; makineye özel durum `~/.local/state/beyin-v3/` altında tutulur. Sonra vault
klasörünü Claude Code'da aç, workspace güvenini onayla ve yeni bir oturum başlat.
Bir ajana kurdurmak için: [beyin.md](beyin.md).

Git kopyasından kurulum sürümü `3.0.0` olarak kaydeder. Kurulumdan sonra vault klasöründe
`python3 beyin.py update` çalıştırırsan resmi sürüm paketi kurulur ve sürüm doğru görünür.

## Kullanım

İlk oturumda ajana: *"Beyin skill'ini kullan. Beni tanımak için kısa sorular sor."*

Sohbet içinden (modele gitmez):

| Komut | Ne yapar |
|---|---|
| `ctx: liste` | Son yakalananlar, en yeni 1 numara |
| `ctx: unut son` | En son yakalananı siler |
| `ctx: unut 3` | Listedeki 3 numarayı siler |
| `ctx: unut <kelime>` | Tek eşleşen kaydı siler; birden çok eşleşirse numaraları gösterir |
| `ctx: kaydet <cümle>` | Kaçırılan bir kararı elle kaydeder |
| `ctx: kapat` / `ctx: aç` | Yakalamayı kapatır / açar |

Terminalden, vault klasöründe aynı komutlar: `python3 beyin.py ctx unut son`.

Diğer komutlar:

```bash
python3 beyin.py context "hangi veritabanını seçtik"   # açık arama
python3 beyin.py doctor                                 # sağlık kontrolü
python3 beyin.py recap --days 7                         # son işler
python3 beyin.py preferences --profile economical       # daha az otomatik bağlam
python3 beyin.py yapilacak liste                        # bekleyen işler
python3 beyin.py yapilacak ekle --proje web "giriş sayfasını düzelt"
python3 beyin.py oturum liste                           # oturum kartları
python3 beyin.py update                                 # yeni sürüme güncelle
```

Yakalanan dosyalar düz Markdown'dır; Obsidian'da düzenleyebilir veya silebilirsin.

### Birden çok makine

Vault'u özel bir git deposunda tutup her makinede ayrı kurabilirsin; makineye özel durum
vault dışında kaldığı için çakışmaz ([docs/v3/MULTI-MACHINE.md](docs/v3/MULTI-MACHINE.md)).
Vault köküne şu satırı içeren bir `.gitattributes` eklemek, iki makinenin aynı nota yazdığı
durumda birleştirmeyi iki tarafın satırlarını da tutarak çözer:

```
*.md merge=union
```

## Geliştirme

```bash
python3 -m unittest discover -s tests -p "v[35]_*test.py"
python3 scripts/evaluate_v3_search.py                                                  # arama ölçümü
python3 scripts/evaluate_v3_search.py --fixture tests/fixtures/v3/search_vocabulary.json  # kelime uyuşmazlığı
python3 scripts/build_v3_release.py --version "$(cat VERSION)" --output "release/beyin-v3-$(cat VERSION).zip"
python3 /tam/yol/Vault/beyin.py update --package "release/beyin-v3-$(cat VERSION).zip"
```

Aynı sürüm tekrar uygulanırsa `noop` döner; vault'a yeni kod almak için önce `VERSION`
artırılır. Güncelleyici yalnız `YusufDemir0/ctxbrain` sürümlerini kabul eder.

## Ölçülen sonuçlar

| Ölçüm (1. sırada doğru not) | avenoxbeyin 3.7.1 | ctxbrain |
|---|---|---|
| Orijinal arama ölçümü, açık arama | %71.9 | %93.8 |
| Orijinal arama ölçümü, katı mod | %84.4 | %84.4 |
| Kelime uyuşmazlığı ölçümü, açık arama | %0 | %100 |
| Kelime uyuşmazlığı ölçümü, katı mod | %7.7 | %53.8 |

## Sınırlar

- Yakalama sezgiseldir; yanlış veya eksik yakalamalar olur. `ctx: unut` ve `ctx: kaydet` bunun için var.
- Her mesajdaki otomatik bağlam bilinçli olarak dar tutulur: fiil kökleri ve önekler
  yalnız açık aramada çalışır, çünkü otomatik bağlamda gürültü üretiyorlar.
- Ünlüyle biten köklerin 3. tekil geçmişi ("bekledi", "okudu") köke inmez; "kilidi"
  (kilit+i) ile aynı biçimdedir.
- Komut ve dosya adları (`beyin.py`, `beyin_v3_*`, `beyin` skill'leri) motorun
  kökeninden gelir; yeniden adlandırma ayrı bir adım olarak planlanır.
- Yalnız Linux'ta test edildi.
