"""Geçici keşif: Junta de Andalucía Observatorio de Precios sayfalarını ve açık veri kaydını indirip
data/_kesif/junta-*.txt olarak saklar (biçimi görmek için). Veri yayını değildir; keşif bitince kaldırılacak."""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROBE = ROOT / "data" / "_kesif"
UA = {"User-Agent": "agrihubai-halden-anlayan/1.0 (+https://github.com/agrihubai/halden-anlayan)"}
FC = "https://www.juntadeandalucia.es/agriculturaypesca/observatorio/servlet/FrontController"
XLS = {"2026": "https://www.juntadeandalucia.es/sites/default/files/inline-files/2026/11/P_Agr%C3%ADcolas_2026_s1_s44_web.xls",
       "2008": "https://www.juntadeandalucia.es/export/drupaljda/estadisticas/pagricolas08_web.xls"}
PAGES = {
    "consejeria": "https://www.juntadeandalucia.es/organismos/agriculturapescaaguaydesarrollorural/servicios/estadistica-cartografia/estadisticas-agricolas/paginas/precios-agricolas-semanales.html",
    "or-tomate": FC + "?action=Static&subsector=20&producto=116&url=generadorInformesOR.jsp",
    "ultimos": FC + "?action=UltimosPrecios&subsector=20",
    "ckan": "https://www.juntadeandalucia.es/datosabiertos/portal/api/3/action/package_show?id=precios-agricolas-semanales-2014",
    "ckan-ara": "https://www.juntadeandalucia.es/datosabiertos/portal/api/3/action/package_search?q=precios%20agricolas&rows=20",
}


def get(url: str) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def run() -> int:
    PROBE.mkdir(parents=True, exist_ok=True)
    n = 0
    for name, url in PAGES.items():
        try:
            t = get(url)
        except Exception as e:  # noqa: BLE001
            t = f"HATA: {e}"
        if name == "consejeria":
            t = json.dumps({"url": url, "baglantilar": sorted(set(re.findall(r'href="([^"]+)"', t)))}, ensure_ascii=False, indent=1)
        elif not name.startswith("ckan"):
            # formlar, select seçenekleri ve script içindeki ajax adresleri
            forms = re.findall(r"<form[\s\S]*?</form>", t, flags=re.I)
            scripts = [s for s in re.findall(r"<script[^>]*>([\s\S]*?)</script>", t, flags=re.I) if re.search(r"ajax|action=|\.do|url", s, re.I)]
            links = sorted(set(re.findall(r'(?:href|src|action)="([^"]*(?:action=|\.xls|\.csv|Download)[^"]*)"', t, flags=re.I)))
            t = json.dumps({"url": url, "uzunluk": len(t), "formlar": [f[:20000] for f in forms], "scriptler": [s[:6000] for s in scripts[:8]], "baglantilar": links[:200]}, ensure_ascii=False, indent=1)
        (PROBE / f"junta-{name}.txt").write_text(t[:200000], encoding="utf-8")
        n += 1
    # haftalık fiyat Excel'i: sayfa adları ve ilk satırlar
    try:
        import subprocess, sys
        try:
            import xlrd  # noqa: F401
        except ImportError:
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "xlrd==2.0.1"], check=True)
        import xlrd
        out = []
        for yil, url in XLS.items():
            data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read()
            wb = xlrd.open_workbook(file_contents=data)
            for sh in wb.sheets():
                out.append(f"=== {yil} · {sh.name} ({sh.nrows}x{sh.ncols})")
                for i in range(sh.nrows):
                    line = " | ".join(str(c.value).strip() for c in sh.row(i))
                    if i < 6 or (yil == "2026" and 300 <= i < 600) or (yil == "2008" and re.search(r"tomate|pimiento|alh", line, re.I)):
                        out.append(f"{i}: {line[:330]}")
        (PROBE / "junta-xls.txt").write_text("\n".join(out)[:180000], encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        (PROBE / "junta-xls.txt").write_text(f"HATA: {e}", encoding="utf-8")
    return n


if __name__ == "__main__":
    print(run())
