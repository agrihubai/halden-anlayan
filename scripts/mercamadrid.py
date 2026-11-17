"""Mercamadrid — aylık hacim ve fiyat, çeşit ve menşe ayrımıyla (Ayuntamiento de Madrid açık veri, CC BY 4.0).

Veri kümesi: https://datos.madrid.es/dataset/300357-0-mercamadrid-volumen-precio
Kaynak dosyalar CKAN API'sinden bulunur (yıl başına bir CSV; adında yıl yazmaz, yıl ilk satırdaki tarihten okunur).
Kolonlar: Fecha Desde; Fecha Hasta; Código Variedad; Descripción Variedad; Origen; Descripción Origen; Kilos;
          Precio Más Frecuente; Precio Máximo; Precio Mínimo   (€/kg, KDV hariç; "en sık fiyat" günlük en sık fiyatın ay ortalaması)
Biçim yıllar içinde değişti (2019-20: boşluksuz ayraç, menşe kodu sıfırsız); ikisi de okunur.

Neden eklendi: Junta (Endülüs) armutta yalnız Blanquilla, Conferencia, Ercolini verir. İspanya'da satılan öteki çeşitler
(Limonera = Dr. Jules Guyot, Passa Crassana, Comice, Castell/Sanjuanera...) yalnız Mercamadrid serisinde ayrı fiyatlanır.
Bu bir toptancı hali (varış pazarı) fiyatıdır, üretici ilk satış fiyatı değildir.

Yalnız meyve ve sebze satırları tutulur (çeşit kodu F ya da H ile başlar). Çıktı: data/ham/mercamadrid/YYYY.csv.gz
  kolonlar: d (ayın ilk günü), kod, cesit, mense_kod, mense, kg, fiyat, en_yuksek, en_dusuk
Özet: data/_kesif/mercamadrid-ozet.json
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import io
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "ham" / "mercamadrid"
PROBE = ROOT / "data" / "_kesif"
API = "https://datos.madrid.es/api/3/action/package_show?id=300357-0-mercamadrid-volumen-precio"
UA = {"User-Agent": "agrihubai-halden-anlayan/1.0 (+https://github.com/agrihubai/halden-anlayan)"}
FIELDS = ["d", "kod", "cesit", "mense_kod", "mense", "kg", "fiyat", "en_yuksek", "en_dusuk"]


def get(url: str, tries: int = 3) -> bytes:
    """Sunucu art arda isteklerde 'Access Denied' sayfası döndürebiliyor: bekleyip yeniden dener."""
    last = None
    for i in range(tries):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()
            if b[:200].lstrip().lower().startswith(b"<html"):
                raise RuntimeError("HTML (Access Denied) döndü")
            return b
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(10 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def num(s: str) -> float | None:
    try:
        x = float(str(s).strip().replace(".", "").replace(",", ".")) if "," in str(s) else float(str(s).strip())
        return x if x > 0 else None
    except ValueError:
        return None


def parse(text: str) -> tuple[int | None, list[dict]]:
    rows, year = [], None
    for i, line in enumerate(io.StringIO(text)):
        f = [x.strip() for x in line.split(";")]
        if i == 0 or len(f) < 10 or not f[0].isdigit():
            continue
        kod = f[2]
        if not kod[:1] in ("F", "H"):
            continue
        d = f"{f[0][:4]}-{f[0][4:6]}-01"
        year = year or int(f[0][:4])
        kg = num(f[6].lstrip("0") or "0")
        p = num(f[7])
        if not p:
            continue
        try:
            mk = int(f[4])
        except ValueError:
            mk = -1
        rows.append({"d": d, "kod": kod, "cesit": f[3], "mense_kod": mk, "mense": f[5], "kg": int(kg or 0),
                     "fiyat": p, "en_yuksek": num(f[8]), "en_dusuk": num(f[9])})
    return year, rows


def update() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    meta = json.loads(get(API))
    res = [r for r in meta["result"]["resources"] if (r.get("format") or "").upper() in ("CSV", "TXT")]
    this_year = dt.date.today().year
    have = {int(p.name[:4]) for p in RAW.glob("*.csv.gz")}
    summary, done, total = {}, set(), 0
    # CSV'ler önce; aynı yılın TXT kopyası yalnız CSV alınamazsa kullanılır
    res.sort(key=lambda r: (r["format"].upper() != "CSV", r["name"]))
    for r in res:
        try:
            raw = get(r["url"])
        except Exception as e:  # noqa: BLE001
            summary[r["name"]] = {"hata": str(e)[:200]}
            continue
        finally:
            time.sleep(5)
        year, rows = parse(raw.decode("latin-1"))
        if not year or year in done:
            summary[r["name"]] = {"yil": year, "atlandi": True}
            continue
        done.add(year)
        summary[r["name"]] = {"yil": year, "kayit": len(rows), "ay": sorted({x["d"][5:7] for x in rows})}
        if year in have and year < this_year - 1:
            total += len(rows)
            continue          # kapanmış yıl, zaten var
        with gzip.GzipFile(RAW / f"{year}.csv.gz", "wb", mtime=0) as gz:
            fh = io.TextIOWrapper(gz, encoding="utf-8", newline="")
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(sorted(rows, key=lambda x: (x["d"], x["kod"], x["mense_kod"])))
            fh.flush()
            fh.detach()
        total += len(rows)
    PROBE.mkdir(parents=True, exist_ok=True)
    (PROBE / "mercamadrid-ozet.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    if not done:
        raise RuntimeError("hiçbir yıl okunamadı")
    print(f"  mercamadrid: {total} kayıt, yıllar {sorted(done)}")
    return total


if __name__ == "__main__":
    update()
