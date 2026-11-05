"""Keşif: HKS'de hal bazında fiyat istatistiği var mı? Yalnızca okur."""
import re, urllib.request, html as H
UA = {"User-Agent": "agrihubai-halden-anlayan/1.0 (+https://github.com/agrihubai/halden-anlayan)"}
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40) as f: return f.read().decode("utf-8", "replace")
    except Exception as e: return f"!! {e}"
def txt(h): return [H.unescape(x).strip() for x in re.findall(r">([^<>]{2,120})<", h) if x.strip()]
B = "https://www.hal.gov.tr"
f = get(B + "/Sayfalar/Fiyat-Sorgulama.aspx")
links = {H.unescape(t).strip(): u for u, t in re.findall(r"href=['\"]([^'\"]+)['\"][^>]*>\s*([^<]{3,60})<", f)}
for k, v in links.items():
    if re.search(r"(?i)istatist|fiyat|ihracat", k): print("link:", k, "->", v)
for k, v in links.items():
    if not re.search(r"(?i)istatist", k): continue
    u = v if v.startswith("http") else B + ("" if v.startswith("/") else "/") + v
    p = get(u); print("=====", k, u, len(p))
    for s in re.findall(r"<select[^>]*name=\"([^\"]+)\"[^>]*>(.*?)</select>", p, re.S):
        opts = [H.unescape(o).strip() for o in re.findall(r"<option[^>]*>([^<]*)</option>", s[1])]
        print(" select", s[0].split("$")[-1], len(opts), "| antalya:", [o for o in opts if re.search(r"(?i)antalya|kumluca|serik|gazipa|alanya|finike|demre|manavgat|ka[sş]", o)][:40], "| ilk:", opts[:10])
    print(" alanlar:", sorted(set(n.split("$")[-1] for n in re.findall(r'name="([^"]*\$[^"]*)"', p))))
    print(" etiket:", [x for x in txt(p) if 2 < len(x) < 70 and not x.startswith(("Register", "var ", "//", "_sp"))][40:110])
