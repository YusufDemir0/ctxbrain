# ctxbrain: ajan kurulum rehberi

Bu dosya, kullanicinin su istegini yerine getirmek icin kurulum tarifidir:

> Bu klasore ctxbrain kur. Mevcut kurulum varsa notlarimi koruyarak guncelle.
> Sonunda ornek bir bilgiyi kaydedip yeni oturumda geri okuyarak birlikte dogrulayalim.

## Degismez kurallar

1. Kurulum hedefi, kullanicinin bu istegi verdigi mevcut vault/workspace klasorudur.
2. Kullanici notlarini silme, tasima, yeniden adlandirma veya `git reset` ile ezme.
3. Kaynak yalniz `YusufDemir0/ctxbrain` deposudur. Ucuncu taraf paketleri veya orijinal
   avenoxbeyin surumlerini kullanma; ctxbrain onlarla ayni dosyalari farkli icerikle yazar.
4. Ham notlari, kimlik bilgilerini veya gizli degerleri terminal ciktisina, sohbete ya da
   dis servislere dokme.
5. Kurulum tamamlanmadan basarili deme. Installer cikis kodunu, `.beyin-version` damgasini
   ve `beyin.py doctor` sonucunu kontrol et.

## 1. Python'u bul

Python 3.11 veya daha yenisi gerekir: macOS/Linux'ta `python3`, Windows'ta `py -3`.
Surumu gercekten calistirip kontrol et. Uygun Python yoksa kullaniciya kurmasini soyle;
rastgele indirme siteleri kullanma.

## 2. Kaynagi al

Depo private olabilir. Kullanicinin oturum acmis `gh` veya git kimligiyle, vault DISINDA
gecici bir klasore klonla:

```sh
gh repo clone YusufDemir0/ctxbrain "<gecici-klasor>/ctxbrain"
```

Klon basarisizsa kullanicidan erisim veya yerel bir kopya yolu iste; baska kaynaga gecme.

## 3. Kur

```sh
python3 "<gecici-klasor>/ctxbrain/scripts/install_v3.py" --vault "<vault-yolu>" --plan
python3 "<gecici-klasor>/ctxbrain/scripts/install_v3.py" --vault "<vault-yolu>"
```

Once `--plan` ciktisini oku: yalniz vault icine yazmali, `retire` veya `preserve` listesinde
kullanici dosyasi varsa dur ve kullaniciya sor. Kurulum ciktisinda `status: installed`,
`companion` ve `skills.conflicts` alanlarini kontrol et. Mevcut bir kurulumu guncellerken
notlarini silme; installer yedek ve geri alma kurallarini kendisi uygular.

## 4. Saglik kontrolu

Vault klasorunde:

```sh
python3 beyin.py doctor
python3 beyin.py preferences
```

`needs_attention` gorursen nedenini kullaniciya acikla.

## 5. Kullaniciya birak

- Istemcinin klasor, workspace veya hook guven incelemesini kullanici kendisi onaylar;
  bunu onun yerine yapma ve onaylanmis gibi davranma.
- Yeni bir oturum acilmadan hafizanin calistigini soyleme. Kullaniciya su testi oner:
  bir karar cumlesi yazsin ("Bundan sonra testleri Ingilizce yazalim."), oturumu kapatsin,
  yeni bir oturumda `ctx: liste` yazsin. Kayit gorunmeden "dogrulandi" deme.
- Ilk oturum icin: "Beyin skill'ini kullan. Beni tanimak icin kisa sorular sor." Skill
  `.agents/skills/beyin/SKILL.md` altindadir.
- Yakalananlari yonetmek: `ctx: liste`, `ctx: unut son`, `ctx: kaydet <cumle>`,
  `ctx: kapat` / `ctx: ac`.

Gecici klonu kurulumdan sonra silebilirsin; vault onu kullanmaz.
