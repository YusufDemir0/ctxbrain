# ctxbrain v5 mimarisi: anı defterinden beyne

## İki yapı

- **Beyin** bu depodur: motor, hook'lar, CLI, skill'ler. Public olabilir; içinde hiçbir
  kullanıcıya ait bilgi yoktur. Gelişimini kullanıcı (kod katkısıyla) sağlar.
- **Vault** kullanıcının Markdown klasörüdür ve her zaman private'tır. Kullanıcı hakkındaki her
  çıkarım vault'tan gelir. Kullanıcının yaşadıkları vault'u değiştirir, beyin vault'u inceler ve
  geliştirir.

Beyin bugün tamamen yereldir ve model çağırmaz. İleride, gerektiğinde devreye giren küçük bir
yerel model (7/24 açık değil) aşağıdaki "model yuvası" noktalarına bağlanır; her yuvanın
deterministik bir yedeği vardır, yani model olmadan da sistem çalışır.

## Kullanıcıyı tanımak ne demek

Bugünkü beyin kullanıcıyı sabit cümlelerle biliyor ("şu projede akışa dokunma"). Bir insanı
tanımak ise yeni bir durumda "o burada ne düşünür?" sorusuna tek cevap değil, **bağlama göre
ağırlıklandırılmış bir olasılık yelpazesi** üretebilmektir. Vault büyüdükçe bu yelpaze hem
genişler (daha çok durum kapsanır) hem keskinleşir (kanıt biriktikçe ağırlıklar ayrışır).

v5'in veri modeli bu yelpazeyi açıkça tutar:

```
olay  ──(tekrar + zaman)──▶  refleks  ──(koşullar değişse de yön aynı)──▶  çekirdek
```

| Katman | Nedir | Nereden gelir | Ne zaman yüklenir | Ömrü |
|---|---|---|---|---|
| Olay | Kullanıcının bir kararı, kuralı ya da düzeltmesi; tek bir an | Otomatik yakalama (`knowledge/yakalanan/`), ajanın kaydettiği düzeltme | Yüklenmez; aranır | Kısa |
| Refleks | Aynı yöne giden olaylardan oluşan, kapsamı olan davranış | Olayların birikmesi | Yalnız kapsamı tetiklenince | Kullanılmazsa söner |
| Çekirdek | Koşullar değiştiği halde yönü değişmeyen refleks | Refleksin yükselmesi | Her zaman (kapsamı genelse) | Uzun, evrimi yavaş |

### Refleks dosyası

Her refleks vault'ta `<companion>/Refleksler/<id>.md` dosyasıdır. Küçük dosyalar git
birleştirmesinde çakışmaz ve Obsidian'da elle düzenlenebilir.

```markdown
---
id: ermay-akisa-dokunma
durum: aktif
kapsam: [ermay-crm-erp]
tetik: [akış, cms]
---
Tasarım incelemesinde sistemin iş akışına değişiklik önerme; akışın arayüzde nasıl
uygulandığını incele.

## Kanıt
- 2026-10-04 · kural · Tasarım incelemelerinde akışa dokunma (Kurallar.md)
- 2026-10-21 · düzeltme · Sevkiyat ekranında akış önerisi geri çevrildi
```

- `durum`: `aktif` ya da `cekirdek`. Sönmüşlük dosyaya yazılmaz, her seferinde hesaplanır.
- `kapsam`: proje anahtarları; boşsa refleks geneldir.
- `tetik`: kapsamdan bağımsız, istemde geçince tetikleyen ek sözcükler.
- `## Kanıt`: her satır bir olay: `tarih · tür · metin`. Türler ve güçleri:
  `kural` 1,0 · `düzeltme` 1,0 · `karar` 0,7 · `tekrar` 0,5 · `gözlem` 0,3 · `ters` −1,0
  (refleksle çelişen olay).

### Ağırlık, sönme ve yükselme

Her kanıtın etkisi zamanla yarılanır (yarı ömür 60 gün). Refleksin ağırlığı:

```
ağırlık = Σ güç(e) · 0,5 ^ (yaş(e) / 60 gün)      (yaş, en son tetiklenmeyle tazelenir)
```

- **Sönme:** çekirdek olmayan bir refleks, ağırlığı 0,25'in altına düşer ve 90 gün
  tetiklenmezse hatıra sayılır: yüklenmez, aranabilir kalır, dosyası silinmez.
