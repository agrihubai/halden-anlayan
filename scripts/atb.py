"""Antalya Ticaret Borsası (ATB): Antalya Halleri domates, sebze ve meyve miktar ve fiyat endeksleri (aylık).

Kaynak sayfa: https://www.antalyaborsa.org.tr/endeksler
Excel dosyasının adresi her ay değişir (ör. /_fm/206-202610020900000001.xlsx); sayfadan bulunur.
Metodoloji: https://www.antalyaborsa.org.tr/_fm/221-202206021202141.pdf (Laspeyres; belge "temel yıl 2005" diyor,
Excel başlıkları "2015=100" diyor). Veriyle kontrol (2026-11-05): üç miktar endeksinin (domates, sebze, meyve) 2015
aylık ortalaması tam 100,00 → miktar serileri 2015=100 tabanlıdır. Fiyat endekslerinin 2015 ortalaması 97,97 / 101,92 /
109,43; tabanları veriyle doğrulanamadı. Panoda yalnızca miktar endeksleri kullanılır.
ATB endeksi Antalya Büyükşehir Belediyesi ile yapılan protokol kapsamında hesaplar (Bloomberg HT, 2 Ekim 2020).

Çıktı: data/ham/atb-endeks.json  {"kaynak", "dosya", "indirme", "seriler": {"domates_miktar": [["2015-01", 87.44], ...], ...}}
"""
from __future__ import annotations

import datetime as dt
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "ham" / "atb-endeks.json"
PAGE = "https://www.antalyaborsa.org.tr/endeksler"
UA = {"User-Agent": "agrihubai-halden-anlayan/1.0 (+https://github.com/agrihubai/halden-anlayan)"}
NAMES = {("domates", "miktar"): "domates_miktar", ("domates", "fiyat"): "domates_fiyat",
         ("sebze", "miktar"): "sebze_miktar", ("sebze", "fiyat"): "sebze_fiyat",
         ("meyve", "miktar"): "meyve_miktar", ("meyve", "fiyat"): "meyve_fiyat"}


def parse_xlsx(data: bytes) -> dict:
    try:
        import openpyxl
    except ImportError:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "openpyxl==3.1.5"], check=True)
        import openpyxl
    ws = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True).worksheets[0]
    out, cur = {}, None
    for row in ws.iter_rows(values_only=True):
        a = row[0]
        if isinstance(a, str):
            t = a.lower().replace("ı", "i")
            g = next((k for k in ("domates", "sebze", "meyve") if k in t), None)
            m = "miktar" if "miktar" in t else ("fiyat" if "fiyat" in t else None)
            cur = NAMES.get((g, m))
            if cur:
                out.setdefault(cur, [])
            continue
        if cur and isinstance(a, (int, float)) and 2000 <= int(a) <= 2100:
            for i, v in enumerate(row[1:13]):
                if isinstance(v, (int, float)):
                    out[cur].append([f"{int(a)}-{i + 1:02d}", round(float(v), 3)])
    return out


def update() -> int:
    html = urllib.request.urlopen(urllib.request.Request(PAGE, headers=UA), timeout=60).read().decode("utf-8", "replace")
    links = re.findall(r'href="([^"]*_fm/[^"]+\.xlsx?)"', html, flags=re.I)
    if not links:
        raise RuntimeError("endeks dosyası bağlantısı bulunamadı")
    url = links[0] if links[0].startswith("http") else "https://www.antalyaborsa.org.tr" + ("" if links[0].startswith("/") else "/") + links[0]
    data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
    series = parse_xlsx(data)
    if len(series) < 6 or min(len(v) for v in series.values()) < 60:
        raise RuntimeError(f"beklenmeyen dosya biçimi: {[(k, len(v)) for k, v in series.items()]}")
    write(series, url)
    return sum(len(v) for v in series.values())


def write(series: dict, url: str) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"kaynak": PAGE, "dosya": url, "indirme": dt.date.today().isoformat(),
                               "not": "Miktar endeksleri 2015=100 (Excel başlığı; 2015 aylık ortalaması 100,00). Metodoloji belgesi temel yılı 2005 olarak veriyor. Fiyat endekslerinin tabanı veriyle doğrulanamadı.",
                               "seriler": series}, ensure_ascii=False, indent=0), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) > 1:   # yerel dosyadan: python scripts/atb.py dosya.xlsx [kaynak-adres]
        s = parse_xlsx(Path(sys.argv[1]).read_bytes())
        write(s, sys.argv[2] if len(sys.argv) > 2 else "")
        print({k: (len(v), v[-1]) for k, v in s.items()})
    else:
        print(update())
