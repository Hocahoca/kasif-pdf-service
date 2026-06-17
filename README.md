# Kaşif PDF Kazıma Servisi

Bu servis, PDF dosyalarından temiz metin çıkarır. Hem normal dijital PDF'leri
hem de taranmış (görüntü) sayfaları Arapça+Türkçe destekli OCR ile okuyabilir.

## Dosyalar
- `main.py` — servisin tüm kodu
- `requirements.txt` — gerekli Python kütüphaneleri
- `nixpacks.toml` — Railway'e Tesseract OCR'ı (Arapça+Türkçe dil paketleriyle) nasıl kuracağını söyler

## Railway'e yükleme adımları
1. railway.app'te hesap aç (GitHub ile giriş yapabilirsin)
2. "New Project" -> "Empty Project"
3. Bu klasördeki 3 dosyayı bir GitHub reposuna yükle (veya Railway CLI ile direkt deploy et)
4. Railway projenle GitHub reposunu bağla
5. Railway otomatik olarak nixpacks.toml'u okuyup Tesseract'ı kuracak, sonra main.py'ı başlatacak
6. Deploy bitince Railway sana bir URL verecek, örn: https://kasif-pdf-service.up.railway.app

## Test etme
Deploy bittikten sonra tarayıcıda şu adrese gir:
https://SENIN-URLIN.up.railway.app/health

Şöyle bir cevap görmen gerekiyor:
{"status": "ok", "service": "Kaşif PDF Kazıma Servisi"}

Bunu görüyorsan servis çalışıyor demektir.

## PDF işleme testi
Bir PDF dosyasıyla test etmek için (terminal/komut satırından):

curl -X POST "https://SENIN-URLIN.up.railway.app/process-pdf" \
  -F "file=@/yol/test-kitap.pdf"

Cevap olarak şu formatta bir JSON gelecek:
{
  "total_pages": 120,
  "pages_used_ocr": [45, 46, 47],
  "ocr_page_count": 3,
  "paragraph_count": 340,
  "paragraphs": ["İlk paragraf metni...", "İkinci paragraf...", ...]
}

"pages_used_ocr" listesi, hangi sayfaların taranmış/görüntü olduğu için
OCR'a düştüğünü gösterir. Bu sayı yüksekse, kitabın büyük kısmı taranmış demektir.
