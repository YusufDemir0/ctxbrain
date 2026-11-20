# Paylaşılan vault yazımları

Aynı checkout’ta çalışan istemciler eski bir dosya kopyasından yola çıkıp birbirlerinin
değişikliklerini ezebiliyordu. Beyin yazıcıları hedef dosyayı okumadan önce vault içindeki
`.beyin-locks/` dizininde dosyaya özgü bir kilit alır. Bu dizin Git tarafından yok sayılır.
Markdown aynı dizindeki geçici bir dosyadan atomik olarak yerleştirilir. CLI kilit için en
fazla iki saniye bekler. Hook, kilit meşgulse o yazımı atlar. Oturum kartı yazımı ve özetin
yeniden derlenmesi aynı özet kilidi altında yapılır. Dosya bazlı kilit, tek bir vault kilidine
göre bağımsız yazımları engellemez. Kilit aynı checkout’taki Beyin işlemleri arasında geçerlidir.
Doğrudan editör yazımları ve ayrı Git checkout’ları kendi çakışma mekanizmalarını kullanır.

`beyin.py preferences --beklenen-dal main` tercihi vault’a kaydedilir. Dal farklıysa veya
HEAD ayrık durumdaysa companion yazan komutlar hata verir. Açılış hook’u bir satır uyarı
ekler ve `doctor` beklenen ve görülen dalı raporlar. Tercihi geri almak için
`beyin.py preferences --beklenen-dal ""` çalıştır. Tercih yoksa dal kontrolü atlanır.

Yeni kayıtlarda köken alanları `harness`, `session` ve biliniyorsa `model` olarak yazılır.
Hook, istemcinin oturum kimliğinden açılıştaki Receipt session değerini üretir. Gövdeyi ve
mevcut frontmatter’ı koruyarak, kökeni henüz olmayan `knowledge/` notlarına alanları ekler.
