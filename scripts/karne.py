"""Islah karnesi: data/urun/<ürün>.json dosyalarından segment göstergelerini hesaplar.

Çıktı:
- data/karne/<ürün>.json : ürünün her segmenti için altı gösterge (ayrıntılı seriler dahil)
- data/karne/_ozet.json  : bütün ürün ve segmentlerin özet satırları (karşılaştırma tablosu için)

Göstergeler (hepsi oran; TL enflasyonu ve kur oranlarda büyük ölçüde sadeleşir):
  prim   : segmentin haftalık fiyatı / ürünün referans segmentinin aynı haftaki fiyatı
  sezon  : haftalık fiyat / ortalanmış 53 haftalık geometrik ortalama; yılın haftalarına göre medyan
  sok    : haftalık fiyat değişimi, segmentin kendi oynaklığına göre aşırı yükselişler (robust z > 3)
  makas  : aynı haldeki adın en yüksek / en düşük fiyatı (kalite ve boyut farkının vekili)
  yeni   : segmentin ve adlarının halde ilk görüldüğü tarih, son 52 haftadaki işlem sıklığı
  es     : İspanya (Avrupa Komisyonu, paketleme çıkışı) ile fiyat düzeyi, prim ve sezon şekli karşılaştırması
Hacim verisi yoktur: hiçbir gösterge pazarın büyüklüğünü söylemez.
"""
from __future__ import annotations

import json
import math
import re
import statistics
from bisect import bisect_right
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SOZLUK = json.loads((ROOT / "sozluk" / "urunler.json").read_text(encoding="utf-8"))

YIL = 10          # sezon ve şok için bakılan yıl sayısı
Z_SOK = 3.0       # şok eşiği (robust z)
MIN_HAFTA = 13    # bir medyan için en az hafta


def d_(s: str) -> date:
    return date.fromisoformat(s)


def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def r3(x, n=3):
    return None if x is None or not math.isfinite(x) else round(x, n)


def weekly(seri, value=lambda r: r[3]):
    """Günlük satırlar [tarih, lo, hi, ort] → {pazartesi: (ortalama, gün sayısı)}."""
    b = defaultdict(list)
    for r in seri:
        v = value(r)
        if v:
            b[monday(d_(r[0]))].append(v)
    return {k: (statistics.fmean(v), len(v)) for k, v in sorted(b.items())}


def window(w: dict, end: date, days: int):
    start = end - timedelta(days=days)
    return {k: v for k, v in w.items() if start < k <= end}


def isoweek(d: date) -> int:
    return min(d.isocalendar()[1], 52)


# ---------------------------------------------------------------- göstergeler
def prim(seg_w, ref_w, last: date):
    common = sorted(set(seg_w) & set(ref_w))
    ratio = {k: seg_w[k][0] / ref_w[k][0] for k in common if ref_w[k][0] > 0}
    if len(ratio) < MIN_HAFTA:
        return None
    yearly = defaultdict(list)
    for k, v in ratio.items():
        yearly[k.year].append(v)
    yillar = [[y, r3(med(v)), len(v)] for y, v in sorted(yearly.items()) if len(v) >= MIN_HAFTA]
    cur = [v for k, v in ratio.items() if last - timedelta(days=364) < k <= last]
    end5 = last - timedelta(days=5 * 365)
    old = [v for k, v in ratio.items() if end5 - timedelta(days=364) < k <= end5]
    c, o = (med(cur) if len(cur) >= MIN_HAFTA else None), (med(old) if len(old) >= MIN_HAFTA else None)
    return {"simdi": r3(c), "simdi_hafta": len(cur), "bes_yil_once": r3(o), "degisim": r3(c / o - 1) if c and o else None,
            "yillar": yillar}


def season_ratios(w: dict, last: date):
    """Her hafta için fiyat / ortalanmış 53 haftalık geometrik ortalama (son YIL yıl)."""
    start = last - timedelta(days=365 * YIL + 182)
    keys = [k for k in w if k >= start - timedelta(days=182)]
    logs = {k: math.log(w[k][0]) for k in keys if w[k][0] > 0}
    out = {}
    ks = sorted(logs)
    for i, k in enumerate(ks):
        if k < start:
            continue
        lo, hi = k - timedelta(days=182), k + timedelta(days=182)
        vals = [logs[j] for j in ks if lo <= j <= hi]
        if len(vals) >= 26:
            out[k] = math.exp(logs[k] - statistics.fmean(vals))
    return out


