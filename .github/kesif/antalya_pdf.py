"""Keşif: Antalya 10 ve 12 Ekim PDF'leri neden okunamıyor? Yalnızca okur."""
import sys, io; sys.path.insert(0, "scripts")
import antalya as A
pl = A._pdfplumber()
for iso in ["2026-10-10", "2026-10-12", "2026-10-09"]:
    j = A.post_json("/Methods.aspx/GetGunlukHalFiyatPdf", {"tarih": iso})["d"]
    data = A.get(j["PdfUrl"]); print("=====", iso, j, len(data), data[:8])
    with pl.open(io.BytesIO(data)) as pdf:
        print(" sayfa:", len(pdf.pages), "meta:", pdf.metadata)
        for i, p in enumerate(pdf.pages[:2]):
            w = p.extract_words(x_tolerance=1.5)
            print(f" s{i}: kelime {len(w)}, karakter {len(p.chars)}, görsel {len(p.images)}, boyut {p.width}x{p.height}, döndürme {p.rotation if hasattr(p,'rotation') else '?'}")
            print("  ilk kelimeler:", [x["text"] for x in w[:60]])
            if w: print("  ilk satırlar:", (p.extract_text() or "")[:600].replace("\n", " ⏎ "))
    rows, d = A.parse_pdf(data); print(" parse:", len(rows), d, rows[:3])
