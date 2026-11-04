"""Hal-den Anlayan veri güncelleyici.

Beş kaynaktan veri çeker (Antalya: scripts/antalya.py, ATB endeksleri: scripts/atb.py):
  1. İzmir Büyükşehir Belediyesi hal fiyatları (yıllık CSV'ler + güncel günler için API), TL, bütün ürünler
  2. ECB günlük euro referans kurları (EUR/TRY)
  3. Avrupa Komisyonu agri-food API: İspanya meyve-sebze fiyatları (tarla, paketleme çıkışı, raf), EUR

Ham veri data/ham/ klasörüne yazılır (İzmir yıl yıl, sıkıştırılmış). Kaynaklardan gelen ilk yanıtların
kısa örnekleri data/_kesif/ klasörüne yazılır; kaynak formatı değişirse ne geldiği oradan görülür.

Bir kaynak inmezse o kaynağın eski verisi korunur; yarım veri yayına çıkmaz.
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import io
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "ham"
PROBE = DATA / "_kesif"
UA = {"User-Agent": "agrihubai-halden-anlayan/1.0 (+https://github.com/agrihubai/halden-anlayan)"}
START_YEAR = 2006
TODAY = dt.date.today()
FIELDS = ["d", "tur", "v", "u", "lo", "hi", "avg"]


# ---------------------------------------------------------------- yardımcılar
def get(url: str, tries: int = 3, timeout: int = 90) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            print(f"  tekrar ({e}): {url}", file=sys.stderr)
            time.sleep(3 * (i + 1))
    raise RuntimeError("ulaşılamadı")


def decode(b: bytes) -> str:
    for enc in ("utf-8-sig", "cp1254"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace")


def num(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("€", "").replace("₺", "").replace("TL", "").strip()
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_date(s) -> dt.date | None:
    s = str(s or "").strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def probe(name: str, text: str, limit: int = 6000) -> None:
    PROBE.mkdir(parents=True, exist_ok=True)
    (PROBE / name).write_text(text[:limit], encoding="utf-8")


def pick(row: dict, *names):
    low = {re.sub(r"[^a-z]", "", str(k).lower()): v for k, v in row.items()}
    for n in names:
        v = low.get(re.sub(r"[^a-z]", "", n.lower()))
        if v not in (None, ""):
            return v
    return None


# ---------------------------------------------------------------- 1. İzmir hali (bütün ürünler)
IZMIR_PKG = "https://acikveri.bizizmir.com/api/3/action/package_show?id=sebze-ve-meyve-hal-fiyatlari"
IZMIR_DAY = "https://openapi.izmir.bel.tr/api/ibb/halfiyatlari/sebzemeyve/{d}"


def row(d: dt.date, tur, name, unit, lo, hi, avg) -> dict | None:
    if not d or not name:
        return None
    return {"d": d.isoformat(), "tur": str(tur or "").strip(), "v": re.sub(r"\s+", " ", str(name)).strip(),
            "u": str(unit or "").strip(), "lo": num(lo), "hi": num(hi), "avg": num(avg)}


def izmir_rows_from_bulletin(text: str) -> list[dict]:
    """2025 dosyası gibi 'Günlük Bülten' biçimi: her gün için 'Bülten Tarihi' ve 'Mal Tipi' satırları,
    ardından yan yana iki blok halinde S.No; Ürün Adı; Birim; Asgari; Azami; Ortalama."""
    out = []
    day, tur = None, ""
    for cells in csv.reader(io.StringIO(text), delimiter=";"):
        cells = [c.strip() for c in cells]
        head = cells[0].lower() if cells else ""
        if head.startswith("bülten tarihi") or head.startswith("bulten tarihi"):
            day = next((parse_date(c) for c in cells[1:] if parse_date(c)), day)
            continue
        if head.startswith("mal tipi"):
            tur = next((c for c in cells[1:] if c and c != ":"), tur)
            continue
        if not day:
            continue
        vals = [c for c in cells if c != ""]
        i = 0
        while i < len(vals):
            # S.No (tam sayı) + ad + birim + üç fiyat
            if re.fullmatch(r"\d+", vals[i]) and i + 5 < len(vals) and num(vals[i + 1]) is None and num(vals[i + 2]) is None:
                lo, hi, avg = num(vals[i + 3]), num(vals[i + 4]), num(vals[i + 5])
                if None not in (lo, hi, avg):
                    x = row(day, tur, vals[i + 1], vals[i + 2], lo, hi, avg)
                    if x:
                        out.append(x)
                    i += 6
                    continue
            i += 1
    return out


def izmir_rows_from_csv(text: str) -> list[dict]:
    first = text.splitlines()[0] if text else ""
    if "TARIH" not in first.upper():
        return izmir_rows_from_bulletin(text)
    delim = ";" if first.count(";") > first.count(",") else ","
    out = []
    for r in csv.DictReader(io.StringIO(text), delimiter=delim):
        x = row(parse_date(pick(r, "TARIH", "date")), pick(r, "MAL_TURU", "maltipadi"), pick(r, "MAL_ADI", "maladi"),
                pick(r, "BIRIM"), pick(r, "ASGARI_UCRET"), pick(r, "AZAMI_UCRET"), pick(r, "ORTALAMA_UCRET"))
        if x:
            out.append(x)
    return out


def izmir_rows_from_api(j, d: dt.date) -> list[dict]:
    items = j if isinstance(j, list) else next((v for v in (j or {}).values() if isinstance(v, list)), [])
    out = []
    for r in items:
        if not isinstance(r, dict):
            continue
        x = row(d, pick(r, "MalTipAdi", "MAL_TURU", "MalTuru"), pick(r, "MalAdi", "MAL_ADI"), pick(r, "Birim", "BIRIM"),
                pick(r, "AsgariUcret", "ASGARI_UCRET"), pick(r, "AzamiUcret", "AZAMI_UCRET"), pick(r, "OrtalamaUcret", "ORTALAMA_UCRET"))
        if x:
            out.append(x)
    return out


def read_year(year: int) -> list[dict]:
    p = RAW / "izmir" / f"{year}.csv.gz"
    if not p.exists():
        return []
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_year(year: int, rows: list[dict]) -> None:
    p = RAW / "izmir" / f"{year}.csv.gz"
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: (r["d"], r["v"]))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    with gzip.GzipFile(p, "wb", mtime=0) as f:  # mtime=0: aynı veri aynı dosyayı üretir, gereksiz commit olmaz
        f.write(buf.getvalue().encode("utf-8"))


def update_izmir() -> int:
    years = {}
    pkg = json.loads(get(IZMIR_PKG))
    probe("izmir-paket.json", json.dumps(pkg, ensure_ascii=False, indent=1), limit=20000)
    for res in pkg["result"]["resources"]:
        m = re.search(r"(20\d\d)", res.get("name") or "")
        url = res.get("url") or ""
        if m and "csv" in ((res.get("format") or "") + url).lower():
            years[int(m[1])] = url

    total = 0
    for year in sorted(years):
        if year < START_YEAR:
            continue
        p = RAW / "izmir" / f"{year}.csv.gz"
        if p.exists() and year < TODAY.year - 1:
            continue  # geçmiş yıllar bir kez indirilir
        try:
            text = decode(get(years[year], timeout=300))
        except Exception as e:  # noqa: BLE001
            print(f"  İzmir {year} inmedi: {e}", file=sys.stderr)
            continue
        if year >= TODAY.year - 2:
            probe(f"izmir-{year}-ornek.csv", "\n".join(text.splitlines()[:12]))
        got = izmir_rows_from_csv(text)
        old = read_year(year)
        merged = {(r["d"], r["v"]): r for r in old}
        merged.update({(r["d"], r["v"]): r for r in got})
        if len(merged) < len(old):
            print(f"  İzmir {year}: veri küçüldü, eski korundu", file=sys.stderr)
            continue
        write_year(year, list(merged.values()))
        total += len(got)
        print(f"  İzmir {year}: {len(got)} satır")

    # Yıllık dosyada henüz olmayan günler: günlük API (paralel, kısa zaman aşımı)
    last = None
    for y in range(TODAY.year, START_YEAR - 1, -1):
        rows = read_year(y)
        if rows:
            last = max(r["d"] for r in rows)
            break
    start = max(dt.date.fromisoformat(last) - dt.timedelta(days=3), TODAY - dt.timedelta(days=370)) if last else TODAY - dt.timedelta(days=370)
    days = [start + dt.timedelta(days=i) for i in range((TODAY - start).days + 1)]

    def fetch_day(d):
        try:
            return d, json.loads(get(IZMIR_DAY.format(d=d.isoformat()), tries=1, timeout=20)), None
        except Exception as e:  # noqa: BLE001
            return d, None, str(e)

    # Önce birkaç günle API'nin çalıştığını sına; çalışmıyorsa yüzlerce isteği boşuna bekleme
    test = [fetch_day(d) for d in days[-5:]]
    ok = [t for t in test if t[1]]
    probe("izmir-api-ornek.json", json.dumps(ok[0][1], ensure_ascii=False, indent=1) if ok else "\n".join(f"{d}: {e}" for d, _, e in test))
    if not ok:
        print("  İzmir API yanıt vermiyor, günlük çekim atlandı", file=sys.stderr)
        return total
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(fetch_day, days[:-5])) + test
    by_year: dict[int, list[dict]] = {}
    for d, j, _ in results:
        if j:
            by_year.setdefault(d.year, []).extend(izmir_rows_from_api(j, d))
    for y, got in by_year.items():
        old = read_year(y)
        merged = {(r["d"], r["v"]): r for r in old}
        # yıllık dosyadaki satır API'ninkinden önceliklidir
        for r in got:
            merged.setdefault((r["d"], r["v"]), r)
        write_year(y, list(merged.values()))
        total += len(got)
        print(f"  İzmir API {y}: {len(got)} satır")
    return total


# ---------------------------------------------------------------- 2. ECB kuru
ECB = "https://data-api.ecb.europa.eu/service/data/EXR/D.TRY.EUR.SP00.A?format=csvdata&startPeriod={y}-01-01"


def update_fx() -> int:
    text = decode(get(ECB.format(y=START_YEAR)))
    probe("ecb-ornek.csv", "\n".join(text.splitlines()[:5]))
    fx = {}
    for r in csv.DictReader(io.StringIO(text)):
        v = num(r.get("OBS_VALUE"))
        if v:
            fx[r["TIME_PERIOD"]] = round(v, 4)
    if len(fx) < 4000:
        raise RuntimeError(f"ECB: beklenenden az kur ({len(fx)})")
    print(f"  ECB: {len(fx)} gün, son {max(fx)} = {fx[max(fx)]}")
    (DATA / "kur-eur-try.json").write_text(json.dumps(sorted(fx.items()), separators=(",", ":")), encoding="utf-8")
    return len(fx)


# ---------------------------------------------------------------- 3. AB / İspanya (bütün ürünler)
EU_BASE = "https://api.tech.ec.europa.eu/agrifood/api/fruitAndVegetable/pricesSupplyChain"


def eu_get(path: str, params: dict | None = None):
    url = EU_BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    try:
        return json.loads(get(url, tries=1, timeout=60)), url
    except urllib.error.HTTPError as e:
        if e.code == 404:  # API "bu parametrelerle sonuç yok" için 404 döndürüyor
            return [], url
        raise


def update_eu() -> int:
    lists = {}
    for name in ("products", "productStages", "varieties"):
        try:
            lists[name], _ = eu_get("/" + name)
        except Exception as e:  # noqa: BLE001
            lists[name] = []
            probe(f"ab-{name}-hata.txt", str(e))
    probe("ab-listeler.json", json.dumps(lists, ensure_ascii=False, indent=1), limit=60000)
    products = [p if isinstance(p, str) else (pick(p, "product", "name", "productName") or "") for p in lists["products"]]
    products = [p for p in products if p]
    if not products:
        raise RuntimeError("AB: ürün listesi alınamadı")
    # Daha önce indirilenler korunur; her ürün için sadece son 8 hafta yeniden istenir.
    p = RAW / "ispanya.json.gz"
    old = []
    if p.exists():
        with gzip.open(p, "rt", encoding="utf-8") as f:
            old = json.load(f)
    last = {}
    for r in old:
        last[r["urun"]] = max(last.get(r["urun"], ""), r["d"])
    # Önce hiç indirilmemiş ürünler, onların içinde de sera ürünleri
    first = ["Tomatoes", "Peppers", "Cucumbers", "Egg Plants", "Courgettes"]
    products.sort(key=lambda x: (x in last, x not in first, x))
    log = []
    fresh: dict[str, list] = {}
    since: dict[str, str] = {}
    end = TODAY.strftime("%d/%m/%Y")
    t_end = time.time() + 12 * 60  # AB için en fazla 12 dakika; kalan ürünler bir sonraki çalıştırmaya kalır
    for prod in products:
        if time.time() > t_end:
            log.append("süre doldu, kalan ürünler bir sonraki çalıştırmaya kaldı")
            break
        if prod in last:
            b = dt.date.fromisoformat(last[prod]) - dt.timedelta(weeks=8)
        else:
            b = dt.date(START_YEAR, 1, 1)
        params = {"memberStateCodes": "ES", "products": prod, "beginDate": b.strftime("%d/%m/%Y"), "endDate": end}
        recs = None
        for attempt in range(3):
            try:
                recs, url = eu_get("", params)
                log.append(f"{url} -> {len(recs)}")
                break
            except Exception as e:  # noqa: BLE001
                log.append(f"{prod} deneme {attempt + 1}: {e}")
                time.sleep(20 if "429" in str(e) else 5)
        time.sleep(1)  # API hız sınırına takılmamak için
        if recs is None:
            continue
        rows = []
        for r in recs:
            if str(pick(r, "memberStateCode") or "ES").upper() != "ES":
                continue
            d = parse_date(pick(r, "beginDate"))
            price = num(pick(r, "price"))
            if not d or price is None:
                continue
            rows.append({"d": d.isoformat(), "urun": prod, "st": str(pick(r, "productStage") or ""),
                         "v": str(pick(r, "variety") or ""), "u": str(pick(r, "unit") or ""),
                         "per": str(pick(r, "periodType") or ""), "price": price})
        fresh[prod] = rows
        since[prod] = b.isoformat()
    probe("ab-istekler.txt", "\n".join(log), limit=30000)
    out = [r for r in old if not (r["urun"] in fresh and r["d"] >= since[r["urun"]])]
    for rows in fresh.values():
        out += rows
    if not out:
        raise RuntimeError("AB: hiç kayıt gelmedi (data/_kesif/ab-istekler.txt)")
    out.sort(key=lambda r: (r["urun"], r["d"], r["st"], r["v"], r["per"]))
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.GzipFile(p, "wb", mtime=0) as f:
        f.write(json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    print(f"  AB: {len(out)} kayıt, {len({r['urun'] for r in out})} ürün; bu sefer {len(fresh)} ürün istendi")
    return len(out)


# ---------------------------------------------------------------- ana akış
def main() -> int:
    DATA.mkdir(exist_ok=True)
    status = {"guncelleme": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "kaynaklar": {}}
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import antalya
    import atb
    for name, fn in (("kur", update_fx), ("izmir", update_izmir), ("antalya", antalya.update), ("atb", atb.update), ("ispanya", update_eu)):
        print(name, flush=True)
        t0 = time.time()
        try:
            n = fn()
            status["kaynaklar"][name] = {"durum": "tamam", "kayit": n, "sure_sn": round(time.time() - t0)}
        except Exception as e:  # noqa: BLE001
            print(f"HATA {name}: {e}", file=sys.stderr)
            status["kaynaklar"][name] = {"durum": "hata", "mesaj": str(e)[:300], "sure_sn": round(time.time() - t0)}
    (DATA / "durum.json").write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