def sezon(w: dict, last: date):
    rat = season_ratios(w, last)
    by_wk = defaultdict(list)
    for k, v in rat.items():
        by_wk[isoweek(k)].append(v)
    nyears = len({k.year for k in rat})
    prof = [med(by_wk.get(i, [])) if len(by_wk.get(i, [])) >= 3 else None for i in range(1, 53)]
    if sum(p is not None for p in prof) < 26:
        return None
    # 3 haftalık dairesel düzeltme (boş haftalar atlanır)
    sm = []
    for i in range(52):
        v = [prof[(i + j) % 52] for j in (-1, 0, 1) if prof[(i + j) % 52] is not None]
        sm.append(r3(statistics.fmean(v)) if v and prof[i] is not None else None)

    def best(sign):
        cand = []
        for i in range(52):
            v = [sm[(i + j) % 52] for j in range(4)]
            if all(x is not None for x in v):
                cand.append((statistics.fmean(v), i))
        if not cand:
            return None
        m, i = max(cand) if sign > 0 else min(cand)
        return {"hafta": [i + 1, (i + 3) % 52 + 1], "oran": r3(m)}

    tepe, dip = best(1), best(-1)
    # tutarlılık: her yılın en pahalı ayı, profilin tepe ayına ±1 ay mı?
    yearly = defaultdict(lambda: defaultdict(list))
    for k, v in rat.items():
        yearly[k.year][k.month].append(v)
    pm = None
    if tepe:
        pm = (date.fromisocalendar(2021, tepe["hafta"][0], 1) + timedelta(days=10)).month
    hits = n = 0
    for y, months in yearly.items():
        if len(months) < 9:
            continue
        top = max(months, key=lambda m: statistics.fmean(months[m]))
        n += 1
        if pm and min((top - pm) % 12, (pm - top) % 12) <= 1:
            hits += 1
    aktif = sum(p is not None for p in prof)
    return {"profil": sm, "yil": nyears, "tepe": tepe, "dip": dip,
            "genlik": r3(tepe["oran"] / dip["oran"]) if tepe and dip and dip["oran"] else None,
            "tutarlilik": [hits, n], "hafta_kapsami": aktif}


def donem(w: dict, last: date):
    """Mevsimlik segmentler: haftalara göre bulunurluk ve sezon başı (turfanda) / sonu (geççi) primi."""
    start = last - timedelta(days=365 * YIL)
    ks = [k for k in sorted(w) if k >= start]
    if not ks:
        return None
    years = max(1, len({k.year for k in ks}))
    var = [0] * 52
    seen = defaultdict(set)
    for k in ks:
        seen[isoweek(k)].add(k.year)
    var = [r3(len(seen.get(i, ())) / years, 2) for i in range(1, 53)]
    # sezonlar: arada en çok 4 hafta boşluk olan ardışık haftalar
    eps, cur = [], [ks[0]]
    for a, b in zip(ks, ks[1:]):
        if (b - a).days > 35:
            eps.append(cur); cur = []
        cur.append(b)
    eps.append(cur)
    eps = [e for e in eps if len(e) >= 6 and e[-1] < last - timedelta(days=21)]   # süren sezon sayılmaz
    bas, son = [], []
    for e in eps:
        m = statistics.median(w[k][0] for k in e)
        if m > 0:
            bas.append(statistics.fmean(w[k][0] for k in e[:3]) / m)
            son.append(statistics.fmean(w[k][0] for k in e[-3:]) / m)
    out = {"bulunurluk": var, "sezon_sayisi": len(eps)}
    if len(eps) >= 3:
        out |= {"turfanda": r3(med(bas)), "gecci": r3(med(son)),
                "sure_hafta": round(statistics.median(len(e) for e in eps)),
                "baslangic_hafta": round(statistics.median(isoweek(e[0]) for e in eps))}
    return out


