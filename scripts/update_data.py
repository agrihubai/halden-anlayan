"""Halden Anlayan veri güncelleyici.

Üç kaynaktan veri çeker ve data/ klasörünü yeniden yazar:
  1. İzmir Büyükşehir Belediyesi hal fiyatları (yıllık CSV'ler + güncel günler için API), TL
  2. ECB günlük euro referans kurları (EUR/TRY)
  3. Avrupa Komisyonu agri-food API: İspanya sebze fiyatları (tarla, paketleme çıkışı, raf), EUR

Her kaynaktan gelen ilk yanıtların kısa bir örneği data/_kesif/ klasörüne yazılır; böylece
kaynak formatı değişirse ne geldiği repo üzerinden görülebilir.

Bir kaynak inmezse o kaynağın eski verisi korunur; yarım veri yayına çıkmaz.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PROBE = DATA / "_kesif"
UA = {"User-Agent": "agrihubai-halden-anlayan/1.0 (+https://github.com/agrihubai/halden-anlayan)"}
START_YEAR = 2006
TODAY = dt.date.today()

# Panodaki ürünler. tr: İzmir'deki ürün adında aranacak kalıp (Türkçe karakterler sadeleştirilmiş, büyük harf).
# tr_haric: aynı kalıba uyan ama başka ürün olan adlar. eu: Komisyon API'sindeki ürün adı adayları.
PRODUCTS = {
    "domates": {"tr": r"\bDOMATES", "tr_haric": r"SALCASI|KURU", "eu": ["tomatoes", "Tomatoes"]},
    "biber": {"tr": r"\bBIBER", "tr_haric": r"SALCASI|KURU|PUL|TOZ|ISOT", "eu": ["sweet peppers", "Sweet peppers", "peppers"]},
    "hiyar": {"tr": r"\bHIYAR|\bSALATALIK", "tr_haric": r"TURSU", "eu": ["cucumbers", "Cucumbers"]},
    "patlican": {"tr": r"\bPATLICAN", "tr_haric": r"KURU", "eu": ["aubergines", "Aubergines", "eggplants"]},
    "kabak": {"tr": r"\bKABAK", "tr_haric": r"BAL ?KABA|CICEG|CEKIRDEK|BALKABA|BAL KABAK", "eu": ["courgettes", "Courgettes", "zucchini"]},
}


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
            time.sleep(4 * (i + 1))
    raise RuntimeError("ulaşılamadı")


def decode(b: bytes) -> str:
    for enc in ("utf-8-sig", "cp1254", "iso-8859-9"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace")


def norm(s: str) -> str:
    """Türkçe adları karşılaştırma için sadeleştirir: büyük harf, aksansız."""
    s = (s or "").replace("ı", "i").replace("İ", "I").replace("i̇", "i")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.upper()).strip()


def num(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("€", "").replace("₺", "").replace("TL", "").strip()
    if not s:
        return None
    if "," in s and "." in s:  # 1.234,56
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_date(s: str) -> dt.date | None:
    s = str(s or "").strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    return dt.date(int(m[1]), int(m[2]), int(m[3])) if m else None


def probe(name: str, text: str, limit: int = 6000) -> None:
    PROBE.mkdir(parents=True, exist_ok=True)
    (PROBE / name).write_text(text[:limit], encoding="utf-8")


def product_of(name: str) -> str | None:
    n = norm(name)
    for key, p in PRODUCTS.items():
        if re.search(p["tr"], n) and not re.search(p["tr_haric"], n):
            return key
    return None


def pick(row: dict, *names):
    """Satırdan, adı büyük/küçük harf ve alt çizgi farkı gözetmeden eşleşen ilk alanı döndürür."""
    low = {re.sub(r"[^a-z]", "", k.lower()): v for k, v in row.items()}
    for n in names:
        v = low.get(re.sub(r"[^a-z]", "", n.lower()))
        if v not in (None, ""):
            return v
    return None


# ---------------------------------------------------------------- 1. İzmir hali
IZMIR_PKG = "https://acikveri.bizizmir.com/api/3/action/package_show?id=sebze-ve-meyve-hal-fiyatlari"
IZMIR_DAY = "https://openapi.izmir.bel.tr/api/ibb/halfiyatlari/sebzemeyve/{d}"


def izmir_rows_from_csv(text: str) -> list[dict]:
    first = text.splitlines()[0] if text else ""
    delim = ";" if first.count(";") > first.count(",") else ","
    out = []
    for r in csv.DictReader(io.StringIO(text), delimiter=delim):
        d = parse_date(pick(r, "TARIH", "tarih", "date"))
        name = pick(r, "MAL_ADI", "maladi", "urun")
        if not d or not name:
            continue
        key = product_of(name)
        if not key:
            continue
        out.append({
            "d": d.isoformat(), "p": key, "v": str(name).strip(),
            "u": str(pick(r, "BIRIM", "birim") or "").strip(),
            "lo": num(pick(r, "ASGARI_UCRET", "asgariucret", "min")),
            "hi": num(pick(r, "AZAMI_UCRET", "azamiucret", "max")),
            "avg": num(pick(r, "ORTALAMA_UCRET", "ortalamaucret", "ortalama")),
        })
    return out


def izmir_rows_from_api(j, d: dt.date) -> list[dict]:
    items = None
    if isinstance(j, list):
        items = j
    elif isinstance(j, dict):
        for k, v in j.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                items = v
                break
    out = []
    for r in items or []:
        name = pick(r, "MalAdi", "MAL_ADI", "urunAdi")
        key = product_of(name or "")
        if not key:
            continue
        out.append({
            "d": d.isoformat(), "p": key, "v": str(name).strip(),
            "u": str(pick(r, "Birim", "BIRIM") or "").strip(),
            "lo": num(pick(r, "AsgariUcret", "ASGARI_UCRET")),
            "hi": num(pick(r, "AzamiUcret", "AZAMI_UCRET")),
            "avg": num(pick(r, "OrtalamaUcret", "ORTALAMA_UCRET")),
        })
    return out


def update_izmir() -> list[dict]:
    raw_path = DATA / "ham" / "izmir.csv"
    old = []
    if raw_path.exists():
        with raw_path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                old.append({**r, "lo": num(r["lo"]), "hi": num(r["hi"]), "avg": num(r["avg"])})
    have_years = {r["d"][:4] for r in old}
    rows = {(r["d"], r["v"]): r for r in old}

    # Yıllık CSV dosyaları (geçmiş yıllar bir kez indirilir; içinde bulunulan ve önceki yıl her seferinde yenilenir)
    pkg = json.loads(get(IZMIR_PKG))
    probe("izmir-paket.json", json.dumps(pkg, ensure_ascii=False, indent=1))
    resources = pkg["result"]["resources"]
    for res in resources:
        name = res.get("name") or ""
        m = re.search(r"(20\d\d)", name)
        url = res.get("url") or ""
        fmt = (res.get("format") or "").lower()
        if not m or "csv" not in (fmt + url.lower()):
            continue
        year = m[1]
        if int(year) < START_YEAR or (year in have_years and int(year) < TODAY.year - 1):
            continue
        try:
            text = decode(get(url, timeout=300))
        except Exception as e:  # noqa: BLE001
            print(f"  İzmir {year} inmedi: {e}", file=sys.stderr)
            continue
        if year in ("2024", "2025"):
            probe(f"izmir-{year}-ornek.csv", "\n".join(text.splitlines()[:15]))
        got = izmir_rows_from_csv(text)
        print(f"  İzmir {year}: {len(got)} satır")
        for r in got:
            rows[(r["d"], r["v"])] = r

    # Yıllık dosyada olmayan son günler: günlük API
    last = max((r["d"] for r in rows.values()), default=f"{TODAY.year}-01-01")
    d = max(dt.date.fromisoformat(last) - dt.timedelta(days=7), TODAY - dt.timedelta(days=400))
    probed = False
    n_api = 0
    while d <= TODAY:
        try:
            j = json.loads(get(IZMIR_DAY.format(d=d.isoformat()), tries=2, timeout=40))
            if not probed:
                probe("izmir-api-ornek.json", json.dumps(j, ensure_ascii=False, indent=1))
                probed = True
            for r in izmir_rows_from_api(j, d):
                rows[(r["d"], r["v"])] = r
                n_api += 1
        except Exception as e:  # noqa: BLE001  (hafta sonu ve tatillerde boş dönebilir)
            if not probed:
                probe("izmir-api-hata.txt", f"{d}: {e}")
        d += dt.timedelta(days=1)
        time.sleep(0.15)
    print(f"  İzmir API: {n_api} satır")

    out = sorted(rows.values(), key=lambda r: (r["d"], r["v"]))
    if len(out) < len(old):
        raise RuntimeError(f"İzmir verisi küçüldü ({len(out)} < {len(old)})")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    with raw_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["d", "p", "v", "u", "lo", "hi", "avg"])
        w.writeheader()
        w.writerows(out)
    return out


# ---------------------------------------------------------------- 2. ECB kuru
ECB = "https://data-api.ecb.europa.eu/service/data/EXR/D.TRY.EUR.SP00.A?format=csvdata&startPeriod={y}-01-01"


def update_fx() -> dict[str, float]:
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
    return fx


# ---------------------------------------------------------------- 3. AB / İspanya
EU_BASE = "https://api.tech.ec.europa.eu/agrifood"
EU_PATHS = ["/api/fruitAndVegetable/prices", "/api/fruitandvegetable/prices", "/api/fruitAndVegetables/prices"]


def update_eu() -> list[dict]:
    try:
        spec = decode(get(EU_BASE + "/v3/api-docs/fruit_and_vegetables", tries=2))
        probe("ab-openapi.json", spec, limit=60000)
    except Exception as e:  # noqa: BLE001
        probe("ab-openapi-hata.txt", str(e))
    out = []
    begin = f"01/01/{START_YEAR}"
    end = TODAY.strftime("%d/%m/%Y")
    log = []
    for key, p in PRODUCTS.items():
        got = None
        for path in EU_PATHS:
            for prod in p["eu"]:
                q = urllib.parse.urlencode({"memberStateCodes": "ES", "products": prod, "beginDate": begin, "endDate": end})
                url = f"{EU_BASE}{path}?{q}"
                try:
                    j = json.loads(get(url, tries=2, timeout=120))
                except Exception as e:  # noqa: BLE001
                    log.append(f"{key} {url} -> {e}")
                    continue
                recs = j if isinstance(j, list) else next((v for v in j.values() if isinstance(v, list)), [])
                log.append(f"{key} {url} -> {len(recs)} kayıt")
                if recs:
                    if key == "domates":
                        probe("ab-domates-ornek.json", json.dumps(recs[:5], ensure_ascii=False, indent=1))
                    got = recs
                    break
            if got:
                break
        for r in got or []:
            if str(pick(r, "memberStateCode") or "ES").upper() != "ES":
                continue
            d = parse_date(pick(r, "beginDate", "startDate", "date"))
            price = num(pick(r, "price", "value"))
            if not d or price is None:
                continue
            unit = str(pick(r, "unit", "priceUnit") or "")
            out.append({
                "d": d.isoformat(), "p": key,
                "st": str(pick(r, "productStage", "stageName", "stage") or ""),
                "v": str(pick(r, "variety", "productName", "product") or ""),
                "u": unit, "price": price,
            })
        print(f"  AB {key}: {sum(1 for x in out if x['p'] == key)} kayıt")
    probe("ab-istekler.txt", "\n".join(log))
    old_path = DATA / "ham" / "ispanya.json"
    if not out:
        if old_path.exists():
            print("  AB: yeni veri yok, eskisi korundu", file=sys.stderr)
            return json.loads(old_path.read_text(encoding="utf-8"))
        return []
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return out


# ---------------------------------------------------------------- ana akış
def main() -> int:
    DATA.mkdir(exist_ok=True)
    status = {"guncelleme": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "kaynaklar": {}}
    for name, fn in (("izmir", update_izmir), ("kur", update_fx), ("ispanya", update_eu)):
        print(name)
        try:
            res = fn()
            status["kaynaklar"][name] = {"durum": "tamam", "kayit": len(res)}
        except Exception as e:  # noqa: BLE001
            print(f"HATA {name}: {e}", file=sys.stderr)
            status["kaynaklar"][name] = {"durum": "hata", "mesaj": str(e)[:300]}
    (DATA / "durum.json").write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
