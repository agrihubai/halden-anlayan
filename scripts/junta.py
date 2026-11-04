"""Junta de Andalucía — Precios agrícolas semanales (Consejería de Agricultura, Pesca, Agua y Desarrollo Rural).

Kaynak sayfa (yıllık Excel dosyaları):
  https://www.juntadeandalucia.es/organismos/agriculturapescaaguaydesarrollorural/servicios/estadistica-cartografia/estadisticas-agricolas/paginas/precios-agricolas-semanales.html
Açık veri kaydı: https://www.juntadeandalucia.es/datosabiertos/portal/dataset/precios-agricolas-semanales-2014 — lisans CC BY 4.0.
Ticari pozisyonlar (dosyadaki tanımlar): "Alm." = Entrada almacén de agricultor (üreticinin malı depoya teslimi, KDV hariç),
  "Alh." = Alhóndiga (mezat panosu veya açık artırma ağırlıklı ortalaması, alhóndiga komisyonu dahil, KDV hariç).

Sadece sebze ürünleri alınır (örtüaltı ve açık alan). Çıktı: data/ham/junta/YYYY.csv.gz
  kolonlar: d (haftanın pazartesisi), bolum, urun, tip, kategori, birim, il, pozisyon, fiyat (EUR/kg)
Özet: data/_kesif/junta-ozet.json (her dosyada kaç satır okundu, başlık nerede bulundu).
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "ham" / "junta"
PROBE = ROOT / "data" / "_kesif"
PAGE = ("https://www.juntadeandalucia.es/organismos/agriculturapescaaguaydesarrollorural/servicios/"
        "estadistica-cartografia/estadisticas-agricolas/paginas/precios-agricolas-semanales.html")
UA = {"User-Agent": "agrihubai-halden-anlayan/1.0 (+https://github.com/agrihubai/halden-anlayan)"}
FIELDS = ["d", "bolum", "urun", "tip", "kategori", "birim", "il", "pozisyon", "fiyat"]
URUNLER = {"TOMATE", "PIMIENTO", "PEPINO", "BERENJENA", "CALABACIN", "JUDIA VERDE", "MELON", "SANDIA"}
IL = {"AL": "Almería", "GR": "Granada", "MA": "Málaga", "SE": "Sevilla", "CA": "Cádiz", "CO": "Córdoba", "HU": "Huelva", "JA": "Jaén"}


def plain(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def xlrd_mod():
    try:
        import xlrd
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "xlrd==2.0.1"], check=True)
        import xlrd
    return xlrd


def year_of(url: str) -> int | None:
    name = urllib.parse.unquote(url.rsplit("/", 1)[-1]).lower()
    m = re.search(r"(20\d{2})", name) or re.search(r"pagricolas(\d{2})_", name)
    if not m:
        return None
    y = int(m.group(1))
    return y + 2000 if y < 100 else y


def file_links() -> dict[int, str]:
    html = urllib.request.urlopen(urllib.request.Request(PAGE, headers=UA), timeout=60).read().decode("utf-8", "replace")
    out = {}
    for h in re.findall(r'href="([^"]+\.xlsx?)"', html, flags=re.I):
        if not re.search(r"agr", h, re.I):
            continue
        url = h if h.startswith("http") else "https://www.juntadeandalucia.es" + h
        y = year_of(url)
        if y:
            out[y] = url
    return out


def to_float(v):
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    s = str(v or "").strip().replace(",", ".")
    try:
        x = float(s)
        return x if x > 0 else None
    except ValueError:
        return None


def parse_sheet(sh, year: int) -> tuple[list[dict], dict]:
    rows = [[str(c.value).strip() if not isinstance(c.value, float) else c.value for c in sh.row(i)] for i in range(sh.nrows)]
    head = None
    for i, r in enumerate(rows[:15]):
        p = [plain(x) if isinstance(x, str) else "" for x in r]
        if any(x.startswith("UNIDAD") for x in p) and any(x.startswith("MERCADO") for x in p) and any(re.match(r"SEM", x) for x in p):
            head = i
            break
    info = {"baslik": head, "satir": sh.nrows}
    if head is None:
        return [], info
    p = [plain(x) if isinstance(x, str) else "" for x in rows[head]]
    iu = next(i for i, x in enumerate(p) if x.startswith("UNIDAD"))
    im = next(i for i, x in enumerate(p) if x.startswith("MERCADO"))
    ip = next((i for i, x in enumerate(p) if x.startswith("POS")), im + 1)
    ik = next((i for i, x in enumerate(p) if x.startswith("CATEGOR")), None)
    weeks = [(i, int(re.search(r"(\d+)", x).group(1))) for i, x in enumerate(p) if re.match(r"SEM\.?\s*\d+", x)]
    info["hafta"] = len(weeks)
    out, section, product = [], "", None
    for r in rows[head + 1:]:
        first = r[0] if r else ""
        if not isinstance(first, str) or not first:
            continue
        unit = r[iu] if iu < len(r) else ""
        if not unit:   # bölüm ya da ürün başlığı
            f = plain(first)
            if f in URUNLER:
                product = f
            elif first != first.upper():   # "Hortícolas protegidos" gibi bölüm adı
                section, product = first, None
            else:
                product = None
            continue
        if not product:
            continue
        market = str(r[im])
        mm = re.match(r"\s*([A-Z]{2})\s*-\s*(.+)", market)
        il = mm.group(1) if mm else ""
        u = plain(unit)
        div = 100 if "100" in u else (1000 if u.startswith("T") else 1)
        cat = str(r[ik]).strip() if ik is not None else ""
        tip = str(first).strip()
        for ci, wk in weeks:
            v = to_float(r[ci]) if ci < len(r) else None
            if v is None:
                continue
            try:
                d = dt.date.fromisocalendar(year, wk, 1)
            except ValueError:
                continue
            out.append({"d": d.isoformat(), "bolum": section, "urun": product, "tip": tip, "kategori": cat, "birim": str(unit).strip(),
                        "il": il, "pozisyon": str(r[ip]).strip() if ip < len(r) else "", "fiyat": round(v / div, 4)})
    return out, info


def update() -> int:
    xlrd = xlrd_mod()
    RAW.mkdir(parents=True, exist_ok=True)
    links = file_links()
    if not links:
        raise RuntimeError("yıllık dosya bağlantısı bulunamadı")
    this_year = dt.date.today().year
    summary, total = {}, 0
    for y, url in sorted(links.items()):
        p = RAW / f"{y}.csv.gz"
        if p.exists() and y < this_year - 1:
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                n = sum(1 for _ in fh) - 1
            summary[y] = {"url": url, "kayit": n, "onbellek": True}
            total += n
            continue
        try:
            data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()
            wb = xlrd.open_workbook(file_contents=data)
            rows, info = [], {}
            for sh in wb.sheets():
                r, i = parse_sheet(sh, y)
                info[sh.name] = i
                rows += r
        except Exception as e:  # noqa: BLE001
            summary[y] = {"url": url, "hata": str(e)[:200]}
            continue
        summary[y] = {"url": url, "kayit": len(rows), "sayfalar": info,
                      "almeria_tipler": sorted({f'{r["urun"]} · {r["tip"]} · {r["kategori"]} · {r["pozisyon"]}' for r in rows if r["il"] == "AL"})[:80]}
        if rows:
            with gzip.open(p, "wt", encoding="utf-8", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=FIELDS)
                w.writeheader()
                w.writerows(rows)
        total += len(rows)
    PROBE.mkdir(parents=True, exist_ok=True)
    (PROBE / "junta-ozet.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  junta: {total} kayıt, {len(links)} yıl")
    return total


if __name__ == "__main__":
    update()
