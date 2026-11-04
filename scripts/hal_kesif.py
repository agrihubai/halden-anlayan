"""Geçici keşif: ilçe halleri için resmî kaynak ve robots.txt kontrolü (data/_kesif/hal-kesif.json). Keşif bitince kaldırılacak."""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "agrihubai-halden-anlayan/1.0 (+https://github.com/agrihubai/halden-anlayan)"}
ROBOTS = ["https://www.hal.gov.tr/robots.txt", "https://gezipanel.antalya.bel.tr/robots.txt", "https://antalya.bel.tr/robots.txt"]
PAGES = ["https://gezipanel.antalya.bel.tr/", "https://gezipanel.antalya.bel.tr/hal-gunluk-fiyat", "https://gezipanel.antalya.bel.tr/Content/js/main.js"]


def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return None, f"HATA: {e}"


def run() -> int:
    out = {"robots": {}, "sayfalar": {}}
    for u in ROBOTS:
        st, t = get(u)
        out["robots"][u] = {"durum": st, "icerik": t[:3000]}
    for u in PAGES:
        st, t = get(u)
        out["sayfalar"][u] = {"durum": st, "hal_baglantilari": sorted(set(re.findall(r'["\']([^"\']*(?:[Hh]al|Methods\.aspx/\w+)[^"\']*)["\']', t)))[:150]}
    p = ROOT / "data" / "_kesif" / "hal-kesif.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(out["robots"]) + len(out["sayfalar"])


if __name__ == "__main__":
    print(run())
