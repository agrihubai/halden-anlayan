"""Ham veriden (data/ham/) panonun okuduğu ürün dosyalarını (data/urun/<ürün>.json) üretir.

Türkiye: İzmir hali, çeşit bazında günlük [tarih, en düşük, en yüksek, ortalama] TL.
İspanya: Komisyon verisi, aşama + çeşit bazında haftalık [hafta başı, EUR/kg].
"""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
KEYS = ["domates", "biber", "hiyar", "patlican", "kabak"]


def f(v):
    try:
        x = float(v)
        return round(x, 3) if x > 0 else None
    except (TypeError, ValueError):
        return None


def per_kg(price: float, unit: str) -> float:
    u = unit.lower().replace(" ", "")
    if "100kg" in u:
        return price / 100
    if "/t" in u or "tonne" in u or "1000kg" in u:
        return price / 1000
    return price


def main() -> None:
    tr = defaultdict(lambda: defaultdict(list))
    units = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    p = DATA / "ham" / "izmir.csv"
    if p.exists():
        with p.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                lo, hi, avg = f(r["lo"]), f(r["hi"]), f(r["avg"])
                if avg is None and lo and hi:
                    avg = round((lo + hi) / 2, 3)
                if avg is None:
                    continue
                v = re.sub(r"\s+", " ", r["v"]).strip()
                tr[r["p"]][v].append([r["d"], lo, hi, avg])
                units[r["p"]][v][r["u"]] += 1

    es = defaultdict(lambda: defaultdict(dict))
    p = DATA / "ham" / "ispanya.json"
    if p.exists():
        for r in json.loads(p.read_text(encoding="utf-8")):
            label = " · ".join(x for x in (r.get("st"), r.get("v")) if x) or "—"
            es[r["p"]][label][r["d"]] = round(per_kg(r["price"], r.get("u", "")), 4)

    out_dir = DATA / "urun"
    out_dir.mkdir(exist_ok=True)
    index = []
    for k in KEYS:
        varieties = []
        for v, rows in tr[k].items():
            rows.sort()
            u = max(units[k][v].items(), key=lambda x: x[1])[0] if units[k][v] else ""
            varieties.append({"ad": v, "birim": u, "n": len(rows), "ilk": rows[0][0], "son": rows[-1][0]})
        varieties.sort(key=lambda x: (-x["n"], x["ad"]))
        es_series = {lab: sorted(d.items()) for lab, d in es[k].items()}
        doc = {
            "urun": k,
            "tr": {"cesitler": varieties, "seriler": {v: tr[k][v] for v in tr[k]}},
            "es": {"seriler": es_series},
        }
        (out_dir / f"{k}.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        index.append({"urun": k, "tr_cesit": len(varieties), "tr_son": max((x["son"] for x in varieties), default=None),
                      "es_seri": len(es_series), "es_son": max((s[-1][0] for s in es_series.values() if s), default=None)})
        print(k, index[-1])
    (DATA / "urunler.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
