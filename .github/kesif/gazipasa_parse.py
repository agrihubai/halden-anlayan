"""Keşif: canlı Gazipaşa sayfası scripts/gazipasa.py ile okunuyor mu? Yalnızca okur."""
import re, sys, urllib.request
sys.path.insert(0, "scripts")
import gazipasa as g
page = urllib.request.urlopen(urllib.request.Request(g.URL, headers=g.UA), timeout=60).read().decode("utf-8", "replace")
print("h1 sayısı:", len(re.findall(r"<h1", page)), [g.text(x)[:80] for x in re.findall(r"<h1[^>]*>(.*?)</h1>", page, re.S)])
d, rows = g.parse(page)
print("tarih:", d)
for r in rows: print(r)
