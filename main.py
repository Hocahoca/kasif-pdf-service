"""
KAŞİF DİJİTAL KÜTÜPHANE - PDF KAZIMA SERVİSİ
================================================
Bu servis, PDF dosyalarından metin çıkarır. İki yöntemi birleştirir:
1. Normal metin çıkarma (PyMuPDF) - dijital/seçilebilir metinli PDF'ler için, hızlı
2. OCR (Tesseract) - taranmış/görüntü sayfalar için, Arapça+Türkçe destekli

Her sayfa için önce normal yöntem denenir. Eğer sayfadan anlamlı metin
çıkmazsa (sayfa bir görüntüyse), otomatik olarak OCR'a düşer.

Çıkan metin temizlenir:
- Sayfa numaraları, tekrarlayan üstbilgi/altbilgi satırları ayıklanır
- Satır kırılmaları (PDF'in kelimeyi ortadan bölmesi) düzeltilir
- Paragraflar mantıklı şekilde birleştirilir
- Arapça/Türkçe karakterler korunur (UTF-8)
"""

from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import JSONResponse
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io
import re
from collections import Counter

app = FastAPI(title="Kaşif PDF Kazıma Servisi")

# ============================================
# AYARLAR
# ============================================
MIN_TEXT_LENGTH_PER_PAGE = 30   # Bu karakterden azsa, sayfa "görüntü" sayılır -> OCR'a düşer
OCR_LANGUAGES = "ara+tur"       # Tesseract dil paketleri: Arapça + Türkçe
DIACRITIC_RATIO_THRESHOLD = 0.12  # Bu orandan fazla harekeli karakter varsa, blok OCR'a yönlendirilir
ARABIC_DIACRITICS = set(range(0x064B, 0x0653))  # Arapça hareke (tashkil) Unicode aralığı


def diacritic_ratio(text: str) -> float:
    """
    Metindeki Arapça karakterler içinde hareke (tashkil) oranını hesaplar.
    Yüksek oran (örn. ayet/hadis metni) -> PyMuPDF'in karakter sıralamasını
    karıştırma riski yüksek -> bu bloğu OCR'a yönlendirmek daha güvenilir.
    """
    arabic_chars = [c for c in text if 0x0600 <= ord(c) <= 0x06FF]
    if not arabic_chars:
        return 0.0
    diacritic_count = sum(1 for c in arabic_chars if ord(c) in ARABIC_DIACRITICS)
    return diacritic_count / len(arabic_chars)


def extract_block_image_text(page, bbox) -> str:
    """
    Sayfanın belirli bir bölgesini (bbox: bounding box) yüksek çözünürlüklü
    görüntüye çevirip OCR ile okur. Harekeli/karmaşık dizgili Arapça metin
    blokları için kullanılır - normal metin çıkarma yerine.
    """
    # Bölgeyi biraz genişletiyoruz (harekeler harfin biraz dışına taşabilir)
    rect = fitz.Rect(bbox)
    padded_rect = fitz.Rect(rect.x0 - 3, rect.y0 - 3, rect.x1 + 3, rect.y1 + 3)
    pix = page.get_pixmap(clip=padded_rect, dpi=400)  # yüksek DPI, küçük bölge için
    img_data = pix.tobytes("png")
    image = Image.open(io.BytesIO(img_data))
    text = pytesseract.image_to_string(image, lang=OCR_LANGUAGES)
    return text.strip()


def extract_text_normal(page) -> str:
    """
    Dijital PDF sayfasından metni BLOK BAZINDA çıkarır. Her blok için hareke
    yoğunluğuna bakılır:
    - Düşük hareke oranı (düz Türkçe/Arapça metin) -> doğrudan metin kullanılır (hızlı, güvenilir)
    - Yüksek hareke oranı (ayet/hadis gibi özel dizgili metin) -> o blok OCR'a yönlendirilir
      (çünkü bu tür metinlerde PyMuPDF'in karakter sıralaması bozulabiliyor)
    Bu karma yaklaşım, aynı sayfada hem düz açıklama hem alıntı ayet/hadis
    bulunan (Tefsir/Hadis kaynaklarında çok yaygın) durumları doğru şekilde ele alır.
    """
    page_dict = page.get_text("dict", sort=True)
    result_parts = []

    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:  # 0 = metin bloğu, 1 = görüntü bloğu
            continue

        # Bloğun düz metnini topla (satırları birleştirerek)
        block_lines = []
        for line in block.get("lines", []):
            line_text = "".join(span.get("text", "") for span in line.get("spans", []))
            block_lines.append(line_text)
        block_text = "\n".join(block_lines)

        if not block_text.strip():
            continue

        ratio = diacritic_ratio(block_text)

        if ratio >= DIACRITIC_RATIO_THRESHOLD:
            # Harekeli/özel dizgili metin -> bu bloğu OCR ile yeniden oku
            try:
                ocr_text = extract_block_image_text(page, block["bbox"])
                if ocr_text:  # OCR bir şey okuyabildiyse onu kullan
                    result_parts.append(ocr_text)
                else:  # OCR boş döndüyse, normal metne geri dön
                    result_parts.append(block_text)
            except Exception:
                # OCR bir sebeple başarısız olursa, normal metne geri dön (veri kaybı olmasın)
                result_parts.append(block_text)
        else:
            result_parts.append(block_text)

    return "\n\n".join(result_parts)


