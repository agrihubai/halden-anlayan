"""Ham veriden (data/ham/) panonun okuduğu dosyaları üretir; ürün ve segmentleri sozluk/urunler.json'dan alır.

- data/urunler.json      : ürün listesi (tür, segmentler, gün sayısı, son tarih, İspanya verisi var mı)
- data/urun/<ürün>.json  : ürünün segmentleri, segment ortalama serileri, haldeki her adın serisi (TL)
                           ve İspanya serileri (EUR/kg)
- data/_kesif/izmir-adlar.csv : haldeki her adın hangi ürün ve segmente gittiği (kontrol için)
- data/_kesif/antalya-adlar.csv : Antalya listesindeki her adın eşleşmesi
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
from datetime import date, timedelta
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


ANTALYA = [(re.compile(e["ad"]), e["urun"], e["segment"]) for e in SOZLUK.get("antalya", {}).get("eslesme", [])]
BY_KEY = {u["k"]: u for u in SOZLUK["urunler"]}


def classify_antalya(fname: str):
    for rx, uk, sk in ANTALYA:
        if rx.search(fname):
            u = BY_KEY.get(uk)
            if u:
                seg = next((x for x in u["segmentler"] if x["k"] == sk), None)
                return u, seg or next((x for x in u["segmentler"] if not x["kalip"]), None)
    return classify(fname)


def read_hal(folder: str, classify_fn):
    """data/ham/<folder>/*.csv.gz → {ürün: {"u", "ad": {anahtar: {...}}, "seg": {segment: [anahtar]}}}, envanter, eşleşmeyenler."""
    series = defaultdict(dict)
    spelled = defaultdict(Counter)
    units = defaultdict(Counter)
    for p in sorted((RAW / folder).glob("*.csv.gz")):
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
    products, inventory, unmatched = {}, [], []
    for key, days in series.items():
        u, s = classify_fn(key)
        name = max(spelled[key].items(), key=lambda x: x[1])[0]
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
    return products, inventory, unmatched


def segments_of(u, P):
    """Ürünün segment serileri: o gün işlem gören ana adların ortalaması; en düşük/en yüksek o günün uç değerleri."""
    segs = []
    for s in u["segmentler"] + [{"k": "standart", "tr": "Standart", "en": "Standard", "es": "Estándar"}]:
        keys = P["seg"].get(s["k"])
        if not keys or any(x["k"] == s["k"] for x in segs):
            continue
        main_keys = [k for k in keys if not P["ad"][k]["yan"]] or keys
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
    return segs


def adlar_of(P):
    return {k: {kk: vv for kk, vv in a.items() if kk != "rows"} | {"seri": a["rows"]} for k, a in P["ad"].items()}


# ---- Almería (Junta de Andalucía): tip, kategori ve ticari pozisyon adları yıllar içinde değişti; tek biçime getirilir
POS = {"ALM.": "almacen", "ALMACEN DE AGRICULTOR": "almacen", "ALH.": "alhondiga", "ALHONDIGA": "alhondiga",
       "C.M.": "cm", "CENTRO DE MANIPULACION": "cm", "S.ALM.": "salida", "SALIDA ALMACEN": "salida",
       "ARBOL": "arbol", "EN ARBOL": "arbol", "CAM.": "campo"}
TIP = [(r"^RAMILLETE/RACIMO$|^RACIMO$", "RAMA"), (r"^CALIFORNIA (ROJO|VERDE|AMARILLO)", r"CALIFORNIA-\1"), (r"^(ROJO|VERDE|AMARILLO)-CALIFORNIA", r"CALIFORNIA-\1"),
       (r"^LAMUYO (ROJO|VERDE|AMARILLO)", r"LAMUYO-\1"), (r"^(ROJO|VERDE|AMARILLO)-LAMUYO", r"LAMUYO-\1"),
       (r"^(ROJO|VERDE)-ITALIANO|^ITALIANO[- ](ROJO|VERDE)", "ITALIANO"), (r"DULCE CONICO", "CONICO"), (r"^PERA-ROJO$", "PERA"),
       (r"^ASURCADO-VERDE$", "ASURCADO"), (r"TIPO CHERRY-", "CHERRY-"), (r"^TIPO CHERRY$", "CHERRY"), (r"^CHERRY-(.*?) ROJO$", r"CHERRY-\1"),
       (r"^HOL\. O DE ALMERIA$|^LARGO,? TIPO HOLANDES O ALMERIA$", "LARGO ALMERIA"), (r"^FRANCES$|^MEDIO LARGO O TIPO FRANCES$", "FRANCES"),
       (r"^ESPANOL$|^CORTO$|^CORTO O TIPO ESPANOL$", "ESPANOL"), (r"^LARGA SEMILARGA$|^LARGA$", "LARGA"), (r"S\.C\.$", "")]


def norm_tip(t: str) -> str:
    t = re.sub(r"\s*-\s*", "-", fold(t)).strip()
    for a, b in TIP:
        t = re.sub(a, b, t).strip()
    return t


def norm_cat(c: str) -> str:
    c = fold(c)
    return c if c in ("I", "II", "EXTRA") else "S.E."


HKS_RX = [(re.compile(e["ad"]), e["urun"], e["segment"]) for e in SOZLUK.get("hks", {}).get("eslesme", [])]


def classify_hks(fname: str):
    for rx, uk, sk in HKS_RX:
        if rx.search(fname):
            if uk is None:          # bilerek dışarıda bırakılan ad (ör. BİBERİYE)
                return None, None
            u = BY_KEY.get(uk)
            if u:
                seg = next((x for x in u["segmentler"] if x["k"] == sk), None)
                return u, seg or next((x for x in u["segmentler"] if not x["kalip"]), None)
    return classify(fname)


def read_hks():
    """HKS Türkiye geneli: {ürün: {"seg": {segment: {pazartesi: [hacim, fiyat×hacim, iyi tarım+organik hacim]}}, "ad": {segment: {ad}}}}"""
    out = defaultdict(lambda: {"seg": defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0])), "ad": defaultdict(set)})
    unmatched = Counter()
    for p in sorted((RAW / "hks").glob("*.csv.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if fold(r["birim"]) != "KG":
                    continue
                u, c = r["urun"].strip(), r["cins"].strip()
                name = u if c in (u, "DİĞER", "DIĞER", "DIGER") or fold(c) == "DIGER" else f"{u} {c}"
                key = fold(name)
                pu, s = classify_hks(key)
                if not pu:
                    unmatched[name] += 1
                    continue
                sk = (s or {"k": "standart"})["k"]
                try:
                    v, pr = float(r["hacim"]), float(r["fiyat"])
                except ValueError:
                    continue
                if v <= 0 or pr <= 0:
                    continue
                d = date.fromisoformat(r["d"])
                wk = (d - timedelta(days=d.weekday())).isoformat()
                cell = out[pu["k"]]["seg"][sk][wk]
                cell[0] += v
                cell[1] += v * pr
                if r["tur"] != "konvansiyonel":
                    cell[2] += v
                out[pu["k"]]["ad"][sk].add(name)
    return out, unmatched


def read_almeria():
    """{ürün: {(tip, kategori, pozisyon): {"seri": {pazartesi: €/kg}, "il": [iller]}}}.
    Almería ilinin serisi varsa yalnız o kullanılır; yoksa Endülüs'ün öteki illerinin haftalık medyanı.
    Tip 'NO DESIGNADO' ise yerine Junta ürün adı yazılır (ör. CEBOLLA, CEBOLLETA)."""
    umap = SOZLUK.get("almeria", {}).get("urunler", {})
    raw = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list))))   # ürün → anahtar → il → gün → [fiyat]
    for p in sorted((RAW / "junta").glob("*.csv.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r["urun"] not in umap or not r["il"]:
                    continue
                pos = POS.get(fold(r["pozisyon"]))
                if not pos:
                    continue
                cat = norm_cat(r["kategori"])
                if fold(r["tip"]).endswith(" II") and cat == "S.E.":   # 2008-09: "Liso II"
                    cat = "II"
                tip = norm_tip(re.sub(r"\s+II$", "", r["tip"]))
                if tip in ("NO DESIGNADO", "N.D.", ""):
                    tip = fold(r["urun"])
                try:
                    raw[umap[r["urun"]]][(tip, cat, pos)][r["il"]][r["d"]].append(float(r["fiyat"]))
                except ValueError:
                    pass
    out = defaultdict(dict)
    for u, keys in raw.items():
        for key, by_il in keys.items():
            iller = ["AL"] if "AL" in by_il else sorted(by_il)
            days = defaultdict(list)
            for il in iller:
                for d, v in by_il[il].items():
                    days[d].append(statistics.median(v))
            out[u][key] = {"seri": {d: round(statistics.median(v), 4) for d, v in days.items()}, "il": iller}
    return out


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
    products, inventory, unmatched = read_hal("izmir", classify)
    ant_products, ant_inventory, ant_unmatched = read_hal("antalya", classify_antalya)
    almeria = read_almeria()
    hks, hks_unmatched = read_hks()

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
        A = ant_products.get(u["k"])
        if not P:
            continue
        segs = segments_of(u, P)
        es_series = {}
        for en in u.get("ab", []):
            for lab, d in es.get(en, {}).items():
                es_series[lab] = sorted(d.items())
        al = {f"{tip} · {cat} · {pos}": sorted(v["seri"].items()) for (tip, cat, pos), v in almeria.get(u["k"], {}).items() if len(v["seri"]) >= 8}
        al_il = {f"{tip} · {cat} · {pos}": v["il"] for (tip, cat, pos), v in almeria.get(u["k"], {}).items() if len(v["seri"]) >= 8}
        H = hks.get(u["k"])
        hks_doc = None
        if H:
            hks_doc = {"kaynak": "T.C. Ticaret Bakanlığı Hal Kayıt Sistemi, Ürün Fiyat Detayları (Türkiye geneli)",
                       "segmentler": {sk: [[wk, round(c[0]), round(c[1] / c[0], 3), round(c[2] / c[0], 3)] for wk, c in sorted(w.items())]
                                      for sk, w in H["seg"].items()},
                       "adlar": {sk: sorted(v) for sk, v in H["ad"].items()}}
        haller = {}
        if A:
            haller["antalya"] = {"segmentler": segments_of(u, A), "adlar": adlar_of(A)}
        doc = {"k": u["k"], "tr": u["tr"], "en": u["en"], "es": u["es"], "botanik": u["botanik"], "tur": u["tur"],
               "segmentler": segs, "adlar": adlar_of(P), "haller": haller, "ispanya": {"urunler": u.get("ab", []), "seriler": es_series},
               "hks": hks_doc, "almeria": {"seriler": al, "iller": al_il, "kaynak": "Junta de Andalucía, Precios agrícolas semanales (CC BY 4.0)"} if al else None}
        (out / f"{u['k']}.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        index.append({"k": u["k"], "tr": u["tr"], "en": u["en"], "tur": u["tur"], "segment": len(segs),
                      "n": max(s["n"] for s in segs), "ilk": min(s["ilk"] for s in segs), "son": max(s["son"] for s in segs),
                      "ispanya": bool(es_series), "almeria": len(al), "antalya": len(haller.get("antalya", {}).get("segmentler", []))})
    (DATA / "urunler.json").write_text(json.dumps(index, ensure_ascii=False, indent=0), encoding="utf-8")

    (DATA / "_kesif").mkdir(parents=True, exist_ok=True)
    with (DATA / "_kesif" / "izmir-adlar.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["urun", "segment", "ad", "birim", "gun", "ilk", "son", "yan"])
        w.writerows(sorted(inventory))
    with (DATA / "_kesif" / "antalya-adlar.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["urun", "segment", "ad", "birim", "gun", "ilk", "son", "yan"])
        w.writerows(sorted(ant_inventory))
    with (DATA / "_kesif" / "ab-adlar.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["urun", "asama", "cesit", "birim", "donem", "kayit"])
        w.writerows(sorted([*k, n] for k, n in es_inv.items()))
    print(f"{len(index)} ürün; eşleşmeyen ad: {len(unmatched)} {unmatched[:20]}")
    print(f"HKS: {len(hks)} ürün; eşleşmeyen ad: {len(hks_unmatched)} (ilk 30: {[n for n, _ in hks_unmatched.most_common(30)]})")
    print(f"Antalya: {len(ant_products)} ürün; eşleşmeyen ad: {len(ant_unmatched)} {ant_unmatched}")
    if unmatched:
        print("UYARI: sözlükte karşılığı olmayan adlar var (data/_kesif/izmir-adlar.csv)", file=sys.stderr)


if __name__ == "__main__":
    main()
    # ürün dosyaları hazır: ıslah karnesini de hesapla (data/karne/)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import karne
    karne.build()