def sok(w: dict, last: date):
    start = last - timedelta(days=365 * YIL)
    ks = [k for k in sorted(w) if k >= start]
    ch = []
    for a, b in zip(ks, ks[1:]):
        if (b - a).days == 7 and w[a][1] >= 2 and w[b][1] >= 2 and w[a][0] > 0 and w[b][0] > 0:
            ch.append((b, math.log(w[b][0] / w[a][0])))
    if len(ch) < 52:
        return None
    vals = [c for _, c in ch]
    m = statistics.median(vals)
    mad = statistics.median(abs(v - m) for v in vals) * 1.4826
    if not mad:
        return None
    up = [(k, c) for k, c in ch if (c - m) / mad > Z_SOK]
    aylar = [[0, 0] for _ in range(12)]          # [şok sayısı, farklı yıl sayısı]
    yrs = defaultdict(set)
    for k, c in up:
        aylar[k.month - 1][0] += 1
        yrs[k.month].add(k.year)
    for mth, s in yrs.items():
        aylar[mth - 1][1] = len(s)
    tekrar = [i + 1 for i, (cnt, ny) in enumerate(aylar) if ny >= 3]
    return {"esik": r3(math.exp(m + Z_SOK * mad) - 1), "hafta": len(ch), "sayi": len(up),
            "aylar": aylar, "tekrar": tekrar,
            "son": [[k.isoformat(), r3(math.exp(c) - 1)] for k, c in up[-8:]]}


def makas(doc, seg, last: date):
    """Segmentin ana adlarında günlük en yüksek / en düşük fiyat oranı (adlar arası günlük medyan)."""
    by_day = defaultdict(list)
    for key in seg["adlar"]:
        a = doc["adlar"][key]
        if a["yan"]:
            continue
        for d, lo, hi, avg in a["seri"]:
            if lo and hi and hi >= lo > 0:
                by_day[d].append(hi / lo)
    daily = {d_(d): statistics.median(v) for d, v in by_day.items()}
    cur = [v for k, v in daily.items() if last - timedelta(days=364) < k <= last]
    end5 = last - timedelta(days=5 * 365)
    old = [v for k, v in daily.items() if end5 - timedelta(days=364) < k <= end5]
    if len(cur) < 30:
        return None
    flat = sum(1 for v in cur if v == 1) / len(cur)
    yearly = defaultdict(list)
    for k, v in daily.items():
        yearly[k.year].append(v)
    return {"simdi": r3(med(cur)), "bes_yil_once": r3(med(old)) if len(old) >= 30 else None,
            "tek_fiyat_payi": r3(flat, 2), "yillar": [[y, r3(med(v))] for y, v in sorted(yearly.items()) if len(v) >= 30]}


def kalite_ciftleri(doc):
    """Aynı adın 1. ve 2. kalitesi (ör. BIBER KIRMIZI / BIBER KIRMIZI II) aynı gün işlem görmüşse oran."""
    out = []
    for key, a in doc["adlar"].items():
        if not re.search(r"\bII\b", key):
            continue
        base = re.sub(r"\s*\bII\b", "", key).strip()
        b = doc["adlar"].get(base)
        if not b:
            continue
        bd = {r[0]: r[3] for r in b["seri"] if r[3]}
        pairs = [(r[0], bd[r[0]] / r[3]) for r in a["seri"] if r[3] and r[0] in bd]
        if len(pairs) >= 20:
            out.append({"ad1": b["ad"], "ad2": a["ad"], "oran": r3(med([p[1] for p in pairs])), "gun": len(pairs),
                        "ilk": pairs[0][0], "son": pairs[-1][0], "segment": b["segment"]})
    return out


