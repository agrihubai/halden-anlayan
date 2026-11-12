"""Gazipaşa hali günlük fiyat listesi (Batı Akdeniz Haber Ajansı yayını).

Kaynak: https://www.batiakdeniztv.com/gazipasa-hal-fiyatlari
  Sayfa tek bir "güncel liste"dir; her gün üzerine yazılır, arşivi yoktur. Bu yüzden her çalıştırmada
  o anki liste okunur ve başlıktaki tarihle (ör. "12 KASIM 2026") saklanır; seri bugünden ileri birikir.
  Tablo: <table class="price-table"> → satır başına ürün adı (td.name) ve bir ya da iki fiyat (td.val, ₺/kg).
  Bir fiyat varsa en düşük = en yüksek; iki fiyat varsa en düşük ve en yüksek. Aynı ad birden çok satırda
  geçerse (ör. iki "Domates" satırı) bütün fiyatlar birleştirilir. Ortalama (avg) en düşük ile en yüksek
  fiyatın orta noktasıdır (Antalya ile aynı kural).
  robots.txt bu sayfayı yasaklamıyor (2026-11-12'de kontrol edildi).

Kaynağın kendisi belediye ya da hal müdürlüğü değil, yerel haber ajansıdır; fiyatlar hal komisyoncularının
günlük bildirdiği aralıktır. Okunan satırlar data/ham/gazipasa/YYYY.csv.gz dosyasına yazılır (İzmir ile aynı kolonlar).
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import html
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "ham" / "gazipasa"
PROBE = ROOT / "data" / "_kesif"
URL = "https://www.batiakdeniztv.com/gazipasa-hal-fiyatlari"
UA = {"User-Agent": "agrihubai-halden-anlayan/1.0 (+https://github.com/agrihubai/halden-anlayan)"}
FIELDS = ["d", "tur", "v", "u", "lo", "hi", "avg"]
AYLAR = {"OCAK": 1, "ŞUBAT": 2, "SUBAT": 2, "MART": 3, "NİSAN": 4, "NISAN": 4, "MAYIS": 5, "HAZİRAN": 6, "HAZIRAN": 6,
         "TEMMUZ": 7, "AĞUSTOS": 8, "AGUSTOS": 8, "EYLÜL": 9, "EYLUL": 9, "EKİM": 10, "EKIM": 10,
         "KASIM": 11, "ARALIK": 12}


def upper_tr(s: str) -> str:
    return s.replace("i", "İ").replace("ı", "I").upper()


def text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def num(s: str) -> float | None:
    s = s.strip()
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def parse(page: str) -> tuple[dt.date | None, list[dict]]:
    """Sayfa HTML'i → (liste tarihi, satırlar)."""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S | re.I)
    d = None
    if m:
        dm = re.search(r"(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)\s+(\d{4})", text(m.group(1)))
        if dm and upper_tr(dm.group(2)) in AYLAR:
            d = dt.date(int(dm.group(3)), AYLAR[upper_tr(dm.group(2))], int(dm.group(1)))
    t = re.search(r'<table[^>]*class="[^"]*price-table[^"]*"[^>]*>(.*?)</table>', page, re.S | re.I)
    if not t:
        return d, []
    merged: dict[str, list[float]] = {}
    spelled: dict[str, str] = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", t.group(1), re.S | re.I):
        nm = re.search(r'<td[^>]*class="[^"]*name[^"]*"[^>]*>(.*?)</td>', tr, re.S | re.I)
        vl = re.search(r'<td[^>]*class="[^"]*val[^"]*"[^>]*>(.*?)</td>', tr, re.S | re.I)
        if not nm or not vl:
            continue
        name = text(nm.group(1))
        vals = [v for v in (num(x) for x in re.findall(r"\d[\d.,]*", text(vl.group(1)))) if v]
        if not name or not vals:
            continue
        key = upper_tr(name)
        merged.setdefault(key, []).extend(vals)
        spelled.setdefault(key, name)
    rows = []
    for key, vals in merged.items():
        lo, hi = min(vals), max(vals)
        if hi > lo * 5:   # biçim bozulması (ör. birleşik rakam) — kaydetme
            print(f"  Gazipaşa: {spelled[key]} fiyatları tutarsız {vals}; atlandı", file=sys.stderr)
            continue
        rows.append({"tur": "", "v": spelled[key], "u": "KG", "lo": lo, "hi": hi, "avg": round((lo + hi) / 2, 3)})
    return d, rows


def read_year(year: int) -> list[dict]:
    p = RAW / f"{year}.csv.gz"
    if not p.exists():
        return []
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_year(year: int, rows: list[dict]) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: (r["d"], r["v"]))
    with gzip.open(RAW / f"{year}.csv.gz", "wt", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def update() -> int:
    """Güncel listeyi okur; o tarihin satırlarını (varsa) yenileriyle değiştirir. Arşivdeki toplam satır sayısını döndürür."""
    req = urllib.request.Request(URL, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        page = r.read().decode("utf-8", "replace")
    d, rows = parse(page)
    if not rows:
        PROBE.mkdir(parents=True, exist_ok=True)
        (PROBE / "gazipasa-hata.html").write_text(page[:60000], encoding="utf-8")
        raise RuntimeError("Gazipaşa: fiyat tablosu okunamadı (data/_kesif/gazipasa-hata.html)")
    today = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3)).date()   # Türkiye saati
    if d is None or d > today or (today - d).days > 7:
        raise RuntimeError(f"Gazipaşa: liste tarihi okunamadı ya da beklenmedik ({d}); kaydedilmedi")
    iso = d.isoformat()
    year_rows = [r for r in read_year(d.year) if r["d"] != iso]
    year_rows += [{"d": iso, **r} for r in rows]
    write_year(d.year, year_rows)
    total = sum(len(read_year(y)) for y in range(2026, today.year + 1))
    print(f"  Gazipaşa: {iso} · {len(rows)} ürün · arşivde {total} satır")
    return total


if __name__ == "__main__":
    try:
        update()
    except Exception as e:  # noqa: BLE001
        print(f"HATA: {e}", file=sys.stderr)
        sys.exit(1)
