"""Geçici keşif: HKS (hal.gov.tr) fiyat sayfaları — hal/il ayrımı var mı (data/_kesif/hal-kesif.json). Keşif bitince kaldırılacak."""
from __future__ import annotations

import html
import json
import re
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "agrihubai-halden-anlayan/1.0 (+https://github.com/agrihubai/halden-anlayan)"}
BASE = "https://www.hal.gov.tr"


def get(u):
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            err = str(e)
            if "name resolution" not in err:
                return None, "HATA: " + err
            time.sleep(5)
    return None, "HATA: " + err


def text(t):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", "", t))))


def run() -> int:
    out = {"harita": [], "sayfalar": {}}
    st, t = get(BASE + "/Sayfalar/SiteHaritasi.aspx")
    links = [(h, re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", a))).strip()) for h, a in re.findall(r'<a[^>]*href="([^"#]+)"[^>]*>([\s\S]*?)</a>', t)]
    out["harita"] = [l for l in links if l[1]][:300]
    for h, a in out["harita"]:
        if not re.search(r"fiyat|istatist|İstatist", a, re.I):
            continue
        u = html.unescape(h if h.startswith("http") else BASE + (h if h.startswith("/") else "/" + h))
        if u in out["sayfalar"] or len(out["sayfalar"]) >= 10:
            continue
        st2, t2 = get(u)
        sel = {}
        for m in re.finditer(r'<select[^>]*name="([^"]+)"[^>]*>([\s\S]*?)</select>', t2, flags=re.I):
            sel[m.group(1)] = [(v, html.unescape(x).strip()) for v, x in re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)</option>', m.group(2))][:400]
        out["sayfalar"][u] = {"ad": a, "durum": st2, "secimler": sel,
                              "inputlar": [x for x in re.findall(r'<input[^>]*name="([^"]+)"', t2) if "ctl00$ctl" in x][:30],
                              "metin": text(t2)[1500:4500]}
    (ROOT / "data" / "_kesif" / "hal-kesif.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(out["sayfalar"])


if __name__ == "__main__":
    print(run())
