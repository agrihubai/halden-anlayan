"""Keşif: Batı Akdeniz TV Gazipaşa hal fiyatları sayfasının yapısı ve robots.txt. Yalnızca okur."""
import re, urllib.request
UA = {"User-Agent": "agrihubai-halden-anlayan/1.0 (+https://github.com/agrihubai/halden-anlayan)"}
def get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as r:
        return r.status, r.headers.get("content-type"), r.read().decode("utf-8", "replace")
s, ct, t = get("https://www.batiakdeniztv.com/robots.txt"); print("=== robots", s, ct); print(t[:3000])
s, ct, h = get("https://www.batiakdeniztv.com/gazipasa-hal-fiyatlari"); print("=== sayfa", s, ct, len(h))
i = h.find("Dikenli")
print("--- tablo etiketleri:", sorted(set(re.findall(r"<(table|tbody|tr|td|th|ul|li|div class=\"[^\"]*(?:price|fiyat|hal)[^\"]*\")", h)))[:40])
for m in re.finditer(r"KASIM|EKİM|EKiM|GÜNCELLEME|SÜNCELLEME", h): print("tarih?", h[max(0,m.start()-150):m.start()+80].replace("\n"," "))
print("--- Dikenli çevresi ---"); print(h[max(0, i-3000): i+1500])
