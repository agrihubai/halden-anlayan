"""Antalya Toptancı Hali günlük fiyat listesi (Antalya Büyükşehir Belediyesi).

Kaynak: https://antalya.bel.tr/tr/halden-gunluk-fiyatlar sayfasındaki liste
  https://gezipanel.antalya.bel.tr/hal-gunluk-fiyat adresinden gelir. Her gün için imzalı bir PDF yayınlanır:
  POST https://gezipanel.antalya.bel.tr/Methods.aspx/GetGunlukHalFiyatPdf  {"tarih": "YYYY-MM-DD"}
  → {"d": {"PdfUrl": "/Hal/Uploads/GunlukFiyatlar/<id>_DD.MM.YYYY.pdf", "PdfDate": "DD.MM.YYYY"}}
  ya da {"d": {"Mesaj": "Fiyat listesi bulunamadı."}} (pazar ve tatil günleri).
Listenin dipnotu: "5957 sayılı Kanunun 6. maddesinin 4. fıkrası ve 16. maddesinin 3. fıkrası gereğince" yayınlanır.
Listede sadece en düşük ve en yüksek fiyat vardır; ortalama sütunu (avg) iki değerin orta noktasıdır.
Arşiv 2026 Temmuz başından itibaren erişilebilir (2026-11-04'te denendi).

PDF'ler saklanmaz; okunan satırlar data/ham/antalya/YYYY.csv.gz dosyasına yazılır (İzmir ile aynı kolonlar).
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import io
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "ham" / "antalya"
PROBE = ROOT / "data" / "_kesif"
BASE = "https://gezipanel.antalya.bel.tr"
UA = {"User-Agent": "agrihubai-halden-anlayan/1.0 (+https://github.com/agrihubai/halden-anlayan)"}
FIELDS = ["d", "tur", "v", "u", "lo", "hi", "avg"]
START = dt.date(2026, 7, 1)
UNITS = {"KG", "BAĞ", "BAG", "ADET", "KASA", "DEMET", "KOLİ", "KOLI", "TANE"}
NUM = re.compile(r"^\d{1,3}(?:\.\d{3})*(?:,\d+)?$|^\d+(?:[.,]\d+)?$")


def num(s: str) -> float | None:
    s = s.strip()
    if not NUM.match(s):
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def upper_tr(s: str) -> str:
    return s.replace("i", "İ").replace("ı", "I").upper()


def parse_words(words: list[tuple[float, float, str]], page_width: float) -> list[dict]:
    """words: (x0, top, text). İki sütunlu liste: her yarıda satır = sıra no, ad, birim, en düşük, en yüksek.
    Sol yarı sebzeler; sağ yarı meyveler, 'İ T H A L' başlığının altı ithal ürünler."""
    mid = page_width * 0.437          # sağ sütunun sıra numarası x≈267 / 595
    # "İ T H A L Ü R Ü N L E R" başlığı harf harf ayrı kelimeler olarak gelebilir: satırı birleştirip ara
    lines: dict[int, list] = {}
    for x, t, w in words:
        lines.setdefault(round(t), []).append((x, w))
    ithal_top = next((t for t, ws in sorted(lines.items())
                      if "İTHALÜRÜNLER" in "".join(w for x, w in sorted(ws)).replace(" ", "").upper()), None)
    out = []
    for side in (0, 1):
        ws = [w for w in words if (w[0] < mid) == (side == 0)]
        rows: list[list] = []
        for w in sorted(ws, key=lambda w: (w[1], w[0])):
            if rows and abs(rows[-1][0] - w[1]) <= 3:
                rows[-1][1].append(w)
            else:
                rows.append([w[1], [w]])
        for top, items in rows:
            toks = [s for x, t, s in sorted(items, key=lambda w: w[0])]
            flat = " ".join(toks).split()
            ui = next((i for i, s in enumerate(flat) if upper_tr(s) in UNITS), None)
            if ui is None or ui < 1:
                continue
            head = flat[:ui]
            if head and head[0].isdigit():
                head = head[1:]
            vals = [num(s) for s in flat[ui + 1:]]
            vals = [v for v in vals if v is not None]
            name = " ".join(head).strip()
            if not name or len(vals) < 2:
                continue
            lo, hi = vals[0], vals[1]
            tur = "SEBZE" if side == 0 else ("İTHAL" if ithal_top is not None and top > ithal_top else "MEYVE")
            out.append({"tur": tur, "v": name, "u": upper_tr(flat[ui]), "lo": lo, "hi": hi,
                        "avg": round((lo + hi) / 2, 3) if lo and hi else (lo or hi)})
    return out


def _pdfplumber():
    try:
        import pdfplumber  # noqa: F401
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pdfplumber==0.11.4"], check=True)
    import pdfplumber
    return pdfplumber


def parse_pdf(data: bytes) -> tuple[list[dict], str | None]:
    pdfplumber = _pdfplumber()
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        rows, date = [], None
        for page in pdf.pages:
            words = page.extract_words(keep_blank_chars=False, use_text_flow=False, x_tolerance=1.5)
            text = " ".join(w["text"] for w in words)
            m = re.search(r"\b(\d{2}\.\d{2}\.\d{4})\b", text)
            date = date or (m and m.group(1))
            rows += parse_words([(w["x0"], w["top"], w["text"]) for w in words], page.width)
    return rows, date


def post_json(path: str, body: dict):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={**UA, "Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(BASE + urllib.request.quote(path), headers=UA), timeout=90) as r:
        return r.read()


def read_year(year: int) -> list[dict]:
    p = RAW / f"{year}.csv.gz"
    if not p.exists():
        return []
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_year(year: int, rows: list[dict]) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    rows = sorted({(r["d"], r["v"]): r for r in rows}.values(), key=lambda r: (r["d"], r["tur"], r["v"]))
    with gzip.open(RAW / f"{year}.csv.gz", "wt", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def update(budget_sec: int = 900) -> int:
    """Arşivde olmayan günleri (son 10 gün her zaman yeniden) indirir. Kaydedilen satır sayısını döndürür."""
    today = dt.date.today()
    have: dict[int, list[dict]] = {}
    days_have = set()
    for y in range(START.year, today.year + 1):
        have[y] = read_year(y)
        days_have |= {r["d"] for r in have[y]}
    missing_file = RAW / "bos-gunler.json"
    empty = set(json.loads(missing_file.read_text())) if missing_file.exists() else set()
    t0 = time.time()
    d, new, probed = START, 0, False
    while d <= today and time.time() - t0 < budget_sec:
        iso = d.isoformat()
        recent = (today - d).days <= 10
        if (iso in days_have or iso in empty) and not recent:
            d += dt.timedelta(days=1)
            continue
        try:
            j = (post_json("/Methods.aspx/GetGunlukHalFiyatPdf", {"tarih": iso}) or {}).get("d") or {}
        except Exception as e:  # noqa: BLE001
            print(f"  antalya {iso}: {e}", file=sys.stderr)
            d += dt.timedelta(days=1)
            continue
        if not j.get("PdfUrl"):
            if not recent:
                empty.add(iso)
            d += dt.timedelta(days=1)
            continue
        rows, pdf_date = parse_pdf(get(j["PdfUrl"]))
        if pdf_date and dt.datetime.strptime(pdf_date, "%d.%m.%Y").date() != d:
            print(f"  antalya {iso}: PDF tarihi {pdf_date}", file=sys.stderr)
        if not probed:
            PROBE.mkdir(parents=True, exist_ok=True)
            (PROBE / "antalya-ornek.json").write_text(json.dumps({"tarih": iso, "kaynak": j, "satir": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
            probed = True
        if len(rows) < 20:
            print(f"  antalya {iso}: sadece {len(rows)} satır okundu, atlandı", file=sys.stderr)
            d += dt.timedelta(days=1)
            continue
        y = d.year
        have[y] = [r for r in have.get(y, []) if r["d"] != iso] + [{"d": iso, **r} for r in rows]
        new += len(rows)
        time.sleep(0.5)
        d += dt.timedelta(days=1)
    for y, rows in have.items():
        if rows:
            write_year(y, rows)
    RAW.mkdir(parents=True, exist_ok=True)
    missing_file.write_text(json.dumps(sorted(empty)), encoding="utf-8")
    total = sum(len(r) for r in have.values())
    print(f"  antalya: {new} yeni/yenilenen satır, toplam {total}")
    return total


if __name__ == "__main__":
    update()
