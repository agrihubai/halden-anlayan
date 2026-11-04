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
PAGES = {
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
        if not name.startswith("ckan"):
            # formlar, select seçenekleri ve script içindeki ajax adresleri
            forms = re.findall(r"<form[\s\S]*?</form>", t, flags=re.I)
            scripts = [s for s in re.findall(r"<script[^>]*>([\s\S]*?)</script>", t, flags=re.I) if re.search(r"ajax|action=|\.do|url", s, re.I)]
            links = sorted(set(re.findall(r'(?:href|src|action)="([^"]*(?:action=|\.xls|\.csv|Download)[^"]*)"', t, flags=re.I)))
            t = json.dumps({"url": url, "uzunluk": len(t), "formlar": [f[:20000] for f in forms], "scriptler": [s[:6000] for s in scripts[:8]], "baglantilar": links[:200]}, ensure_ascii=False, indent=1)
        (PROBE / f"junta-{name}.txt").write_text(t[:200000], encoding="utf-8")
        n += 1
    return n


if __name__ == "__main__":
    print(run())
