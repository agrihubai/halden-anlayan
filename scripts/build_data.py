"""Ham veriden (data/ham/) panonun okuduğu dosyaları üretir.

- data/urunler.json        : ürün listesi (tür, ana sınıflar, çeşit sayıları, İspanya eşleşmesi)
- data/urun/<ürün>.json    : bir ürünün bütün çeşitleri (Türkiye, TL) ve İspanya serileri (EUR/kg)
- data/_kesif/izmir-adlar.csv, ab-adlar.csv : kaynaklardaki bütün ad ve çeşitlerin envanteri

Sınıflandırma scripts/siniflama.json dosyasından okunur. Orada kuralı olmayan adlar otomatik ayrıştırılır:
"DOMATES (SALKIM)" → ürün DOMATES, sınıf SALKIM; parantez yoksa ilk kelime ürün, gerisi sınıf sayılır.
"""
from __future__ import annotations

import csv
import gzip
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "ham"
CONF = json.loads((Path(__file__).resolve().parent / "siniflama.json").read_text(encoding="utf-8"))


def fold(s: str) -> str:
    s = (s or "").replace("ı", "i").replace("İ", "I")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.upper()).strip()


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(s).lower()).strip("-")


def title_tr(s: str) -> str:
    s = s.strip()
    words = []
    for w in re.split(r"(\s+|\(|\)|/|-)", s):
        if not w or not w.strip() or w in "()/-":
            words.append(w)
            continue
        lw = w.replace("I", "ı").replace("İ", "i").lower()
        words.append(lw[:1].replace("i", "İ").replace("ı", "I").upper() + lw[1:])
    return "".join(words)


def classify(name: str) -> tuple[str, str]:
    """(ürün adı, sınıf) döndürür."""
    n = fold(name)
    for rule in CONF.get("kurallar", []):
        if re.search(rule["kalip"], n):
            return rule["urun"], rule.get("sinif") or auto(name)[1]
    return auto(name)


def auto(name: str) -> tuple[str, str]:
    s = re.sub(r"\s+", " ", name).strip()
    n = fold(s)
    for multi in CONF.get("cok_kelimeli", []):
        if n.startswith(fold(multi)):
            rest = s[len(multi):].strip(" ()-")
            return title_tr(multi), title_tr(rest) or "Standart"
    m = re.match(r"^([^()]+?)\s*\((.+)\)\s*(.*)$", s)
    if m:
        extra = (" " + m[3]).rstrip() if m[3] else ""
        return title_tr(m[1]), title_tr(m[2] + extra)
    parts = s.split(" ", 1)
    return title_tr(parts[0]), title_tr(parts[1]) if len(parts) > 1 else "Standart"


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
    # ---- Türkiye
    series = defaultdict(list)          # ad -> [[tarih, lo, hi, avg]]
    meta = {}                           # ad -> (tür, birim sayacı)
    for p in sorted((RAW / "izmir").glob("*.csv.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                lo, hi, avg = f(r["lo"]), f(r["hi"]), f(r["avg"])
                if avg is None and lo and hi:
                    avg = round((lo + hi) / 2, 3)
                if avg is None:
                    continue
                series[r["v"]].append([r["d"], lo, hi, avg])
                t, u = meta.setdefault(r["v"], (Counter(), Counter()))
                t[r["tur"]] += 1
                u[r["u"]] += 1

    products = defaultdict(lambda: {"cesitler": [], "seriler": {}, "tur": Counter()})
    inventory = []
    for name, rows in series.items():
        rows.sort()
        urun, sinif = classify(name)
        tur = meta[name][0].most_common(1)[0][0] if meta[name][0] else ""
        birim = meta[name][1].most_common(1)[0][0] if meta[name][1] else ""
        k = slug(urun)
        P = products[k]
        P["ad"] = urun
        P["tur"][title_tr(tur) if tur else "Diğer"] += len(rows)
        P["cesitler"].append({"ad": name, "sinif": sinif, "birim": birim, "n": len(rows), "ilk": rows[0][0], "son": rows[-1][0]})
        P["seriler"][name] = rows
        inventory.append([tur, name, urun, sinif, birim, len(rows), rows[0][0], rows[-1][0]])

    # ---- İspanya
    es = defaultdict(lambda: defaultdict(dict))
    es_inv = Counter()
    p = RAW / "ispanya.json.gz"
    if p.exists():
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            for r in json.load(fh):
                es_inv[(r["urun"], r["st"], r["v"], r["u"])] += 1
                label = " · ".join(x for x in (r["st"], r["v"]) if x) or "—"
                es[r["urun"]][label][r["d"]] = round(per_kg(r["price"], r["u"]), 4)
    es_map = {slug(k): v for k, v in CONF.get("ispanya", {}).items()}

    # ---- yaz
    out = DATA / "urun"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.json"):
        old.unlink()
    index = []
    for k, P in products.items():
        P["cesitler"].sort(key=lambda c: (c["sinif"], -c["n"]))
        es_names = es_map.get(k, [])
        es_series = {}
        for en in es_names:
            for lab, d in es.get(en, {}).items():
                es_series[lab] = sorted(d.items())
        son = max(c["son"] for c in P["cesitler"])
        doc = {"urun": k, "ad": P["ad"], "tr": {"cesitler": P["cesitler"], "seriler": P["seriler"]}, "es": {"urunler": es_names, "seriler": es_series}}
        (out / f"{k}.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        siniflar = Counter(c["sinif"] for c in P["cesitler"])
        index.append({"k": k, "ad": P["ad"], "en": CONF.get("ingilizce", {}).get(k), "tur": P["tur"].most_common(1)[0][0],
                      "siniflar": sorted(siniflar), "cesit": len(P["cesitler"]), "n": sum(c["n"] for c in P["cesitler"]),
                      "son": son, "ispanya": bool(es_series)})
    index.sort(key=lambda x: (x["tur"], x["ad"]))
    (DATA / "urunler.json").write_text(json.dumps(index, ensure_ascii=False, indent=0), encoding="utf-8")

    (DATA / "_kesif").mkdir(parents=True, exist_ok=True)
    with (DATA / "_kesif" / "izmir-adlar.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tur", "ad", "urun", "sinif", "birim", "gun", "ilk", "son"])
        w.writerows(sorted(inventory))
    with (DATA / "_kesif" / "ab-adlar.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["urun", "asama", "cesit", "birim", "kayit"])
        w.writerows(sorted([*k, n] for k, n in es_inv.items()))
    print(f"{len(index)} ürün, {len(inventory)} çeşit; İspanya {len(es)} ürün")


if __name__ == "__main__":
    main()