def yeni(doc, seg, w: dict, last: date):
    adlar = sorted(({"ad": doc["adlar"][k]["ad"], "ilk": doc["adlar"][k]["ilk"], "son": doc["adlar"][k]["son"],
                     "yan": doc["adlar"][k]["yan"]} for k in seg["adlar"]), key=lambda a: a["ilk"])
    son52 = sum(1 for k in w if last - timedelta(days=364) < k <= last)
    gecen = (last - d_(seg["son"])).days
    durum = "sessiz" if gecen > 365 else ("duzenli" if son52 >= 40 else ("mevsimlik" if son52 >= 8 else "seyrek"))
    return {"ilk": seg["ilk"], "son": seg["son"], "son52": son52, "durum": durum,
            "yeni": seg["ilk"] >= "2012-01-01", "adlar": adlar}


# ---------------------------------------------------------------- İspanya
def es_series(doc, ab_name):
    """AB çeşidinin paketleme çıkışı haftalık serisi {pazartesi: (€/kg, 1)}."""
    for lab, rows in (doc.get("ispanya") or {}).get("seriler", {}).items():
        st, _, v = lab.partition(" · ")
        if st == "Paketleme çıkışı" and v == ab_name:
            return {monday(d_(d)): (p, 1) for d, p in rows if p}
    return {}


def es_all_types(doc):
    for lab in (doc.get("ispanya") or {}).get("seriler", {}):
        st, _, v = lab.partition(" · ")
        if st == "Paketleme çıkışı" and "All types" in v:
            return v
    return None


def es_karsilastir(doc, seg, seg_eur, ref, ref_eur, ref_ab, last, tr_sezon):
    ab = (seg.get("ab") or [None])[0]
    tam = bool(ab)
    if not ab and seg["k"] == ref:
        ab = es_all_types(doc)
    if not ab:
        return None
    es = es_series(doc, ab)
    if len(es) < MIN_HAFTA:
        return None
    common = sorted(set(es) & set(seg_eur))
    if len(common) < MIN_HAFTA:
        return {"ab": ab, "tam": tam, "ortak_hafta": len(common), "es_ilk": min(es).isoformat(), "es_son": max(es).isoformat()}
    end = max(common)
    win = [k for k in common if end - timedelta(days=364) < k <= end]
    duzey = med([seg_eur[k][0] / es[k][0] for k in win]) if len(win) >= MIN_HAFTA else None
    out = {"ab": ab, "tam": tam, "ortak_hafta": len(common), "donem": [min(win).isoformat(), end.isoformat()] if win else None,
           "tr_eur": r3(med([seg_eur[k][0] for k in win]), 2) if win else None,
           "es_eur": r3(med([es[k][0] for k in win]), 2) if win else None, "duzey": r3(duzey),
           "es_ilk": min(es).isoformat(), "es_son": max(es).isoformat()}
    # prim karşılaştırması: İspanya'da da referansın karşılığı varsa
    es_ref = es_series(doc, ref_ab) if ref_ab and seg["k"] != ref else {}
    if es_ref:
        cw = [k for k in set(es) & set(es_ref) & set(seg_eur) & set(ref_eur) if end - timedelta(days=364) < k <= end]
        if len(cw) >= MIN_HAFTA:
            out["prim_es"] = r3(med([es[k][0] / es_ref[k][0] for k in cw]))
            out["prim_tr"] = r3(med([seg_eur[k][0] / ref_eur[k][0] for k in cw]))
            out["prim_hafta"] = len(cw)
    es_sz = sezon(es, max(es))
    if es_sz and tr_sezon:
        a, b = tr_sezon["profil"], es_sz["profil"]
        pts = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
        if len(pts) >= 26:
            out["sezon_es"] = {"profil": es_sz["profil"], "tepe": es_sz["tepe"], "dip": es_sz["dip"], "genlik": es_sz["genlik"], "yil": es_sz["yil"]}
            mx, my = statistics.fmean(p[0] for p in pts), statistics.fmean(p[1] for p in pts)
            sx = math.sqrt(sum((p[0] - mx) ** 2 for p in pts)); sy = math.sqrt(sum((p[1] - my) ** 2 for p in pts))
            out["sezon_benzerlik"] = r3(sum((p[0] - mx) * (p[1] - my) for p in pts) / (sx * sy), 2) if sx and sy else None
    return out


# ---------------------------------------------------------------- ana akış
def load_fx():
    rows = json.loads((DATA / "kur-eur-try.json").read_text(encoding="utf-8"))
    return [d_(d) for d, _ in rows], [v for _, v in rows]


