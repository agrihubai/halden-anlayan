"""Keşif: Antalya ilçe halleri için resmî kaynak var mı? Yalnızca okur, log'a yazar."""
import re, urllib.request, json, ssl
UA = {"User-Agent": "agrihubai-halden-anlayan/1.0 (+https://github.com/agrihubai/halden-anlayan)"}
def get(u, data=None, h=None):
    hd = dict(UA); hd.update(h or {})
    r = urllib.request.Request(u, data=data, headers=hd)
    try:
        with urllib.request.urlopen(r, timeout=40) as f: return f.read().decode("utf-8", "replace")
    except Exception as e: return f"!! {e}"
print("=== hal.gov.tr robots.txt"); print(get("https://www.hal.gov.tr/robots.txt")[:3000])
for u in ["https://antalya.bel.tr/robots.txt", "https://gezipanel.antalya.bel.tr/robots.txt"]:
    print("===", u); print(get(u)[:1500])
B = "https://gezipanel.antalya.bel.tr"
for path in ["/hal-gunluk-fiyat", "/"]:
    h = get(B + path); print("=== gezipanel", path, len(h))
    print("select:", re.findall(r"<select[^>]*>", h)[:20])
    print("option:", re.findall(r"<option[^>]*>[^<]*</option>", h)[:80])
    print("methods:", sorted(set(re.findall(r"Methods\.aspx/(\w+)", h))))
    print("hal kelimeleri:", sorted(set(re.findall(r"(?i)(kumluca|serik|gazipa[sş]a|alanya|finike|demre|manavgat|ka[sş]|elmal[iı]|korkuteli)", h))))
    for js in sorted(set(re.findall(r'src="([^"]+\.js[^"]*)"', h))):
        u = js if js.startswith("http") else B + ("" if js.startswith("/") else "/") + js
        t = get(u); m = sorted(set(re.findall(r"Methods\.aspx/(\w+)", t)))
        if m or re.search(r"(?i)hal", t[:200000]): print("  js", u, len(t), m)
for p in ["/hal-fiyat", "/hal", "/hal-gunluk-fiyatlar"]:
    print("=== gezipanel", p, get(B + p)[:200].replace("\n", " "))
# Bilinen yöntem dışında hal parametresi kabul ediyor mu?
for body in [{"tarih": "2026-11-04"}, {"tarih": "2026-11-04", "halId": 2}, {"tarih": "2026-11-04", "hal": "KUMLUCA"}]:
    print("=== POST", body, get(B + "/Methods.aspx/GetGunlukHalFiyatPdf", json.dumps(body).encode(), {"Content-Type": "application/json; charset=utf-8"})[:300])
print("=== hal.gov.tr Toptanci-Halleri")
h = get("https://www.hal.gov.tr/Sayfalar/Toptanci-Halleri.aspx?sid=7")
print([x for x in re.findall(r">([^<>]{3,80})<", h) if re.search(r"(?i)antalya|kumluca|serik|gazipa|alanya|finike|demre|manavgat", x)][:60])
