# Devir kartı: limit ortasında kalan işi başka istemci sürdürsün (5.0.5)

## Sorun

Oturum kartı ve receipt'i ajan iş sonunda yazar. Claude Code'un kullanım limiti iş ortasında dolunca tur
`Stop` yerine `StopFailure` ile biter; hook bu olayı dinlemediği için vault'a hiçbir iz düşmez. Sonraki istemci
(örnekte Codex) `Last-Session.md`'de yarım işi göremez ve kullanıcının isteğiyle Claude'un ham sohbet kaydını
elle ayrıştırmak zorunda kalır. Ölçüm (bir kullanıcının vault'u, 2026-11-14): aynı hafta üç kez yaşandı.

## Çözüm

`beyin_v3_devir.py`: hook, sohbet kaydının son 4 MB'ından **model çağırmadan** bir devir kartı üretir.

- **Ne zaman:** UserPromptSubmit, Stop, **StopFailure** (`error` alanıyla "kesildi (rate_limit)"), PreCompact,
  SessionEnd her zaman; PostToolUse (artık matcher'sız, tüm araçlar) en fazla 60 sn'de bir.
- **İçerik:** son 5 kullanıcı isteği (sistem eklentileri, skill gövdeleri, AGENTS talimatları ayıklanır), görev
  listesi (Claude `update_plan`/`TodoWrite` artımlarıyla yeniden kurulur, `wrap_up` tamamlar; Codex `update_plan`),
  değişen dosyalar (`Edit`/`Write`/`apply_patch`), son komutlar, son asistan mesajı, kayıt yolu. Sır filtresinden geçer.
- **Yer:** `<companion>/Devir/<sid8>-<istemci>.md`; `sid8` receipt/oturum kartı kimliğiyle aynıdır.
- **Görünürlük:** kesilen ya da görev listesi bitmemiş açık kartlar (7 gün) `Last-Session.md`'nin başında
  "Yarım kalan işler (devir)" bölümünde (en çok 3, 900 karakter). Codex AGENTS.md ile bu dosyayı zaten okur.
- **Devralma:** `beyin.py devir goster <sid> --detay` kartı ve kayıttaki son turları düz metin verir (Claude
  transcript ve Codex rollout).
- **Kapanış:** aynı oturumun `oturum yaz`'ı ya da receipt'i, veya `beyin.py devir kapat <sid>`; kart silinmez,
  `Devir/Arşiv/`'e taşınır.
- **Hook davranışı:** matcher'sız PostToolUse'ta düzenleme dışı araçlar yalnız devir kartını günceller ve hemen
  döner; receipt hatırlatması gibi eski işlemler eskisi gibi yalnız düzenleme araçlarında çalışır. Her adım fail open.

## Alternatifler

- Ajanın ara kart yazması (talimat): limit habersiz gelir, ajan son adımı göremez; yetmez.
- Kaydın tamamını vault'a kopyalamak: büyük, özel ve gürültülü; kart + kayıt yolu yeter.
- Modelle özetlemek: çekirdek model çağırmaz; deterministik ayrıştırma yeterli doğrulukta.

## Geri alma

`BEYIN_V3_NO_DEVIR=1` devir yazımını kapatır. Sürüm geri alınırsa `Devir/` klasörü düz Markdown olarak kalır.