- **Yükselme (çekirdeğe aday):** en az 3 olumlu kanıt, ilk ve son kanıt arasında en az 30 gün,
  en az 2 farklı bağlamda (ayrı gün ya da kapsam) görülmüş olması ve son 60 günde `ters` kanıt
  olmaması. Bu, "ilk söyleyişte çekirdek olmaz; zaman geçip koşullar değişse de istek aynı
  kalıyorsa çekirdeğe girer" ilkesinin ölçülebilir hali.
- Yükselme geri alınabilir bir işlemdir. Beyin adayı oturum başında bildirir; ajan
  `beyin.py refleks yukselt <id>` ile uygular ve kullanıcıya hangi seçeneği seçtiğini söyler.

Sayılar başlangıç değerleridir; ölçüm setiyle ayarlanır.

### Tetikleme

Refleks, kapsamı **o an etkin** olduğunda yüklenir. Etkin kapsam üç kaynaktan bulunur:

1. **İstem:** proje sözlüğündeki ad ya da takma adlardan biri istemde geçer.
2. **Dosyalar:** oturumda düzenlenen dosyanın yolu bir projenin klasörüne ya da adına işaret eder
   (PostToolUse).
3. **Oturum hafızası:** bir kez etkinleşen kapsam, sonraki 6 tur boyunca yeniden anılmasa da
   etkin kalır.

Proje sözlüğü `<companion>/Refleksler/_sozluk.md` dosyasıdır. İlk hali vault'taki proje
klasörlerinin adlarından üretilir, kullanıcı takma ad ekler:

```markdown
- ermay-crm-erp: ermay, erp, ermayweb, mobilya, sevkiyat
- ya-oyle-olsaydi: zombi, meteor, video, bereli martı
```

Her refleks oturumda bir kez söylenir; dosyası değişirse ya da bağlam sıkıştırılırsa yeniden.
Açılışta yalnız genel refleksler ve çekirdek yüklenir; proje refleksleri tetiklenince gelir.

Upstream'in proje kuralları çalışma klasörüne bakar; vault kökünde açılan oturumda bu hiç
çalışmaz. v5'te tetiğin kaynağı istem, dosya ve oturumdur.

### Çatışma: olasılık yelpazesi

Aynı bağlamda farklı yönlere giden iki refleks tetiklenirse ikisi de ağırlıklarıyla yüklenir.
Ajan şu ilkeyle davranır: en olası olanı önerir ve alternatifi söyler. Geri alınamaz işte sorar;
geri alınabilir işte ilerler ama "şu seçeneklerden şunu seçtim" diye bildirir.

### Olay kaydı

- Otomatik yakalama (mevcut `beyin_v3_capture`) her istemde karar ve kural cümlelerini olay
  olarak yazar. Ajanın hatırlamasına bağlı değildir. Aynı turda her cümle, kapsamdaki
  reflekslerle karşılaştırılır (kök örtüşmesi):
  - **Kesin** (en az 0,6 kapsama ve 5 ortak kök): refleksin kendisine `tekrar` kanıtı eklenir.
  - **Olası** (0,35 ve 4): ajana öneri olarak gider; ajan doğrularsa kanıtı ekler.
  - **Hiçbir reflekse benzemeyen kural cümlesi:** "refleks adayı" önerisi.

  Öneriler o oturumun kapanış taslağında ve bir sonraki oturum başında (en çok 3, her biri bir
  kez) söylenir. Gerçek bir vault'un 43 yakalamasında kesin eşleşme 1/1, olası eşleşme 4/4
  doğruydu; adayların bir kısmı kural değil o anki iş talimatıydı, bu yüzden adaylar yalnız
  öneridir. Bu ayrım, model yuvasının ilk işidir.
- Kullanıcı ajanı düzelttiğinde ajan `beyin.py refleks ekle "<kural>" --kapsam <proje|genel>
  --tur düzeltme` çalıştırır. Komut benzer refleksleri gösterir; aynı anlamdaysa ajan yeni refleks
  açmak yerine `--refleks <id>` ile mevcut olana kanıt ekler. Böylece aynı kural ikinci kez
  söylendiğinde yeni satır değil, daha güçlü bir refleks olur.

