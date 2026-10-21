#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""診斷 yfinance 為什麼抓不到某些代號。用法：python3 tools/diag_yf.py"""
import sys, time
from datetime import date, timedelta

try:
    import yfinance as yf
except ImportError:
    sys.exit("沒有 yfinance")

print("yfinance 版本：", getattr(yf, "__version__", "未知"))
try:
    import curl_cffi; print("curl_cffi    ：", curl_cffi.__version__)
except Exception: print("curl_cffi    ： 未安裝")
import pandas as pd; print("pandas       ：", pd.__version__)
print()

end = date.today(); start = end - timedelta(days=400)
FAIL = ["2330", "2303", "1101", "2317"]      # 這次整批掉的
OK   = ["2347", "2360", "6257"]              # 這次成功的

def one(tk):
    try:
        df = yf.download(tk, start=start.isoformat(), end=(end+timedelta(days=1)).isoformat(),
                         interval="1d", auto_adjust=False, progress=False, threads=False)
        n = 0 if df is None or df.empty else len(df.dropna(how="all"))
        return n, ""
    except Exception as exc:                 # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"

print("=== 單檔逐一測（最關鍵）===")
for c in FAIL + OK:
    for sfx in (".TW", ".TWO"):
        n, err = one(c + sfx)
        print(f"  {c}{sfx:<5} 列數={n:<5} {err}")
        time.sleep(1.0)
        if n: break

print("\n=== 多檔一次抓（看 group_by 結構）===")
tks = " ".join(c + ".TW" for c in FAIL[:2] + OK[:1])
try:
    df = yf.download(tks, start=start.isoformat(), end=(end+timedelta(days=1)).isoformat(),
                     interval="1d", auto_adjust=False, group_by="ticker",
                     progress=False, threads=True)
    print("  shape:", None if df is None else df.shape)
    if df is not None and not df.empty:
        lv0 = list(dict.fromkeys(df.columns.get_level_values(0))) \
              if hasattr(df.columns, "levels") else list(df.columns)
        print("  第一層欄位:", lv0)
        for t in tks.split():
            try:
                sub = df[t].dropna(subset=["Close"])
                print(f"    {t}: {len(sub)} 列")
            except Exception as exc:          # noqa: BLE001
                print(f"    {t}: 取不到 → {type(exc).__name__}")
except Exception as exc:                      # noqa: BLE001
    print("  多檔抓失敗：", type(exc).__name__, exc)
