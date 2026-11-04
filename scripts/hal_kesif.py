"""Geçici keşif: ilçe halleri için resmî kaynak ve robots.txt kontrolü (data/_kesif/hal-kesif.json). Keşif bitince kaldırılacak."""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "agrihubai-halden-anlayan/1.0 (+https://github.com/agrihubai/halden-anlayan)"}
ROBOTS = ["https://www.hal.gov.tr/robots.txt", "https://gezipanel.antalya.bel.tr/robots.txt", "https://antalya.bel.tr/robots.txt"]
PAGES = ["https://www.hal.gov.tr/Sayfalar/FiyatDetaylari.aspx", "https://hal.gov.tr/Sayfalar/FiyatDetaylari.aspx"]


def get(u):
    import time
    for i in range(4):
        st, t = _get(u)
        if st or "name resolution" not in t:
            return st, t
        time.sleep(5)
    return st, t


def _get(u):
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
        sel = {}
        for m in re.finditer(r"<select[^>]*name=\"([^\"]+)\"[^>]*>([\s\S]*?)</select>", t, flags=re.I):
            sel[m.group(1)] = re.findall(r"<option[^>]*value=\"([^\"]*)\"[^>]*>([^<]*)</option>", m.group(2))[:400]
        inputs = re.findall(r"<input[^>]*name=\"([^\"]+)\"[^>]*>", t, flags=re.I)
        scripts = [x[:3000] for x in re.findall(r"<script[^>]*>([\s\S]*?)</script>", t, flags=re.I) if re.search(r"ajax|fiyat|webservice|_api|svc|asmx", x, re.I)][:10]
        srcs = re.findall(r"<script[^>]*src=\"([^\"]+)\"", t, flags=re.I)
        tables = [re.sub(r"\s+", " ", x)[:4000] for x in re.findall(r"<table[\s\S]*?</table>", t, flags=re.I)][:3]
        out["sayfalar"][u] = {"durum": st, "uzunluk": len(t), "secimler": sel, "inputlar": inputs[:80], "scriptler": scripts, "script_src": srcs[:60], "tablolar": tables,
                               "metin": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", "", t)))[:4000]}
    p = ROOT / "data" / "_kesif" / "hal-kesif.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(out["robots"]) + len(out["sayfalar"])


if __name__ == "__main__":
    print(run())
