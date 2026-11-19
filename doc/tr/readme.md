# Sanal Yapışkan Notlar (Virtual Sticky Notes)

* **Yazar:** Bora Fırlangeç
* **Sürüm:** 1.0.0
* **NVDA Uyumluluğu:** 2023.1 ve üzeri

Sanal Yapışkan Notlar; görme engelli ve ekran okuyucu kullanan kullanıcıların masaüstü uygulamalarında veya web sayfalarında odaklandıkları arayüz kontrollerine (butonlar, yazı alanları, bağlantılar vb.) kişisel **Markdown** notları iliştirmelerini sağlayan bir NVDA eklentisidir.

## Temel Özellikler

* **Akıllı Kontrol Tanıma (Parmak İzi Sistemi):** Pencereler kapatılıp açılsa veya web sayfaları yenilense bile eklediğiniz notlar ilgili kontrole yapışık kalır.
* **Anında Sesli Geri Bildirim:** Üzerinde not bulunan bir kontrole odaklandığınızda kısa bir bildirim sesi duyarsınız ve notun ilk satırı özet olarak seslendirilir.
* **Markdown Desteği:** Notlarınızı başlıklar (`#`), listeler (`-`), bağlantılar (`[metin](adres)`) ve tablolar kullanarak yapılandırılmış şekilde yazabilirsiniz.
* **Sanal Web Görünümü (Browse Mode):** Kayıtlı notları harici bir tarayıcı açmadan doğrudan NVDA'nın sanal imleç penceresinde HTML olarak görüntüleyebilir; `H` (başlık), `L` (liste), `K` (bağlantı) gibi standart web navigasyon tuşlarıyla notun içinde gezinebilirsiniz.
* **Uygulama Bazlı Not Listesi:** Aktif uygulamaya ait tüm notları tek bir listede görüntüleyebilir ve **Enter** tuşuna basarak hızla düzenleyebilirsiniz.
* **Kalıcı Depolama:** Notlarınız NVDA kullanıcı yapılandırma dizininde (`sticky_notes.json`) saklanır; eklentiyi güncelleseniz bile verileriniz kaybolmaz.

## Klavye Kısayolları

Tüm kısayollar **NVDA Menüsü > Tercihler > Girdi Hareketleri > Sanal Yapışkan Notlar** kategorisi altından özelleştirilebilir:

| Kısayol | İşlev |
| :--- | :--- |
| `NVDA + Shift + N` | Odaktaki kontrole yeni yapışkan not ekler veya mevcut notu düzenler. |
| `NVDA + Alt + N` | Aktif uygulamada kayıtlı tüm notların listesini açar (Seçili not üzerinde `Enter` tuşuna basarak düzenleme ekranını açabilirsiniz). |
| `NVDA + Ctrl + N` | Odaktaki kontrolün notunu HTML olarak render eder ve NVDA sanal web arayüzünde açar. |

## Kullanım İpuçları

1. Etiketlenmemiş bir butona veya karmaşık bir web formundaki alana geldiğinizde `NVDA + Shift + N` tuşlarına basın.
2. Açılan çok satırlı metin kutusuna Markdown sözdizimiyle hatırlatıcınızı yazın ve **Kaydet** butonuna basın.
3. Daha sonra aynı kontrole her odaklandığınızda NVDA sizi sesli olarak uyaracaktır.
4. Uzun veya bağlantı içeren bir notu detaylı incelemek için `NVDA + Ctrl + N` tuşlarına basarak sanal web görünümünü açabilir, işiniz bittiğinde `Escape` tuşuyla kapatarak kaldığınız yere dönebilirsiniz.