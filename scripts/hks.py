"""T.C. Ticaret Bakanlığı Hal Kayıt Sistemi (HKS) — Ürün Fiyat Detayları (Türkiye geneli, günlük).

Sayfa: https://www.hal.gov.tr/Sayfalar/FiyatDetaylari.aspx (menüde "Fiyat İstatistikleri")
Her bülten bir önceki günün verisidir ("4.11.2026 Tarihli Veriler Kullanılmıştır"). Satırlar: ürün adı, ürün cinsi,
ürün türü (Geleneksel/Konvansiyonel, İyi Tarım, Organik Tarım), ortalama fiyat (TL), işlem hacmi, birim.
Sayfanın notu: "Bilgi amaçlı olup, zaman zaman insan hatası ya da otomatik sistemlerdeki teknik arızalar nedeni ile
hatalı değerlerle karşılaşılma ihtimali bulunmaktadır."
Hal ya da il ayrımı yoktur; bütün hallerdeki bildirimlerin toplamıdır.

Yöntem: sayfa açılır (SharePoint/ASP.NET formu), tarih seçilip "Getir" ile bülten yüklenir, sonra
"Excel'e aktar (Tüm Sayfalar)" ile bütün satırlar tek dosyada alınır (UTF-16 HTML tablo).
Çıktı: data/ham/hks/YYYY.csv.gz  kolonlar: d (veri tarihi), urun, cins, tur, fiyat, hacim, birim
Geçmiş günler yeniden eskiye doğru, her çalışmada zaman bütçesi içinde doldurulur.
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import html
import http.cookiejar
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "ham" / "hks"
PAGE = "https://www.hal.gov.tr/Sayfalar/FiyatDetaylari.aspx"
UA = {"User-Agent": "agrihubai-halden-anlayan/1.0 (+https://github.com/agrihubai/halden-anlayan)"}
FIELDS = ["d", "urun", "cins", "tur", "fiyat", "hacim", "birim"]
START = dt.date(2019, 1, 1)
DEBUG: list | None = None
TUR = {"GELENEKSEL(KONVANSIYONEL)": "konvansiyonel", "IYI TARIM": "iyi-tarim", "ORGANIK TARIM": "organik"}


def plain(s: str) -> str:
    import unicodedata
    s = s.replace("ı", "i").replace("İ", "I")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


class Client:
    def __init__(self):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.prefix = None
        self.page = None

    def req(self, data: dict | None = None) -> tuple[bytes, dict]:
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        r = urllib.request.Request(PAGE, data=body, headers={**UA, **({"Content-Type": "application/x-www-form-urlencoded"} if body else {})})
        for i in range(4):
            try:
                with self.op.open(r, timeout=90) as resp:
                    return resp.read(), dict(resp.headers)
            except Exception as e:  # noqa: BLE001
                if i == 3:
                    raise
                time.sleep(5 * (i + 1))
        raise RuntimeError("ulaşılamadı")

    @staticmethod
    def form(page: str) -> dict:
        """Formdaki gönderilecek alanlar (gizli + metin + seçili radyo); düğmeler hariç."""
        out = {}
        for tag in re.findall(r"<input\b[^>]*>", page, flags=re.I):
            a = dict((k.lower(), html.unescape(v)) for k, v in re.findall(r'(\w[\w-]*)="([^"]*)"', tag))
            name, typ = a.get("name"), a.get("type", "text").lower()
            if not name or typ in ("submit", "button", "image", "checkbox"):
                continue
            if typ == "radio" and "checked" not in tag.lower():
                continue
            out[name] = a.get("value", "")
        return out

    def bulletin(self, day: dt.date) -> tuple[str | None, list[dict]]:
        """day tarihli bülten (içinde day-1 verisi). Döner: veri tarihi (ISO), satırlar."""
        page = self.page or self.req()[0].decode("utf-8", "replace")
        if not self.prefix:
            m = re.search(r'name="([^"]*\$)dateControl\$dateControlDate"', page)
            if not m:
                raise RuntimeError("tarih alanı bulunamadı")
            self.prefix = html.unescape(m.group(1))
        p = self.prefix
        f = self.form(page)
        f.update({p + "dateControl$dateControlDate": day.strftime("%d.%m.%Y"), p + "btnGet": "Getir", "__EVENTTARGET": "", "__EVENTARGUMENT": ""})
        page2 = self.req(f)[0].decode("utf-8", "replace")
        self.page = page2 if "__VIEWSTATE" in page2 else None
        f2 = self.form(page2)
        f2.update({p + "rblExcelOptions": "2", p + "btnExcel": "Excel", "__EVENTTARGET": "", "__EVENTARGUMENT": ""})
        data, headers = self.req(f2)
        if DEBUG is not None and not DEBUG:
            DEBUG.append({"gun": day.isoformat(), "sayfa1": len(page), "form1": sorted(f)[:60], "sayfa2_uzunluk": len(page2),
                          "sayfa2_bulten": re.findall(r"B[üu]lten Tarihi[^<]{0,80}", page2)[:2], "form2_tarih": f2.get(p + "dateControl$dateControlDate"),
                          "excel_basliklar": headers, "excel_bas": data[:600].decode("utf-16", "replace") if data[:2] in (b"\xff\xfe", b"\xfe\xff") else data[:600].decode("utf-8", "replace")})
        if "excel" not in headers.get("Content-Type", headers.get("content-type", "")).lower():
            raise RuntimeError("Excel dönmedi")
        t = data.decode("utf-16")
        m = re.search(r"\((\d{1,2}\.\d{1,2}\.\d{4}) Tarihli Veriler", t)
        if not m:
            return None, []
        vd = dt.datetime.strptime(m.group(1), "%d.%m.%Y").date().isoformat()
        rows = []
        for tr in re.findall(r"<tr\b[^>]*>([\s\S]*?)</tr>", t, flags=re.I):
            cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>([\s\S]*?)</td>", tr, flags=re.I)]
            if len(cells) != 6 or cells[0] == "Ürün Adı":
                continue
            try:
                price = float(cells[3].replace(".", "").replace(",", "."))
                vol = float(cells[4].replace(".", "").replace(",", "."))
            except ValueError:
                continue
            rows.append({"d": vd, "urun": cells[0], "cins": cells[1], "tur": TUR.get(plain(cells[2]), plain(cells[2]).lower()),
                         "fiyat": price, "hacim": vol, "birim": cells[5]})
        if DEBUG is not None and len(DEBUG) < 2:
            trs = re.findall(r"<tr\b[^>]*>([\s\S]*?)</tr>", t, flags=re.I)
            DEBUG.append({"vd": vd, "tr": len(trs), "satir": len(rows), "ornek": [re.sub(r"\s+", " ", x)[:300] for x in trs[1:4]],
                          "uzunluk": len(t), "son": t[-300:]})
        return vd, rows


def read_year(y: int) -> list[dict]:
    p = RAW / f"{y}.csv.gz"
    if not p.exists():
        return []
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_year(y: int, rows: list[dict]) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    rows = sorted({(r["d"], r["urun"], r["cins"], r["tur"], r["birim"]): r for r in rows}.values(),
                  key=lambda r: (r["d"], r["urun"], r["cins"], r["tur"]))
    with gzip.open(RAW / f"{y}.csv.gz", "wt", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def update(budget_sec: int = 1500) -> int:
    today = dt.date.today()
    years = {y: read_year(y) for y in range(START.year, today.year + 1)}
    have = {r["d"] for rows in years.values() for r in rows}
    empty_p = RAW / "bos-gunler.json"
    empty = set(json.loads(empty_p.read_text())) if empty_p.exists() else set()
    c, t0, new, fails = Client(), time.time(), 0, 0
    # bülten günü = veri günü + 1; yeniden eskiye
    day = today
    while day > START and time.time() - t0 < budget_sec and fails < 10:
        data_day = (day - dt.timedelta(days=1)).isoformat()
        recent = (today - day).days <= 7
        if (data_day in have or data_day in empty) and not recent:
            day -= dt.timedelta(days=1)
            continue
        try:
            vd, rows = c.bulletin(day)
            fails = 0
        except Exception as e:  # noqa: BLE001
            print(f"  hks {day}: {e}", file=sys.stderr)
            fails += 1
            c = Client()
            day -= dt.timedelta(days=1)
            continue
        if not rows:
            if not recent:
                empty.add(data_day)
        else:
            y = int(vd[:4])
            years.setdefault(y, [])
            years[y] = [r for r in years[y] if r["d"] != vd] + rows
            have.add(vd)
            new += len(rows)
        time.sleep(1)
        day -= dt.timedelta(days=1)
    for y, rows in years.items():
        if rows:
            write_year(y, rows)
    RAW.mkdir(parents=True, exist_ok=True)
    empty_p.write_text(json.dumps(sorted(empty)), encoding="utf-8")
    if DEBUG:
        (ROOT / "data" / "_kesif").mkdir(parents=True, exist_ok=True)
        (ROOT / "data" / "_kesif" / "hks-tani.json").write_text(json.dumps(DEBUG, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    first = min(have) if have else None
    print(f"  hks: {new} yeni satır; {len(have)} gün ({first} – {max(have) if have else None})")
    return sum(len(r) for r in years.values())


if __name__ == "__main__":
    update(int(sys.argv[1]) if len(sys.argv) > 1 else 1500)
