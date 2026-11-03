# Avenox 3.8–3.12 denetimi: ne bulmuşlar, nasıl çözmüşler, biz ne yaparız

ctxbrain, avenoxbeyin 3.7.1 üzerine kuruldu. O tarihten sonra upstream 904 commit ve beş
sürüm (3.8.0 → 3.12.0, son commit 2026-10-29) çıkardı; ~20 bin satır değişti. Bu belge o
çalışmayı bir **denetmen raporu** gibi okur: topluluk bizim fark etmediğimiz hangi sorunları
bulmuş, nasıl ve neden öyle çözmüş, biz bunu nasıl daha iyi yapabiliriz.

Kaynaklar: GitHub sürüm notları (v3.8.0–v3.12.0), `upstream/main` kodu (36f8a75) ve RFC
[avenoxai/avenoxbeyin#368](https://github.com/avenoxai/avenoxbeyin/issues/368). Kod
kopyalanmaz; fikirler anlaşılır, yeniden tasarlanır ve kendi mimarimize göre yazılır.

## 0. Önce bizim ölçtüğümüz

Gerçek kullanımdaki bir vault'ta (2026-11-03):

| Ölçüm | Değer | Anlamı |
|---|---|---|
| `Kurallar.md` | 75 kural, 17.899 karakter | Açılışta ~16 bin karakteri kırpılıyor |
| Kural dağılımı | 13 genel (2,9 bin), 62 tek projeye ait (14,7 bin) | Açılıştaki kural metninin ~%84'ü o anki işle ilgisiz |
| Tur başı bağlam | Neredeyse her istemde ~4,4 bin karakter | Konu dışı sorularda da başka projelerin notları geliyor |
| Receipt kapsamı | %41, son 7 gün %16 | Oturum kapanışı ajanın disiplinine bağlı ve tutmuyor |
| Otomatik yakalama | 17 gün, 43 kayıt (31 karar, 12 kural) | Ham olay akışı zaten var ama hiçbir şey ondan öğrenmiyor |

Bu tablo raporun pusulası: upstream'in her iyileştirmesini "bu sorunlardan birini kapatıyor mu,
beyni kayıt defterine mi yoksa kullanıcıyı tanımaya mı yaklaştırıyor" diye tartıyoruz.

## 1. Upstream'in kendi teşhisi (RFC #368)

Upstream 16 Ekim'de bir vizyon RFC'si yazdı. Hedef: "Jarvis benzeri tek bir kişisel Beyin".
En yüksek öncelikli sorun olarak **konuşmalardan kalıcı öğrenme**yi koydular:

- Last-Session ve Threads güncelleniyor, ama knowledge ve notlar güncellenmiyor.
- Kök neden: semantik öğrenim tespiti tamamen aktif ajana bırakılmış. Hook yalnız receipt'teki
  `Öğrenilen:` etiketini ayrıştırıyor; `Öğrenilen: yok` yazmak her şeyi susturuyor.
- Önerdikleri hat: konuşma → öğrenim adayı → sınıflandırma → tekrar ayıklama → doğrulama →
  çalışma alanına yönlendirme → birleştirme → kalıcılaştırma → okuyarak doğrulama.
- İlkeleri: "Write less, learn better"; her mesaj için ağır model çağrısı yok; kullanıcı beyanı,
  kaynaklı bilgi ve model çıkarımı aynı güvende değil.

**Yorumumuz:** Teşhis doğru ve bizimkiyle örtüşüyor. Ama önerilen hat hâlâ *not üretmeye*
odaklı: hedef daha iyi knowledge dosyaları. Bizim hedefimiz başka: kullanıcının nasıl düşündüğünü
ve neye nasıl tepki verdiğini zamanla öğrenen bir yapı. Not üretmek bunun yan ürünü olabilir,
özü olamaz. Ayrıca upstream'in şu ana kadar *uyguladığı* kısım (aşağıda §2.1) hâlâ ajanın
beyanına dayanıyor; kök nedeni tam kapatmıyor.

## 2. İyileştirmeler tek tek

Her madde: **Sorun · Nasıl · Neden · Yorum · Karar.** Karar değerleri: *al* (fikri olduğu gibi
uygula), *uyarla* (fikri al, kendi tasarımımızla yaz), *sonra* (doğru ama şimdi değil),
*alma* (yönümüz değil).

### 2.1 Hafıza ve öğrenme

**Öğrenim aday defteri (#395) ve "Öğrenilen: yok" kaçağı (#369)**
- Sorun: Ajan receipt'e `Öğrenilen: yok` yazınca öğrenim hatırlatması susuyordu; değişmemiş eski
  bir notu refs'e koymak da yetiyordu.
- Nasıl: `beyin.py learn --candidate "..." --source not.md` adayı runtime'daki
  `learning-state.jsonl`'a yazar. Aday doğrudan bilgi notuna dönüşmez. Dosya düzenlenmiş bir
  oturumda `Öğrenilen: yok` bir kez sorgulanır; yalnız *bu düzenleme penceresinde* yazılan aday
  ya da değişen not gereği karşılar.
- Neden: Öğrenimi hemen kalıcı nota yazmak not kirliliği üretiyor; hiç yazmamak bilgi kaybı.
  Ara bir "aday" durumu ikisinin arasını açıyor.
- Yorum: Ara durum fikri çok değerli; bizim olay → refleks → çekirdek katmanlarının ilk basamağı
  tam olarak bu. Ama adayı yine ajan beyan ediyor. Biz bunu ajana bırakmak zorunda değiliz:
  `beyin_v3_capture` her istemde kullanıcının karar ve kural cümlelerini zaten yakalıyor
  (17 günde 43 olay). Olay akışı ajanın hatırlamasına bağlı değil.
- Karar: **uyarla.** Aday defteri yerine kullanıcı kaynaklı olay defteri; ajanın beyanı ikinci
  kaynak.

**Hafıza denetçisi (#388, #372)**
- Sorun: Benzer notlar çoğalıyor, eski durumla yenisi çelişiyor, kimse fark etmiyor.
- Nasıl: `beyin.py audit` notları kök sözcük örtüşmesiyle (containment + Jaccard, eşik 0,60)
  karşılaştırır, zıt durum çiftlerini (açık/kapalı gibi) zamana göre arar. Salt okunur, model yok.
- Neden: Önce görünür kılmak, sonra düzeltmek; yerel ve deterministik kalmak.
- Yorum: Sözcük örtüşmesi aynı şeyi farklı kelimelerle söyleyen iki notu kaçırır. Bu, ileride
  devreye girecek yerel modelin doğal işi. Şimdilik sözcük düzeyi yeterli bir başlangıç.
- Karar: **sonra.** Çekirdek oluşturma işinde aynı benzerlik ölçüsüne ihtiyacımız olacak; orada
  ortak bir benzerlik fonksiyonu yazıp denetçiyi onun üstüne kurarız.

**Karar defteri (#324)**
- Sorun: `companion-compact` eski oturum kartlarını arşive taşıyınca içlerindeki kararlar
  bağlamdan da düşüyordu.
- Nasıl: Arşive giden kartlardaki `**Karar:**` satırları `Kararlar.md`'ye kopyalanır; bu dosya
  aranır ve bağlama girer.
- Neden: Oturum kartı kısa ömürlü, karar uzun ömürlü; ikisinin ömrü ayrılmalı.
- Yorum: Doğru içgörü: **bilginin ömrü türüne göre değişir.** Bizim tasarımda bu genelleşir:
  olayın ömrü kısa, refleksin orta, çekirdeğin uzun.
- Karar: **uyarla** (katman tasarımına içkin).

**Kişi notları (#314, #391)**
- Nasıl: Kişi başına tek not (`kind: person`, `aliases`); kullanıcının söylediği "Beyan",
  ajanın tahmini "Çıkarım (onay bekliyor)" bölümüne. Hassas bilgi yazılmaz.
- Yorum: Beyan ile çıkarımı aynı notta ayrı bölümlerde tutmak, bizim "çıkarım hipotezdir"
  ilkemizle aynı. Kişi kartları kullanıcıyı tanımanın bir boyutu (çevresi).
- Karar: **sonra.**

**`supersedes` ve emekli durumlar (#201, #206), reddedilmiş çıkarım (#252)**
- Nasıl: `supersedes` yalnız kesin kimlik, yol ya da bağlantıyla eşleşir (alt dizeyle asla).
  `status: archived/eski/emekli…` notlar varsayılan bağlama girmez.
- Yorum: Unutmanın en ilkel biçimi: elle emekliye ayırmak. Bizde unutma zamanla ve kullanımla
  kendiliğinden olacak; elle emeklilik yine de geçerli bir çıkış kapısı olarak kalmalı.
- Karar: **al** (küçük, güvenli).

### 2.2 Kurallar

**Uzun Kurallar.md başını kaybetmiyor (#379, 31a261a, adb820b)**
- Sorun: ~40 bin karakteri aşan dosya baştan kesiliyordu; kural sayacı yanlış sayıyordu.
- Nasıl: Bütçeyi aşan dosyanın başı ve sonu tutulur; kesim kural sınırına oturtulur; `doctor`
  açılışta kuralların kaçta kaçının göründüğünü söyler.
- Yorum: Doğru ama yara bandı. Dosya büyüdükçe ortadaki kurallar yine görünmez; hangisinin
  görüneceğini konum (baş/son) belirliyor, önem değil.
- Karar: **alma.** Sorunu kökten kaldırıyoruz (§3).

**Proje kuralları kendi dosyasına (#376, #387, #333)**
- Sorun: Tek projeye ait kurallar global dosyayı şişiriyor.
- Nasıl: Proje kuralı `projects/<proje>/Kurallar.md`'ye gider, global dosyada
  `[kapsam: <proje>]` etiketli tek satır işaretçi kalır. Aktif proje, çalışma klasöründen
  (`cwd` → `.beyin-projects.json` ya da `projeler/` klasörleri) veya istemde adı açıkça geçerse
  bulunur; başka projelerin etiketli kuralları elenir.
- Neden: Kural ancak ilgili olduğunda yüklenmeli.
- Yorum: Fikir tam isabet; bizim **refleks** tanımımızın ilk hali. Ama tetik zayıf:
  - Vault kökünde açılan oturumda `cwd` her zaman vault köküdür, proje hiç çözülmez. Bu, bizim
    kullanım biçimimiz (oturum vault'ta, proje klasörü eklenir).
  - İstemde proje adı geçmezse ("şu sevkiyat ekranı" gibi) eşleşme olmaz.
  - Kapsamı ajan ya da kullanıcı elle etiketler.
- Bizim tetiklerimiz: istemin içeriği (proje adı, takma adı, proje sözlüğü), oturumda dokunulan
  dosya yolları (PostToolUse), ve aynı oturumun önceki turlarında çözülmüş proje (oturum hafızası).
- Karar: **uyarla.** Kapsam fikri alınır; tetikleme bizim olur.

**Açılış taban payları (#329)**
- Nasıl: Kurallar 0,40, Last-Session 0,15, Threads 0,12, Core 0,08; kalan %25 diğerlerine.
- Yorum: Sabit oranlar ilgiyi değil türü ödüllendirir. Kurallar ilgili refleks kümesine inince
  bu dağılım kendiliğinden rahatlar.
- Karar: **sonra** (yeni yapı oturunca yeniden ölçülür).

### 2.3 Bağlam ve arama

**Oturum içi tekrar önleme (#364, #377)**
- Sorun: Aynı not aynı oturumda her turda yeniden gönderiliyor.
- Nasıl: Oturum başına teslim defteri (`session-delivery/`): kayıt kimliği + kaynak hash + metin
  penceresi aynıysa tekrar gönderilmez; dosya değişirse yeniden gelir. Sıkıştırmada ve oturum
  sonunda sıfırlanır. Varsayılan kapalı. Ölçümleri: ikinci tur 1.346 → 795 karakter.
- Neden: Model zaten gördüğü notu ikinci kez okumamalı; bütçe yeni bilgiye kalmalı.
- Yorum: Sağlam, ölçülmüş bir fikir. Varsayılanı kapalı bırakmaları geri dönüş uyumluluğu yüzünden.
- Karar: **al**, bizde varsayılan açık.

**Arama düzeltmeleri**
- BM25 (#214): gevşek aramada uzun özet notları konuyu anlatan notun önüne geçmesin.
- Kısa sayı yanıtları (#357): "1", "2." gibi seçim cevapları ilgisiz not getirmesin.
- Ad/başlık tam eşleşmesi önde (#305).
- Yazım hatası toleransı (a2ccb3d), Türkçe çekim ve ünlü düşmesi (#430).
- Yorum: ctxbrain Türkçe aramayı (fiil kökleri, ünsüz yumuşaması, EN-TR sözlüğü) kendi yolunda
  geliştirdi; upstream'in Türkçe düzeltmeleri bizimkiyle çakışabilir. Kısa sayı yanıtı ve ad
  eşleşmesi bizde eksik ve doğrudan "alakasız bağlam" sorununa dokunuyor.
- Karar: kısa sayı yanıtı ve ad eşleşmesi **al**; BM25 ve yazım hatası **uyarla** (kendi
  ölçüm setimizle); Türkçe çekim **alma** (bizimki ölçülmüş ve daha geniş).

**Senkron gecikince arama düşmüyor (#365, #400)**
- Nasıl: Senkron 1,5 sn'de bitmezse önceki indeksten bağlam kurulur, bunu söyleyen bir satırla.
- Karar: **al** (sağlamlık, maliyetsiz).

**İndeks dışı klasörler ve hassas adlar (#275, #303, #337)**
- Nasıl: Kullanıcı `--index-exclude-dir` ile klasör dışlar; adı `Kasa`, `Şifreler`, `Özel`,
  `Private` gibi olan klasörler hiç indekslenmez; BOM'lu dosyada frontmatter okunur.
- Yorum: Hassas ad kuralı bizim gelecekteki "kapı bekçisi"nin ilk, ucuz katmanı.
- Karar: **al.**

### 2.4 Oturum kapanışı ve receipt

**Sentetik turlar (#378), düzenleme tespiti (#370, #327), kapsam penceresi (#212)**
- Sorun: Bildirim, başka ajanın mesajı, öneri çatalı gibi kullanıcının yazmadığı turlar sahte
  "receipt eksik" üretiyordu; Bash ile yapılan düzenlemeler görülmüyordu.
- Nasıl: Bu turlar `synthetic` işaretlenir; `note-create`/`task-update` Bash'ten çalışınca da
  düzenleme penceresi açılır; uyarı yalnız son 7 güne bakar.
- Yorum: Ölçümü düzeltiyor ama davranışı değil. Kapsamı düşük olan ajanı daha doğru *saymak*,
  ona daha çok yazdırmaz.
- Bizim yaklaşım: kapanışın ham maddesini hook kendisi toplasın (dokunulan dosyalar, yakalanan
  kararlar, oturum kartı taslağı); ajan yalnız onaylasın ya da düzeltsin.
- Karar: sentetik tur **al**; kapanış **uyarla.**

**Receipt bayrakları (#202), dış bağlantı (#322)**
- `--event-id --summary --ref` ve `--link URL`. Karar: **al** (ajan için daha az hata).

**Sohbet izi (chat_trace)**
- Nasıl: İsteğe bağlı; mesaj metnini okumaz, yalnız sayaç tutar ve açık yazım ister.
- Karar: **alma.** Bizim olay akışımız (yakalama) bu ihtiyacı daha doğrudan karşılıyor.

### 2.5 Çoklu cihaz ve sağlamlık

- Çakışma işaretli dosyalar indekslenmez (#205), senkron servisi kopyaları (#291), receipt
  ayrışması (#239), başka işletim sisteminden gelen state yolu (#249, #292), cihazlar arası
  oturum farkındalığı (#298), hash kilitli `note-read`/`note-edit` (#412), süreçler arası
  sıkıştırma kilidi (#193, #198).
- Yorum: Bunlar gerçek çoklu cihaz kullanımında yaşanmış sorunların çözümleri; bizim vault da
  PC, bulut ve mobil oturumlarla git üzerinden eşitleniyor. `note-edit`'in hash kilidi iki ajanın
  aynı notu ezmesini önlüyor: bizde oturum kartlarıyla kısmen çözdüğümüz sorunun genel hali.
- Karar: çakışma işaretleri, senkron kopyaları ve state yolu **al**; `note-edit` **sonra**.

### 2.6 Bakım araçları

- `triage` (#328): gelen kutusu, bayat görevler, haftalık bilgi özeti. Salt okunur.
- `scheduled-check` (#290): kullanıcının kurduğu zamanlayıcı için sync + doctor.
- `hook-done` defteri (#306), `hook-reconcile` (#297).
- Yorum: `scheduled-check` deseni (servis kurmaz, model çağırmaz, sonucu bir sonraki oturumda
  tek satır söyler), ileride "oturum yokken de çalışan beyin"in güvenli ilk adımı.
- Karar: `scheduled-check` deseni **uyarla** (sonraki aşama); diğerleri **sonra.**

### 2.7 Kapsam dışı

`yakala` (7.600 satırlık kısayol/yakalama sistemi: tarayıcı, ekran görüntüsü, işletim sistemi
dinleyicileri), `ingest-server`, Kiro, Hermes A2A ayarları. Bunlar ayrı bir ürün yönü; beynin
özüne dokunmuyor. **alma** (şimdilik).

## 3. Sentez: upstream'den öğrendiğimiz üç ilke

1. **Bilginin ömrü türüne göre değişir** (karar defteri, oturum kartı ayrımı).
2. **Kural ancak ilgili olduğunda yüklenmeli** (proje kapsamı).
3. **Kalıcılaşmadan önce bir ara durum gerekir** (öğrenim adayı).

Upstream bu üçünü ayrı ayrı, farklı modüllerde buldu. Biz bunları tek bir modelde birleştiriyoruz:

```
olay  ──(tekrar + zaman)──▶  refleks  ──(koşullar değişse de yön aynı)──▶  çekirdek
  │                            │                                             │
kısa ömür                   bağlamında tetiklenir                       her zaman yüklenir
kullanıcı kaynaklı          kanıt ağırlıklı                             az ve öz
                            kullanılmazsa söner                         evrimi yavaş
```

Bu modelin ayrıntısı, ölçütleri ve uygulama sırası: [02-mimari.md](02-mimari.md).

## 4. Özet karar tablosu

| İyileştirme | Karar | Gerekçe |
|---|---|---|
| Oturum içi tekrar önleme | al (varsayılan açık) | Alakasız/tekrar bağlamı doğrudan azaltır |
| Kısa sayı yanıtı, ad eşleşmesi | al | Alakasız bağlam |
| Senkron gecikince eski indeks | al | Sağlamlık |
| Hassas klasör adları, BOM | al | Kapı bekçisinin ilk katmanı |
| Sentetik tur, receipt bayrakları | al | Doğru ölçüm, daha az ajan hatası |
| Çakışma işaretleri, senkron kopyaları | al | Çoklu cihaz |
| Öğrenim adayı | uyarla → olay defteri | Kaynak ajan değil kullanıcı |
| Proje kuralları | uyarla → refleks | Tetik istem, dosya ve oturumdan |
| Karar defteri | uyarla → katman ömrü | Genel ilke |
| Kapanış | uyarla → hook taslak üretir | Kapsam %16 sorunu |
| BM25, yazım hatası | uyarla | Kendi ölçüm setimizle |
| Uzun Kurallar baş/son | alma | Kökten çözülüyor |
| Türkçe çekim düzeltmeleri | alma | Bizimki daha geniş |
| Sohbet izi | alma | Olay akışı karşılıyor |
| Denetçi, kişi notları, triage, note-edit | sonra | Önce çekirdek model |
| yakala, ingest-server, Kiro | alma | Ayrı ürün yönü |