def extract_text_ocr(page) -> str:
    """
    Sayfayı yüksek çözünürlüklü görüntüye çevirip OCR ile metin okur.
    Taranmış/eski kitap sayfaları için kullanılır.
    """
    # Sayfayı yüksek çözünürlükte görüntüye çeviriyoruz (OCR doğruluğu için önemli)
    pix = page.get_pixmap(dpi=300)
    img_data = pix.tobytes("png")
    image = Image.open(io.BytesIO(img_data))

    # Tesseract ile Arapça+Türkçe OCR
    text = pytesseract.image_to_string(image, lang=OCR_LANGUAGES)
    return text


def clean_extracted_text(raw_text: str) -> str:
    """
    Çıkarılan ham metni temizler:
    - Fazla boşlukları/satır sonlarını düzenler
    - Kelimenin ortasında bölünmüş satırları birleştirir
    """
    if not raw_text:
        return ""

    # Satır sonunda tire ile bölünmüş kelimeleri birleştir (örn: "kita-\nbı" -> "kitabı")
    text = re.sub(r"-\n", "", raw_text)

    # Tek satır sonlarını boşlukla değiştir, ama çift satır sonunu (paragraf ayrımı) koru
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)

    # Üçten fazla ardışık satır sonunu ikiye indir
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Fazla boşlukları temizle
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)

    return text.strip()


def detect_and_remove_repeating_lines(pages_text: list[str]) -> list[str]:
    """
    Tüm sayfalarda tekrar eden satırları (üstbilgi/altbilgi, kitap adı, sayfa no gibi)
    tespit eder ve kaldırır. Bir satır, sayfaların %50'sinden fazlasında aynen
    tekrarlanıyorsa bu bir üstbilgi/altbilgi kabul edilir.
    """
    if len(pages_text) < 3:
        return pages_text  # çok az sayfa varsa tekrar tespiti güvenilir olmaz

    line_counter = Counter()
    for page_text in pages_text:
        lines = [l.strip() for l in page_text.split("\n") if l.strip()]
        # Her sayfanın ilk ve son satırlarına bakıyoruz (üst/alt bilgi orada olur)
        edge_lines = lines[:2] + lines[-2:]
        for line in edge_lines:
            if 0 < len(line) < 80:  # çok uzun satırlar gövde metni olabilir, atla
                line_counter[line] += 1

    threshold = len(pages_text) * 0.5
    repeating_lines = {line for line, count in line_counter.items() if count >= threshold}

    cleaned_pages = []
    for page_text in pages_text:
        lines = page_text.split("\n")
        filtered = [l for l in lines if l.strip() not in repeating_lines]
        cleaned_pages.append("\n".join(filtered))

    return cleaned_pages


def split_into_paragraphs(full_text: str) -> list[str]:
    """Temizlenmiş metni paragraflara böler (veritabanına bu şekilde kaydedilecek)."""
    paragraphs = [p.strip() for p in full_text.split("\n\n") if p.strip()]
    # Çok kısa "paragrafları" (örn. tek kelimelik kalıntılar) öncekiyle birleştir
    merged = []
    for p in paragraphs:
        if merged and len(p) < 15:
            merged[-1] += " " + p
        else:
            merged.append(p)
    return merged


@app.post("/process-pdf")
async def process_pdf(file: UploadFile):
    """
    Ana endpoint: PDF dosyasını alır, metni çıkarır, temizler,
    paragraf listesi olarak döner. Supabase Edge Function bu sonucu
    alıp veritabanına yazacak.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Sadece PDF dosyaları kabul edilir.")

    pdf_bytes = await file.read()

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"PDF açılamadı: {str(e)}")

    pages_text = []
    pages_used_ocr = []
    total_pages = len(doc)  # dokümanı kapatmadan önce sayfa sayısını kaydediyoruz

    for page_num in range(total_pages):
        page = doc[page_num]
        text = extract_text_normal(page)

        if len(text.strip()) < MIN_TEXT_LENGTH_PER_PAGE:
            # Bu sayfa muhtemelen taranmış görüntü -> OCR'a düş
            text = extract_text_ocr(page)
            pages_used_ocr.append(page_num + 1)

        pages_text.append(text)

    doc.close()

    # Tekrar eden üstbilgi/altbilgi satırlarını tüm kitap genelinde tespit edip kaldır
    pages_text = detect_and_remove_repeating_lines(pages_text)

    # Her sayfayı temizle ve birleştir
    cleaned_pages = [clean_extracted_text(t) for t in pages_text]
    full_text = "\n\n".join(cleaned_pages)

    paragraphs = split_into_paragraphs(full_text)

    return JSONResponse({
        "total_pages": total_pages,
        "pages_used_ocr": pages_used_ocr,
        "ocr_page_count": len(pages_used_ocr),
        "paragraph_count": len(paragraphs),
        "paragraphs": paragraphs,
    })


@app.get("/health")
async def health_check():
    """Servisin ayakta olduğunu kontrol etmek için basit bir endpoint."""
    return {"status": "ok", "service": "Kaşif PDF Kazıma Servisi"}