### Göç

`beyin.py refleks gocet` mevcut `Kurallar.md`'yi okur ve her kuralı sözlükle eşleştirir. Tek
projeye ait kurallar kendi refleks dosyalarına taşınır (kanıtı kuralın orijinal tarihiyle);
genel kurallar `Kurallar.md`'de kalır. Varsayılan kuru çalıştırmadır, `--uygula` önce dosyanın
tam metnini arşive yedekler. Hiçbir şey silinmez.

### Açılış (5.0.3)

Açılış, companion dosyalarını istemcinin kesme sınırının altında (Claude Code için 10.000
karakter) taşır. Gerçek bir vault'ta kaynaklar 17,9 bin karakterdi; 9.000 bütçede baştan kırpma
`Threads`'in 9 konusundan yalnız ilk ikisini, `Core`'un ise kimlik ve aktif alanlarını verip
kalıcı tercihlerini düşürüyordu. Artık bir kaynak sığmazsa, hiçbiri kırpılmadan önce üçü
özetlenir:

- `Threads`: her konunun başlığı ile "Sonraki adım" ve "Açık" satırları (yoksa son satırı).
- `Last-Session`: en yeni kart tam, eskiler başlık ve ilk satır; eski kart listesi çıkar.
- `Core`: her satırın ilk cümlesi; aktif iş bölümü (Threads zaten taşır) kalın etiketlerine iner.

Aynı vault'ta açılış 9.000 karakterde kırpmasız sığdı: 9 konunun hepsi ve tüm tercihler.

"Nerede kalmıştık" türü bir soru açılışı yeniden basardı; oturumun ilk istemi çoğu zaman bu
olduğundan neredeyse her oturum aynı 9 bin karakteri iki kez taşıyordu. Açılış, companion
dosyalarının parmak izini oturum kaydına yazar; aynı oturumda soru gelirse ve dosyalar
değişmediyse açılış tekrarlanmaz. Sorunun aramaya giden kısmı yalnız konusudur ("zombi'de
nerede kaldık" → "zombi"); konusu yoksa arama yapılmaz.

## Model yuvası

Model gelene kadar her yuvanın deterministik bir karşılığı var:

| Yuva | Bugün | Model gelince |
|---|---|---|
| Benzer refleks bulma | Kök sözcük örtüşmesi | Anlam benzerliği |
| Kapsam sınıflandırma | Sözlük eşleşmesi | Bağlamdan çıkarım |
| Çelişki bulma | `ters` kanıtı elle | Olaylar arasında otomatik |
| Kapı bekçisi | `visibility: private`, hassas klasör adları | Buluta yalnız gerekeni geçiren ön işleme |
| Oturumsuz düşünme | Yok | Zamanlanmış, kısa süreli toplu değerlendirme |

## Ölçüm

"Hatalar beynin sınavıdır." Her düzeltme olayı bir test vakasına dönüşebilir: durum yeniden
verildiğinde doğru refleks tetikleniyor mu? `scripts/evaluate_v5_reflex.py`:

- Tetikleme isabeti: etiketli istemlerde doğru kapsam etkinleşiyor mu, yanlış kapsam
  etkinleşmiyor mu.
- Açılış maliyeti: göçten önce ve sonra açılıştaki kural karakteri.

Depodaki ölçüm seti sentetiktir; kişisel vault'ta aynı betik `--vault` ile çalışır ve sonucu
yalnız yerelde kalır.

## Fazlar

1. **Refleks çekirdeği:** refleks deposu, ağırlık modeli, tetikleme (istem, dosya, oturum), hook
   bağlantısı, `refleks` komutları, göç aracı, testler.
2. **Bağlam gürültüsü ve kapanış:** oturum içi tekrar önleme varsayılan açık, kısa sayı
   yanıtları, ölçüm seti; Stop'ta oturum kartı taslağı.
3. **Upstream'den alınanlar:** sentetik turlar, hassas klasör adları, senkron gecikmesinde eski
   indeks, çakışma işaretleri ([01-avenox-denetimi.md](01-avenox-denetimi.md) §4).
4. **Belgeler ve sürüm:** ajanın tek okumada sistemi anlayacağı README, katkı rehberi, 5.0.0.
5. **Sonra:** model yuvası, oturumsuz düşünme, kapı bekçisi.
