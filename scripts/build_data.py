"""Ham veriden (data/ham/) panonun okuduğu dosyaları üretir; ürün ve segmentleri sozluk/urunler.json'dan alır.

- data/urunler.json      : ürün listesi (tür, segmentler, gün sayısı, son tarih, İspanya verisi var mı)
- data/urun/<ürün>.json  : ürünün segmentleri, segment ortalama serileri, haldeki her adın serisi (TL)
                           ve İspanya serileri (EUR/kg)
- data/_kesif/izmir-adlar.csv : haldeki her adın hangi ürün ve segmente gittiği (kontrol için)
- data/_kesif/ab-adlar.csv    : AB verisindeki ürün, aşama ve çeşitler
"""
from __future__ import annotations

import csv
import gzip
import json
import re
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "ham"
SOZLUK = json.loads((ROOT / "sozluk" / "urunler.json").read_text(encoding="utf-8"))
YAN = re.compile(SOZLUK["yan"])


def fold(s: str) -> str:
    """Hal adını karşılaştırma biçimine getirir: büyük harf, Türkçe karakterler sadeleşmiş, tek boşluk."""
    s = (s or "").replace("ı", "i").replace("İ", "I")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s*\(\s*", " (", s.upper())
    s = re.sub(r"\s*\)\s*", ") ", s)
    return re.sub(r"\s+", " ", s).strip()


def classify(fname: str):
    for u in SOZLUK["urunler"]:
        if re.search(u["izmir"], fname):
            for s in u["segmentler"]:
                if s["kalip"] and re.search(s["kalip"], fname):
                    return u, s
            default = next((s for s in u["segmentler"] if not s["kalip"]), None)
            return u, default
    return None, None


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
    # ---- Türkiye: aynı adın farklı yazımları (BIBER SIVRI / BİBER SİVRİ) tek seride birleşir
    series = defaultdict(dict)                 # fold(ad) -> {tarih: [lo, hi, avg]}
    spelled = defaultdict(Counter)             # fold(ad) -> {yazım: son tarih}
    units = defaultdict(Counter)
    for p in sorted((RAW / "izmir").glob("*.csv.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                lo, hi, avg = f(r["lo"]), f(r["hi"]), f(r["avg"])
                if avg is None and lo and hi:
                    avg = round((lo + hi) / 2, 3)
                if avg is None:
                    continue
                key = fold(r["v"])
                series[key][r["d"]] = [lo, hi, avg]
                spelled[key][r["v"].strip()] = max(spelled[key][r["v"].strip()], int(r["d"].replace("-", "")))
                units[key][r["u"].upper()] += 1

    products = {}
    inventory, unmatched = [], []
    for key, days in series.items():
        u, s = classify(key)
        name = max(spelled[key].items(), key=lambda x: x[1])[0]   # en son kullanılan yazım
        rows = [[d, *v] for d, v in sorted(days.items())]
        unit = units[key].most_common(1)[0][0]
        if not u:
            unmatched.append(name)
            inventory.append(["", "", name, unit, len(rows), rows[0][0], rows[-1][0], ""])
            continue
        if not s:
            s = {"k": "standart", "tr": "Standart", "en": "Standard", "es": "Estándar"}
        P = products.setdefault(u["k"], {"u": u, "ad": {}, "seg": defaultdict(list)})
        yan = bool(YAN.search(key))
        P["ad"][key] = {"ad": name, "anahtar": key, "segment": s["k"], "birim": unit, "yan": yan,
                        "n": len(rows), "ilk": rows[0][0], "son": rows[-1][0], "rows": rows}
        P["seg"][s["k"]].append(key)
        inventory.append([u["k"], s["k"], name, unit, len(rows), rows[0][0], rows[-1][0], "yan" if yan else ""])

    # ---- İspanya
    es = defaultdict(lambda: defaultdict(dict))
    es_inv = Counter()
    p = RAW / "ispanya.json.gz"
    if p.exists():
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            for r in json.load(fh):
                es_inv[(r["urun"], r["st"], r["v"], r["u"], r.get("per", ""))] += 1
                if r.get("per") and r["per"].lower() != "week":
                    continue  # grafikte sadece haftalık fiyatlar
                st = {"Ex-packaging station price": "Paketleme çıkışı", "Farmgate price": "Tarla",
                      "Retail buying price": "Perakende alış", "Retail selling price": "Raf"}.get(r["st"], r["st"])
                label = " · ".join(x for x in (st, r["v"]) if x) or "—"
                es[r["urun"]][label][r["d"]] = round(per_kg(r["price"], r["u"]), 4)

    # ---- yaz
    out = DATA / "urun"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.json"):
        old.unlink()
    index = []
    for u in SOZLUK["urunler"]:
        P = products.get(u["k"])
        if not P:
            continue
        segs = []
        for s in u["segmentler"] + [{"k": "standart", "tr": "Standart", "en": "Standard", "es": "Estándar"}]:
            keys = P["seg"].get(s["k"])
            if not keys or any(x["k"] == s["k"] for x in segs):
                continue
            main_keys = [k for k in keys if not P["ad"][k]["yan"]] or keys
            # segment serisi: o gün işlem gören ana adların ortalaması; en düşük/en yüksek: o günkü uç değerler
            by_day = defaultdict(list)
            for k in main_keys:
                for d, lo, hi, avg in P["ad"][k]["rows"]:
                    by_day[d].append((lo, hi, avg))
            seri = []
            for d in sorted(by_day):
                v = by_day[d]
                los = [x[0] for x in v if x[0]]
                his = [x[1] for x in v if x[1]]
                seri.append([d, min(los) if los else None, max(his) if his else None, round(statistics.fmean(x[2] for x in v), 3)])
            units_ = Counter(P["ad"][k]["birim"] for k in main_keys)
            segs.append({"k": s["k"], "tr": s["tr"], "en": s["en"], "es": s["es"], "ab": s.get("ab", []), "birim": units_.most_common(1)[0][0],
                         "adlar": sorted(keys, key=lambda k: (P["ad"][k]["yan"], -P["ad"][k]["n"])),
                         "n": len(seri), "ilk": seri[0][0], "son": seri[-1][0], "seri": seri})
        es_series = {}
        for en in u.get("ab", []):
            for lab, d in es.get(en, {}).items():
                es_series[lab] = sorted(d.items())
        adlar = {k: {kk: vv for kk, vv in a.items() if kk != "rows"} | {"seri": a["rows"]} for k, a in P["ad"].items()}
        doc = {"k": u["k"], "tr": u["tr"], "en": u["en"], "es": u["es"], "botanik": u["botanik"], "tur": u["tur"],
               "segmentler": segs, "adlar": adlar, "ispanya": {"urunler": u.get("ab", []), "seriler": es_series}}
        (out / f"{u['k']}.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        index.append({"k": u["k"], "tr": u["tr"], "en": u["en"], "tur": u["tur"], "segment": len(segs),
                      "n": max(s["n"] for s in segs), "ilk": min(s["ilk"] for s in segs), "son": max(s["son"] for s in segs),
                      "ispanya": bool(es_series)})
    (DATA / "urunler.json").write_text(json.dumps(index, ensure_ascii=False, indent=0), encoding="utf-8")

    (DATA / "_kesif").mkdir(parents=True, exist_ok=True)
    with (DATA / "_kesif" / "izmir-adlar.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["urun", "segment", "ad", "birim", "gun", "ilk", "son", "yan"])
        w.writerows(sorted(inventory))
    with (DATA / "_kesif" / "ab-adlar.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["urun", "asama", "cesit", "birim", "donem", "kayit"])
        w.writerows(sorted([*k, n] for k, n in es_inv.items()))
    print(f"{len(index)} ürün; eşleşmeyen ad: {len(unmatched)} {unmatched[:20]}")
    if unmatched:
        print("UYARI: sözlükte karşılığı olmayan adlar var (data/_kesif/izmir-adlar.csv)", file=sys.stderr)


if __name__ == "__main__":
    main()
