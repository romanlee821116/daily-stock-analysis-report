# -*- coding: utf-8 -*-
"""
組內超額：THEMES 訊號 vs THEMES 當日平均、對照組訊號 vs 對照組當日平均。

為什麼一定要這樣算：
    用「全體 154 檔混合基準」時，若 THEMES（半導體動能股）這兩年整體就贏過
    對照組（傳產金融），任何打在 THEMES 上的訊號都會自動好看、打在對照組上的
    都會自動難看 —— 那測到的是族群 beta，不是訊號。組內比較讓族群效應抵銷。
"""
import csv, importlib.util, os, pathlib, statistics as st, collections
REPO = pathlib.Path(__file__).resolve().parent.parent
sp = importlib.util.spec_from_file_location("bs", REPO/"tools"/"breakout_scan.py")
bs = importlib.util.module_from_spec(sp); sp.loader.exec_module(bs)
fs = importlib.util.spec_from_file_location("fh", REPO/"tools"/"fetch_history.py")
fh = importlib.util.module_from_spec(fs); fs.loader.exec_module(fh)

DROP={"7750","7769"}; CALIB="2026-05-01"
NEUTRAL=set(fh.CONTROL)-set(bs.THEMES)
bars={}
for r in csv.DictReader(open(REPO/"backtest"/"prices_history.csv")):
    if r["code"] in DROP: continue
    bars.setdefault(r["code"],[]).append({"d":r["date"],"o":float(r["open"]),
        "h":float(r["high"]),"l":float(r["low"]),"c":float(r["close"]),"v":float(r["volume"])})
for c in bars: bars[c].sort(key=lambda x:x["d"])
GRP={c:("中立" if c in NEUTRAL else "THEMES") for c in bars}
IDX={c:{x["d"]:k for k,x in enumerate(bars[c])} for c in bars}
alld=sorted({x["d"] for c in bars for x in bars[c]})
print(f"THEMES {sum(1 for g in GRP.values() if g=='THEMES')} 檔 ／ "
      f"中立 {sum(1 for g in GRP.values() if g=='中立')} 檔")

# 各組各自的當日等權報酬
base={}
for g in ("THEMES","中立"):
    for h in (10,20):
        for d in alld:
            v=[]
            for c in bars:
                if GRP[c]!=g: continue
                i=IDX[c].get(d)
                if i is not None and i+h<len(bars[c]):
                    v.append((bars[c][i+h]["c"]/bars[c][i]["c"]-1)*100)
            if len(v)>=8: base[(g,h,d)]=sum(v)/len(v)

flat={"net":0.0,"buyers":0}; ev=[]
for c in bars:
    b=bars[c]; g=GRP[c]
    for j in range(125,len(b)):
        i=bs.indicators(b[max(0,j-130):j+1],flat,0,0)
        if not i or bs.classify(i,None)[0]!="起漲": continue
        d=b[j]["d"]; row={"c":c,"d":d,"g":g,"score":bs.score(i,"起漲"),"oos":d<CALIB}
        for h in (10,20):
            k=(g,h,d)
            if k in base and j+h<len(b):
                row[f"e{h}"]=(b[j+h]["c"]/b[j]["c"]-1)*100-base[k]
        ev.append(row)

def rep(nm,g,key="e10"):
    v=[x[key] for x in g if key in x]
    if len(v)<8: print(f"  {nm:<26} n={len(v)} 太少"); return
    byd=collections.defaultdict(list)
    for x in g:
        if key in x: byd[x["d"]].append(x[key])
    daily=[sum(a)/len(a) for a in byd.values()]
    td=st.mean(daily)/((st.pstdev(daily) or 1e-9)/len(daily)**0.5)
    print(f"  {nm:<26} n={len(v):>4}  組內超額{st.mean(v):>+6.2f}%  中位{st.median(v):>+6.2f}%  "
          f"勝率{sum(1 for x in v if x>0)/len(v)*100:>5.1f}%  t(日)={td:>+5.2f}")

oos=[x for x in ev if x["oos"]]
print(f"\n真樣本外訊號 {len(oos)} 個（組內比較，10日）")
rep("THEMES 全部",[x for x in oos if x["g"]=="THEMES"])
rep("中立  全部",[x for x in oos if x["g"]=="中立"])
print()
rep("THEMES 分數>=50",[x for x in oos if x["g"]=="THEMES" and x["score"]>=50])
rep("中立  分數>=50",[x for x in oos if x["g"]=="中立" and x["score"]>=50])
print("\n持有 20 日：")
rep("THEMES 分數>=50",[x for x in oos if x["g"]=="THEMES" and x["score"]>=50],"e20")
rep("中立  分數>=50",[x for x in oos if x["g"]=="中立" and x["score"]>=50],"e20")

print("\n各組的「基準」本身表現（當日等權 10 日報酬平均）：")
for g in ("THEMES","中立"):
    v=[base[(g,10,d)] for d in alld if (g,10,d) in base]
    print(f"  {g:<8} 平均 {st.mean(v):+.2f}%／中位 {st.median(v):+.2f}%（{len(v)} 天）")