def build():
    fx_d, fx_v = load_fx()

    def rate(s):
        i = bisect_right(fx_d, d_(s)) - 1
        return fx_v[i] if i >= 0 else None

    sz_index = {u["k"]: u for u in SOZLUK["urunler"]}
    out_dir = DATA / "karne"
    out_dir.mkdir(exist_ok=True)
    for old in out_dir.glob("*.json"):
        old.unlink()
    ozet = []
    for p in sorted((DATA / "urun").glob("*.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        segs = [s for s in doc["segmentler"] if s["n"] >= 30]
        if not segs:
            continue
        last = max(d_(s["son"]) for s in segs)
        unit = statistics.mode(s["birim"] for s in segs)
        W = {s["k"]: weekly(s["seri"]) for s in segs}
        # referans: aynı birimde, son 5 yılda en çok haftada işlem gören segment ("diğer" hariç)
        cand = [s for s in segs if s["birim"] == unit and s["k"] != "diger"] or [s for s in segs if s["birim"] == unit]
        ref = max(cand, key=lambda s: (len(window(W[s["k"]], last, 5 * 365)), s["n"]))["k"]
        ref_ab = (next(s for s in segs if s["k"] == ref).get("ab") or [None])[0] or es_all_types(doc)
        sz_segs = {s["k"]: s for s in sz_index.get(doc["k"], {}).get("segmentler", [])}
        eur_w = {}
        for s in segs:
            if s["birim"] == "KG":
                eur_w[s["k"]] = weekly(s["seri"], lambda r: (r[3] / rate(r[0])) if r[3] and rate(r[0]) else None)
        rows = []
        for s in segs:
            w = W[s["k"]]
            sz = sezon(w, last)
            k = {"k": s["k"], "tr": s["tr"], "en": s["en"], "birim": s["birim"],
                 "ab_uyum": sz_segs.get(s["k"], {}).get("ab_uyum"),
                 "prim": prim(w, W[ref], last) if s["k"] != ref and s["birim"] == unit else None,
                 "sezon": sz, "donem": donem(w, last), "sok": sok(w, last), "makas": makas(doc, s, last), "yeni": yeni(doc, s, w, last),
                 "es": es_karsilastir(doc, s, eur_w.get(s["k"], {}), ref, eur_w.get(ref, {}), ref_ab, last, sz)
                 if s["birim"] == "KG" else None}
            rows.append(k)
            pr, es = k["prim"] or {}, k["es"] or {}
            ozet.append({"u": doc["k"], "utr": doc["tr"], "uen": doc["en"], "tur": doc["tur"], "s": s["k"], "str": s["tr"], "sen": s["en"],
                         "ref": s["k"] == ref, "prim": pr.get("simdi"), "prim_deg": pr.get("degisim"),
                         "genlik": (sz or {}).get("genlik"), "turfanda": (k["donem"] or {}).get("turfanda"), "tepe": ((sz or {}).get("tepe") or {}).get("hafta"),
                         "sok": (k["sok"] or {}).get("sayi"), "sok_hafta": (k["sok"] or {}).get("hafta"),
                         "makas": (k["makas"] or {}).get("simdi"), "ilk": s["ilk"], "durum": k["yeni"]["durum"],
                         "yeni": k["yeni"]["yeni"], "es_duzey": es.get("duzey"), "es_tam": es.get("tam"),
                         "es_benzer": es.get("sezon_benzerlik")})
        karne = {"k": doc["k"], "tr": doc["tr"], "en": doc["en"], "son": last.isoformat(), "birim": unit, "referans": ref,
                 "ref_ab": ref_ab, "yil": YIL, "z": Z_SOK, "segmentler": rows, "kalite": kalite_ciftleri(doc)}
        (out_dir / p.name).write_text(json.dumps(karne, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (out_dir / "_ozet.json").write_text(json.dumps(ozet, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Islah karnesi: {len({o['u'] for o in ozet})} ürün, {len(ozet)} segment")


if __name__ == "__main__":
    build()
