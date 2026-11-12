# Hal-den Anlayan

Türkiye ve İspanya sebze hal fiyatları panosu. / Turkey–Spain wholesale vegetable price dashboard.

**Pano / Dashboard:** https://agrihubai.github.io/halden-anlayan/

Domates, biber, hıyar, patlıcan ve kabak için:
- **Türkiye:** İzmir halinin günlük en düşük, en yüksek ve ortalama fiyatları (TL). Grafiğin üstüne gelince o günün ECB kuruyla euro karşılığı görünür.
- **İspanya:** Avrupa Komisyonu'nun haftalık tarla, paketleme çıkışı ve raf fiyatları (EUR).
- **Karşılaştırma:** İki ülke haftalık euro/kg olarak aynı grafikte.

## Nasıl çalışır

- `scripts/update_data.py` üç kaynaktan veri çeker ve ham veriyi `data/ham/` klasörüne yazar. Kaynaklardan gelen ilk yanıtların kısa örnekleri `data/_kesif/` klasörüne yazılır; kaynak formatı değişirse buradan görülür.
- `scripts/build_data.py` ham veriden panonun okuduğu `data/urun/<ürün>.json` dosyalarını üretir.
- `.github/workflows/veri-guncelle.yml` bu iki betiği **her gün üç kez** (06:41, 11:41, 17:41 UTC) otomatik çalıştırır; GitHub'ın zamanlanmış işleri geciktirmesine karşı üç deneme vardır. İş her çalıştırmada kendini yeniden etkinleştirir, böylece GitHub'ın 60 günlük hareketsizlik kapatması devreye girmez. Actions sekmesinden elle de çalıştırılabilir.
- `.github/workflows/hks-gecmis.yml` HKS'nin eksik geçmiş günlerini iki saatte bir doldurur.
- `index.html` panonun kendisidir (D3 ile, tek dosya).

## Kaynaklar

- [İzmir Büyükşehir Belediyesi açık veri: sebze ve meyve hal fiyatları](https://acikveri.bizizmir.com/dataset/sebze-ve-meyve-hal-fiyatlari)
- [Gazipaşa hal fiyatları, Batı Akdeniz Haber Ajansı](https://www.batiakdeniztv.com/gazipasa-hal-fiyatlari) — günlük güncel liste; arşivi olmadığı için seri 12 Kasım 2026'dan itibaren birikir. Dikenli salatalık (İspanyol tipi kısa hıyar) yalnız bu listede ayrı fiyatlanır.
- [ECB euro referans kurları](https://data.ecb.europa.eu/) (EUR/TRY)
- [Avrupa Komisyonu agri-food veri portalı](https://agridata.ec.europa.eu/extensions/DataPortal/fruit-and-vegetables.html)

Hal fiyatı üreticinin eline geçen fiyat değildir. İzmir hali Türkiye'nin tamamını temsil etmez. Bu sayfa yapay zekâ ile hazırlanmıştır; yatırım ya da ticaret tavsiyesi değildir. [AgriHub-AI](https://agrihubai.wordpress.com/)
