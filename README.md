# ctxbrain

AI ajanları için yerel, Türkçe öncelikli bir **beyin**. Claude Code, Codex, Antigravity ya da
OpenCode'da bir klasörü (vault) açtığında beyin, o klasördeki Markdown notlardan seni tanır.
Kararlarını yakalar, düzeltmelerini refleks olarak öğrenir ve her mesajda yalnız o anki işe
ilgili olanı ajanın önüne koyar. Sunucu, API anahtarı, pip paketi ya da model çağrısı yok;
Python 3.11+ yeterli.

> **Bu depoyu bir ajan okuyorsa:** Kurulum tarifi [beyin.md](beyin.md)'de, mimari
> [docs/v5/02-mimari.md](docs/v5/02-mimari.md)'de, katkı kuralları
> [CONTRIBUTING.md](CONTRIBUTING.md)'de. Kullanıcının notlarını silme ya da taşıma; her
> komutun çıktısını doğrula. Kurulum yalnız vault klasörüne yazar.

## İçindekiler

1. [İki yapı: beyin ve vault](#iki-yapı-beyin-ve-vault)
2. [Ne yapar](#ne-yapar)
3. [Kurulum](#kurulum)
4. [İlk oturum](#ilk-oturum)
5. [Günlük kullanım](#günlük-kullanım)
6. [Komutlar](#komutlar)
7. [Vault'ta ne nerede](#vaultta-ne-nerede)
8. [Nasıl çalışır](#nasıl-çalışır)
9. [Gizlilik](#gizlilik)
10. [Birden çok makine](#birden-çok-makine)
11. [Güncelleme ve geri alma](#güncelleme-ve-geri-alma)
12. [Sorun giderme](#sorun-giderme)
13. [Ölçülen sonuçlar](#ölçülen-sonuçlar)
14. [Sınırlar ve yol haritası](#sınırlar-ve-yol-haritası)
15. [Geliştirme ve katkı](#geliştirme-ve-katkı)
16. [Köken ve lisans](#köken-ve-lisans)

## İki yapı: beyin ve vault

| | Beyin | Vault |
|---|---|---|
| Nedir | Bu depo: hook'lar, CLI, skill'ler | Senin Markdown klasörün (Obsidian vault'u olabilir) |
| Kimde | Herkese açık olabilir; içinde kullanıcıya ait hiçbir bilgi yok | Her zaman private; yalnız sen |
| Ne tutar | Nasıl öğrenileceğini, hatırlanacağını, unutulacağını | Seni: kararların, kuralların, projelerin, notların |
| Kim geliştirir | Kullanıcılar, kod katkısıyla | Beyin, seninle konuşurken |

Seninle ilgili her çıkarım vault'tan gelir. Senin yaşadıkların vault'u değiştirir, beyin de
vault'u inceleyip geliştirir. Makineye özel çalışma durumu (indeks, oturum kayıtları) vault
dışında, `~/.local/state/beyin-v3/` altında tutulur.

## Ne yapar

- **Seni bağlama göre hatırlar (refleksler).** Bir düzeltmen ("depocu kârı görmesin") o projeye
  ait bir **refleks** olur ve yalnız o proje konuşulurken ya da o projenin dosyasına
  dokunulurken yüklenir. Aynı şeyi tekrar söylersen yeni bir satır değil, daha güçlü bir refleks
  olur; yakalanan cümlen bir refleksi açıkça tekrar ediyorsa kanıt kendiliğinden eklenir, emin
  olunamayanlar ajana öneri olarak gider. Kullanılmayan refleks zamanla söner ama silinmez; projesine döndüğünde "eski, doğrula"
  işaretiyle geri gelir. Zaman geçtiği ve koşullar değiştiği halde yönü değişmeyen refleks
  **çekirdeğe** yükselir.
- **Konuşurken karar yakalar.** Karar ve kural bildiren cümlelerin ("…kullanalım", "…olmamalı",
  "bundan sonra…", "asla…", "unutma…") cevap üretilmeden önce `knowledge/yakalanan/` altına
  yazılır. Ajanın hatırlamasına bağlı değildir; oturum yarıda kapansa da kalır. Sırlar maskelenir.
- **Gereksiz bağlamı eler.** Her mesajda ilgili notlar sınırlı bir bağlam olarak eklenir. Aynı not
  aynı oturumda iki kez gelmez; proje sözlüğün varsa etkin olmayan projelerin notları gelmez;
  "1", "tamam devam et" gibi mesajlarda arama yapılmaz.
- **Türkçeyi anlar.** Çekimler köke iner ("kullanıyoruz" ↔ "kullandık"), ünsüz yumuşaması tanınır
  ("kilidi" ↔ "kilit"), ~50 teknik terim iki dilde eşleşir ("veritabanı" ↔ "database").
- **Paralel oturumlar birbirini ezmez.** Her oturum kendi kartını yazar; `Last-Session.md` bu
  kartlardan üretilir.
- **Yapılacaklar.** "Bunu yapılacaklara ekle" dersen ajan işi yapmaz, tarih ve kimlikle kaydeder;
  "yapılacakları uygula" dersen bekleyenleri yapar ve sonucuyla kapatır.
- **Oturumu kapatmayı kolaylaştırır.** Dosya değişmiş ama kayıt yazılmamışsa, Stop anında ajana
  bu oturumda değişen dosyaları ve senin söylediğin kararları taslak olarak verir; ajan hatırlamak
  yerine doğrular.
- **Sohbet içi komutlar.** `ctx:` ile başlayan mesajları hook kendisi işler, modele hiç gitmez.

## Kurulum

### Gereksinimler

- Python 3.11 veya daha yenisi (macOS/Linux'ta `python3`, Windows'ta `py -3`).
- Desteklenen bir ajan istemcisi: Claude Code, Codex, Google Antigravity, OpenCode, Hermes, OMP.
- Git (yalnız kaynağı almak için).

### Adımlar

```bash
git clone https://github.com/YusufDemir0/ctxbrain.git
cd ctxbrain
python3 scripts/install_v3.py --vault "/tam/yol/Vault" --plan   # önce ne yazacağını gör
python3 scripts/install_v3.py --vault "/tam/yol/Vault"
cd "/tam/yol/Vault"
python3 beyin.py update        # resmi paketi kurar, sürüm damgasını düzeltir
python3 beyin.py doctor --human
```

- Vault boş bir klasör, mevcut bir not klasörü ya da Obsidian vault'u olabilir. Kurulum yalnız
  vault içine yazar, global ayarlara dokunmaz, notlarını silmez.
- Git kopyasından yapılan kurulum sürümü `3.0.0` olarak damgalar; `beyin.py update` GitHub'daki
  resmi paketi doğrulayıp kurar ve damgayı düzeltir.
- Windows'ta `python3` yerine `py -3`. Ayrıntı: [SETUP-WINDOWS.md](SETUP-WINDOWS.md).
- Antigravity: [SETUP-ANTIGRAVITY.md](SETUP-ANTIGRAVITY.md). Diğer istemciler: [docs/v3/](docs/v3/).
- **Bir ajana kurdurmak için** ajana şunu söyle: *"github.com/YusufDemir0/ctxbrain deposundaki
  beyin.md'yi oku ve bu klasöre kur."*

Kurulumdan sonra vault klasörünü ajan istemcisinde aç, workspace güvenini onayla ve yeni bir
oturum başlat. `doctor` ilk oturumdan sonra istemciyi "olay görüldü" olarak gösterir.

## İlk oturum

1. Ajana: *"Beyin skill'ini kullan. Beni tanımak için kısa sorular sor."* Ajan adını, hitabını,
   çalıştığın alanları ve beklentilerini sorar, cevapları `Core.md`'ye yazar.
2. **Proje sözlüğünü kur.** Refleksler ve bağlam kapısı projeleri bu sözlükle tanır:
   ```bash
   python3 beyin.py refleks sozluk --olustur
   ```
   Komut `projeler/` (ya da `projects/`) altındaki klasörlerden sözlüğü üretir. Sonra
   `🔮 850-Companion/Refleksler/_sozluk.md` dosyasını aç ve her projeye günlük dilde kullandığın
   takma adları ekle:
   ```markdown
   - magaza-erp: erp, mağaza, sevkiyat, stok
   - video-kanali: video, kapak, shorts
   ```
   Sözlük yoksa her şey çalışır, yalnız proje kapısı kapalı kalır.
3. **Eski kuralların varsa taşı.** `Kurallar.md` uzunsa tek projeye ait kuralları reflekse çevir:
   ```bash
   python3 beyin.py refleks gocet            # kuru çalıştırma: ne taşınacak
   python3 beyin.py refleks gocet --uygula   # önce arşive tam yedek, sonra taşı
   ```
   Yalnız etiketi tek bir projeyi anan kurallar taşınır; genel ya da birden çok projeyi anan
   kurallar her oturumda yüklenmeye devam eder.

## Günlük kullanım

Çoğu şeyi konuşarak yaparsın; ajan komutları kendisi çalıştırır.

| Sen dersin ki | Ne olur |
|---|---|
| "Depocu kârı görmesin, unutma." | Cümle yakalanır; ajan bunu ilgili projeye refleks olarak kaydeder |
| "Hayır, öyle değil, …" (düzeltme) | Ajan `refleks ekle --tur duzeltme`; benzer refleks varsa ona kanıt ekler |
| "Bunu yapılacaklara ekle." | İş yapılmaz, `Yapılacaklar.md`'ye kaydedilir |
| "Yapılacakları uygula." | Bekleyenler yapılır, sonuçlarıyla kapatılır |
| "Son günlerde ne yaptık?" | `recap` ile kayıtlar özetlenir |
| `ctx: liste` | Son yakalananlar (modele gitmez) |
| `ctx: unut son` / `ctx: unut 3` | Yanlış yakalananı siler |
| `ctx: kaydet <cümle>` | Kaçan bir kararı elle kaydeder |
| `ctx: kapat` / `ctx: aç` | Yakalamayı kapatır / açar |

Ajan iki refleks arasında kalırsa en olası olanı önerir ve alternatifi söyler. Geri alınamaz
işlerde sorar, geri alınabilir işlerde ilerler ama "şu seçeneklerden şunu seçtim" diye bildirir.

## Komutlar

Hepsi vault klasöründe çalışır: `python3 beyin.py <komut>` (Windows: `py -3 beyin.py`).

| Komut | Ne yapar |
|---|---|
| `doctor [--human]` | Sağlık: hook'lar, senkron, sürüm, hafıza hijyeni |
| `context "soru"` | Kaynak bağlantılı açık arama |
| `recap --days 7` | Son işlerin kaynaklı özeti |
| `refleks liste` | Refleksler: durum, kapsam, ağırlık, çekirdeğe aday olanlar |
| `refleks ekle "<kural>" --kapsam <proje\|genel> --tur <tür>` | Refleks aç ya da mevcut reflekse kanıt ekle (`--refleks <id>`) |
| `refleks yukselt <id>` / `refleks dusur <id>` | Çekirdeğe al / çekirdekten çıkar |
| `refleks sozluk [--olustur]` | Proje sözlüğünü göster ya da üret |
| `refleks gocet [--uygula]` | Tek projeye ait kuralları `Kurallar.md`'den reflekse taşı |
| `oturum yaz --session <id> --etiket <etiket> --proje <proje>` | Oturum kartını yaz (gövde stdin'den) |
| `oturum liste` / `oturum derle` | Kartları listele / `Last-Session.md`'yi yeniden üret |
| `yapilacak ekle "<iş>" --proje <proje>` | İşi sonraya kaydet |
| `yapilacak liste` / `yapilacak uygulandi <ID> --sonuc "…"` | Bekleyenler / işi kapat |
| `receipt --event-id <id> --summary "…" --ref <yol> --harness <istemci>` | Oturum sonucunu kaynaklı kaydet |
| `companion-compact [--dry-run]` | Büyüyen Last-Session/Threads'in eskisini arşive taşı (silmez) |
| `preferences [--profile economical\|normal\|manual]` | Otomatik bağlam ve kontrol ayarları |
| `ctx <liste\|unut\|kaydet\|kapat\|aç>` | Yakalananları terminalden yönet |
| `update [--check]` / `rollback` | Güncelle / önceki sürüme dön |

Refleks türleri ve güçleri: `kural` ve `duzeltme` 1,0 · `karar` 0,7 · `tekrar` 0,5 ·
`gozlem` 0,3 · `ters` −1,0 (reflekse karşı çıkan olay).

## Vault'ta ne nerede

```
Vault/
├── AGENTS.md, CLAUDE.md          ajan talimatları (beyin bloğu kurulumla yönetilir)
├── beyin.py                      CLI giriş noktası
├── Yapılacaklar.md               sonraya kaydedilen işler
├── 🔮 850-Companion/              seni tanıyan katman
│   ├── Core.md                   kim olduğun, kalıcı tercihlerin
│   ├── Kurallar.md               her oturumda yüklenen genel kurallar
│   ├── Refleksler/               kapsamlı, kanıtlı davranışlar (+ _sozluk.md)
│   ├── Oturumlar/                oturum kartları
│   ├── Last-Session.md           kartlardan üretilen son oturum özeti (elle düzenleme)
│   ├── Threads.md                açık konular
│   ├── Journal.md                ortak gözlemler ve çıkarımlar
│   └── Arşiv/                    taşınan eski metin (private)
├── knowledge/
│   ├── yakalanan/                otomatik yakalanan kararlar ve kurallar
│   ├── concepts/, connections/   damıtılmış bilgi
│   └── v3/outcomes.md            receipt görünümü (otomatik)
├── projeler/<proje>/             proje notları (sözlüğün kaynağı)
├── receipts/, daily/v3/          oturum sonuç kayıtları (otomatik)
└── .claude/, .codex/, .agents/   istemci hook'ları ve skill'ler (kurulumla yönetilir)
```

Companion klasörünün adı farklı olabilir; beyin mevcut olanı bulur ve ikincisini açmaz.

## Nasıl çalışır

```
olay  ──(tekrar + zaman)──▶  refleks  ──(koşullar değişse de yön aynı)──▶  çekirdek
```

| Hook olayı | Ne olur |
|---|---|
| SessionStart | `Core`, `Kurallar`, `Last-Session`, aktif `Threads`, son `Journal` girişi bütçeyle yüklenir; sığmazsa önce özetlenir (her konunun sonraki adımı, en yeni oturum kartı, satırların ilk cümlesi), sonra kırpılır; genel refleksler ve çekirdeğe aday refleksler bildirilir; bekleyen iş sayısı söylenir |
| UserPromptSubmit | Yakalama çalışır; istemdeki projeler etkinleşir ve refleksleri gelir; ilgili notlar aranır, tekrarlar ve etkin olmayan projelerin notları elenir. "Nerede kalmıştık" sorusu açılışı aynı oturumda tekrarlamaz (companion dosyası değişmediyse); yalnız sorunun konusu aranır |
| PostToolUse | Düzenlenen dosyanın projesi etkinleşir, refleksleri gelir; dosya oturum taslağına girer |
| Stop | Dosya değişip receipt yazılmadıysa bir kez hatırlatır ve oturum taslağını verir |
| PreCompact, SessionEnd | Kuyruk ve oturum kayıtları kapanır |

- **Refleks ağırlığı:** her kanıtın etkisi 60 günde yarılanır; refleks tetiklendikçe tazelenir.
  Ağırlığı 0,25'in altına düşen ve 90 gün tetiklenmeyen refleks söner.
- **Çekirdeğe aday:** en az 3 olumlu kanıt, aralarında en az 30 gün, son 60 günde karşı kanıt yok.
- **Proje etkinliği:** istemde ad ya da takma ad, oturumda dokunulan dosya ya da son 6 tur.
- Arama ve indeks yereldir (SQLite); Markdown kaynak her zaman gerçeğin kendisidir.

Ayrıntı ve gerekçeler: [docs/v5/02-mimari.md](docs/v5/02-mimari.md). Upstream'den nelerin
neden alındığı: [docs/v5/01-avenox-denetimi.md](docs/v5/01-avenox-denetimi.md).

## Gizlilik

- Beyin model çağırmaz ve ağa çıkmaz. Tek istisna, günde en çok bir kez yapılan GitHub sürüm
  kontrolüdür (`preferences --update-notifications off` ile kapanır); kontrol hiçbir veri göndermez.
- `visibility: private` taşıyan notlar otomatik bağlama girmez.
- Adı `Şifreler`, `Kasa`, `Özel`, `Gizli`, `Müşteriler`, `Private` gibi hassasiyet bildiren klasörler
  hiç indekslenmez.
- Yakalamada ve receipt'lerde bilinen sır kalıpları (API anahtarları, token'lar) maskelenir.
- **Bilmen gereken:** ajan istemcin bir bulut modeli kullanıyorsa (Claude, GPT…), bağlama giren not
  parçaları o modelin sağlayıcısına gider. Beyin bunu azaltır (kapsam kapısı, tekrar önleme) ama
  ortadan kaldırmaz. Yerel bir "kapı bekçisi" model yol haritasında.

## Birden çok makine

Vault'u private bir git deposunda tutup her makinede ayrı kurabilirsin; makineye özel durum vault
dışında kaldığı için çakışmaz ([docs/v3/MULTI-MACHINE.md](docs/v3/MULTI-MACHINE.md)). Oturum
kartları ve refleksler küçük ayrı dosyalar olduğu için birleştirmede birbirini ezmez. Vault köküne
şu `.gitattributes` satırını eklemen önerilir:

```
*.md merge=union
```

Çözülmemiş birleştirme işaretleri (`<<<<<<<`) taşıyan bir not, çözülene kadar indekse girmez.

## Güncelleme ve geri alma

```bash
python3 beyin.py update --check   # yeni sürüm var mı, paket doğrulanır, hiçbir şey yazılmaz
python3 beyin.py update           # uygula
python3 beyin.py rollback         # önceki sürüme dön
```

Güncelleme yalnız `YusufDemir0/ctxbrain` GitHub sürümlerini kabul eder ve paketi SHA-256 ile
doğrular. Senin notların, `Core.md`, `Kurallar.md`, refleksler ve tercihler korunur.

## Sorun giderme

| Belirti | Ne yap |
|---|---|
| Ajan geçmişi hatırlamıyor | `beyin.py doctor --human`; istemci "olay görülmedi" ise vault'u o istemcide yeniden aç ve workspace güvenini onayla |
| "Memory hygiene" uyarısı | `beyin.py companion-compact`; hiçbir metin silinmez, arşive taşınır |
| Proje refleksleri gelmiyor | `beyin.py refleks sozluk` ile projenin takma adlarını kontrol et |
| Alakasız notlar geliyor | Sözlük var mı bak; notun `projeler/<proje>/` altında ya da `project:` alanlı olması kapının onu tanımasını sağlar |
| Kurulum "conflict" diyor | Elle değiştirdiğin yönetilen bir dosya var; çıktıdaki yolu kontrol et, notların silinmez |
| Sürüm `3.0.0` görünüyor | Git kopyasından kurulmuş; `beyin.py update` |

## Ölçülen sonuçlar

**Arama** (1. sırada doğru not):

| Ölçüm | avenoxbeyin 3.7.1 | ctxbrain |
|---|---|---|
| Orijinal arama ölçümü, açık arama | %71,9 | %93,8 |
| Kelime uyuşmazlığı ölçümü, açık arama | %0 | %100 |
| Kelime uyuşmazlığı ölçümü, katı mod | %7,7 | %53,8 |

**Bağlam gürültüsü** (gerçek bir vault'un 68 oturumu, 481 tur, 2026-10/11):

| | 4.x | v5 filtreleri (tahmin) |
|---|---|---|
| Kayıt eklenen tur | %85, ortalama 4.434 karakter | — |
| Aynı oturumda tekrar eden kayıt | %35 | 0 |
| Eklenen kayıt | 2.005 | ~961 (−%52) |
| Eklenen karakter | 1,82 milyon | ~0,62 milyon (−%66) |

v5 sütunu, v5 filtrelerinin geçmiş teslimatlara uygulanmasıyla hesaplanmış bir tahmindir; elenen
kayıtların gerçekten gereksiz olduğu ayrıca etiketlenmedi.

**Kurallar:** aynı vault'ta `Kurallar.md` 75 kural, 17,9 bin karakter; göçle 42 kural reflekse
taşındı, açılıştaki kural metni 8,8 bin karaktere indi.

Ölçümleri kendin çalıştır: `scripts/evaluate_v3_search.py`, `scripts/evaluate_v5_reflex.py
[--vault <yol>]`.

## Sınırlar ve yol haritası

- Yakalama sezgiseldir; yanlış ya da eksik yakalama olur (`ctx: unut`, `ctx: kaydet` bunun için).
- Kapsam yalnız sözlükle bulunur; projeyi anmadan anlatılan bir konu ("teslimat bölgeleri")
  projesine bağlanamaz. Bu iş yerel modelin.
- Göç, etiketi proje anmayan kuralları taşımaz; onlar `Kurallar.md`'de kalır.
- Yalnız Linux'ta uçtan uca test edildi; CI Windows ve macOS'ta da çalışır.

Sırada: gerektiğinde devreye giren küçük bir yerel model (kapsam sınıflandırma, benzer refleks,
çelişki bulma), buluta yalnız gerekeni geçiren kapı bekçisi ve oturum yokken de çalışan kısa
"düşünme" turları. Model gelmeden de her yuvanın deterministik bir karşılığı var.

## Geliştirme ve katkı

```bash
python3 -m unittest discover -s tests -p "v[35]_*test.py"     # tüm testler
python3 scripts/evaluate_v3_search.py                          # arama ölçümü
python3 scripts/evaluate_v5_reflex.py                          # refleks tetikleme ölçümü
python3 scripts/build_v3_release.py --version "$(cat VERSION)" --output "release/beyin-v3-$(cat VERSION).zip"
python3 /tam/yol/Vault/beyin.py update --package "release/beyin-v3-$(cat VERSION).zip"
```

Katkı kuralları, mimari sınırlar ve bir değişikliğin nasıl önerileceği:
[CONTRIBUTING.md](CONTRIBUTING.md).

## Köken ve lisans

ctxbrain, [avenoxai/avenoxbeyin](https://github.com/avenoxai/avenoxbeyin) V3.7.1 üzerine kurulmuş
bağımsız bir projedir. Hook, senkron ve kurulum katmanı oradan gelir; Türkçe arama, yakalama,
oturum kartları, yapılacaklar ve v5 refleks modeli ctxbrain'e aittir. Upstream'in sonraki
çalışmaları bir denetmen raporu gibi okunur, fikirler yeniden tasarlanarak alınır. Komut ve
dosya adları (`beyin.py`, `beyin_v3_*`) motorun kökeninden gelir.

MIT. Orijinal lisans ve atıf korunur: [LICENSE](LICENSE),
[docs/upstream/avenoxbeyin-README.md](docs/upstream/avenoxbeyin-README.md).
