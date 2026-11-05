"""Keşif: Antalya ilçe halleri için resmî kaynak var mı? Yalnızca okur, log'a yazar."""
import re, urllib.request, html as H
UA = {"User-Agent": "agrihubai-halden-anlayan/1.0 (+https://github.com/agrihubai/halden-anlayan)"}
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40) as f: return f.read().decode("utf-8", "replace")
    except Exception as e: return f"!! {e}"
def txt(h): return [H.unescape(x).strip() for x in re.findall(r">([^<>]{2,120})<", h) if x.strip()]
h = get("https://www.hal.gov.tr/Sayfalar/Toptanci-Halleri.aspx?sid=7")
t = txt(h)
print("=== Toptancı halleri: Antalya satırları")
for i, x in enumerate(t):
    if "HAL" in x.upper() and any("ANTALYA" in y.upper() for y in t[i:i+3]): print(" |", " ¦ ".join(t[i:i+3]))
print("sayfalama:", re.findall(r"(?i)(sayfa[^<]{0,40}|__doPostBack\('[^']+','Page\$\d+'\))", h)[:10])
f = get("https://www.hal.gov.tr/Sayfalar/Fiyat-Sorgulama.aspx")
print("=== Fiyat-Sorgulama", len(f))
for s in re.findall(r"<select[^>]*name=\"([^\"]+)\"[^>]*>(.*?)</select>", f, re.S):
    opts = [H.unescape(o) for o in re.findall(r"<option[^>]*>([^<]*)</option>", s[1])]
    print(" select", s[0], len(opts), [o for o in opts if re.search(r"(?i)antalya|kumluca|serik|gazipa|alanya|finike|demre|manavgat", o)][:30], opts[:8])
for n in sorted(set(re.findall(r'(?:name|id)="([^"]*ctl37[^"]*)"', f))): print(" alan:", n.split("$")[-1].split("_")[-1], "|", n[-60:])
for m in re.findall(r'<(?:select|table)[^>]*id="([^"]+)"', f): print(" eleman:", m[-70:])
print(" etiketler:", [x for x in txt(f) if 2 < len(x) < 60 and not x.startswith(("Register", "var ", "//"))][:120])
print(" metin:", [x for x in txt(f) if len(x) > 15][:40])
