# -*- coding: utf-8 -*-
"""樣本外驗證：用 2026-05~07 的價格跑新版起漲條件（校準用的是 09~10 的 7 個案例）。"""
import csv, importlib.util, os, pathlib, statistics as st, collections
# repo 根目錄由這支腳本自己的位置推導，不要寫死任何人的家目錄路徑。
# （2026-10-21 修：原本寫死 ~/mnt/... 那是 Claude 端的掛載點，
#  在使用者自己的 Mac 上一定 FileNotFoundError。）
REPO = pathlib.Path(__file__).resolve().parent.parent
sp = importlib.util.spec_from_file_location("bs", REPO/"tools"/"breakout_scan.py")
bs = importlib.util.module_from_spec(sp); sp.loader.exec_module(bs)

bars = {}
for fn in ("prices_hist.csv", "prices.csv"):
    for r in csv.DictReader(open(REPO/"backtest"/fn)):
        bars.setdefault(r["code"], []).append({"d":r["date"],"o":float(r["open"]),
            "h":float(r["high"]),"l":float(r["low"]),"c":float(r["close"]),"v":float(r["volume"])})
for c in bars:
    seen={}; 
    for b in sorted(bars[c], key=lambda x:x["d"]): seen[b["d"]]=b
    bars[c]=[seen[d] for d in sorted(seen)]
U = sorted(c for c in bars if c in bs.THEMES and len(bars[c])>=100)
flat = {"net":0.0,"buyers":0}
print(f"樣本：{len(U)} 檔 {U}")
print(f"期間：{min(b['d'] for c in U for b in bars[c])} ~ {max(b['d'] for c in U for b in bars[c])}\n")

def seg(d):
    return "樣本內 (09-18~10-19)" if d >= "2026-09-18" else (
           "樣本外 (05~07)" if d < "2026-08-01" else "過渡 (08~09中)")

rows = collections.defaultdict(lambda: {"trig":0,"truth":0,"hit":0,"r10":[],"ex":[]})
alltruth = collections.defaultdict(list)
for c in U:
    b = bars[c]
    for j in range(25, len(b)):
        i = bs.indicators(b[:j+1], flat, 0, 0)
        if not i: continue
        s = seg(b[j]["d"])
        trig = bs.classify(i, None)[0] == "起漲"
        truth = False
        if j+10 < len(b) and b[j]["c"] > i["hi_n"]:
            truth = (max(x["h"] for x in b[j+1:j+11])/b[j]["c"]-1)*100 >= 15
        if truth: rows[s]["truth"] += 1; alltruth[s].append((b[j]["d"],c))
        if trig:
            rows[s]["trig"] += 1
            if truth: rows[s]["hit"] += 1
            if j+10 < len(b): rows[s]["r10"].append((b[j+10]["c"]/b[j]["c"]-1)*100)

print(f"{'期間':<22}{'觸發':>5}{'真實起漲':>9}{'抓到':>5}{'召回':>7}{'精準':>7}{'10日平均報酬':>13}")
print("─"*72)
for s in ("樣本外 (05~07)","過渡 (08~09中)","樣本內 (09-18~10-19)"):
    v = rows[s]
    rec = v["hit"]/v["truth"]*100 if v["truth"] else float("nan")
    pre = v["hit"]/v["trig"]*100 if v["trig"] else float("nan")
    r10 = f"{st.mean(v['r10']):+.2f}%" if v["r10"] else "—"
    print(f"{s:<22}{v['trig']:>5}{v['truth']:>9}{v['hit']:>5}{rec:>6.0f}%{pre:>6.0f}%{r10:>13}")
print()
for s in ("樣本外 (05~07)",):
    print(f"{s} 的真實起漲日：")
    for d,c in sorted(alltruth[s]): print(f"   {d} {c}")
