"""Keşif: Junta yıllık dosyasında 8 sebze dışında hangi ürünler var? Yalnızca okur."""
import sys, collections, urllib.request; sys.path.insert(0, "scripts")
import junta as Jn
class Hepsi(set):
    def __contains__(self, x): return True
Jn.URUNLER = Hepsi()
xlrd = Jn.xlrd_mod(); links = Jn.file_links(); y = max(k for k in links if k <= 2025)
data = urllib.request.urlopen(urllib.request.Request(links[y], headers=Jn.UA), timeout=120).read()
wb = xlrd.open_workbook(file_contents=data); rows = []
for sh in wb.sheets(): rows += Jn.parse_sheet(sh, y)[0]
print("yıl", y, "satır", len(rows))
c = collections.defaultdict(lambda: [0, set(), set()])
for r in rows:
    k = (r["urun"], r["tip"]); c[k][0] += 1; c[k][1].add(r["il"]); c[k][2].add(r["pozisyon"])
for (u, t), (n, il, pz) in sorted(c.items()): print(f"{u} | {t} | {n} | {','.join(sorted(il))} | {','.join(sorted(pz))}")
