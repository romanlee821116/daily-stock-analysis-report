# -*- coding: utf-8 -*-
"""觀察池大小 vs 訊號覆蓋率／品質。只能在 ETF 報告涵蓋期內測。"""
import csv, importlib.util, pathlib, statistics as st, collections
REPO = pathlib.Path(__file__).resolve().parent.parent
sp = importlib.util.spec_from_file_location("bs", REPO/"tools"/"breakout_scan.py")
bs = importlib.util.module_from_spec(sp); sp.loader.exec_module(bs)

bars={}
for r in csv.DictReader(open(REPO/"backtest"/"prices_history.csv")):
    bars.setdefault(r["code"],[]).append({"d":r["date"],"o":float(r["open"]),
        "h":float(r["high"]),"l":float(r["low"]),"c":float(r["close"]),"v":float(r["volume"])})
for c in bars: bars[c].sort(key=lambda x:x["d"])
IDX={c:{x["d"]:k for k,x in enumerate(bars[c])} for c in bars}
alld=sorted({x["d"] for c in bars for x in bars[c]})
w=[]; flows=bs.load_etf_flows(REPO/"reports", w); fdays=sorted(flows)
print(f"全部有價格 {len(bars)} 檔；ETF 報告 {len(fdays)} 天 {fdays[0]}~{fdays[-1]}")

fwd={}
for h in (10,20):
    for d in alld:
        v=[]
        for c in bars:
            i=IDX[c].get(d)
            if i is not None and i+h<len(bars[c]):
                v.append((bars[c][i+h]["c"]/bars[c][i]["c"]-1)*100)
        if len(v)>=20: fwd[(h,d)]=sum(v)/len(v)

# 報告涵蓋期內，全部 154 檔的起漲訊號
flat={"net":0.0,"buyers":0}; ev=[]
for c in bars:
    b=bars[c]
    for j in range(125,len(b)):
        d=b[j]["d"]
        if d < fdays[0]: continue
        i=bs.indicators(b[max(0,j-130):j+1],flat,0,0)
        if not i or bs.classify(i,None)[0]!="起漲": continue
        row={"c":c,"d":d,"score":bs.score(i,"起漲")}
        for h in (10,20):
            if (h,d) in fwd and j+h<len(b):
                row[f"e{h}"]=(b[j+h]["c"]/b[j]["c"]-1)*100-fwd[(h,d)]
        ev.append(row)
print(f"報告涵蓋期內（全 154 檔）起漲訊號 {len(ev)} 個\n")

def uni_at(d, lb):
    use=[a for a in fdays if a < d][-lb:]
    return {code for a in use for code in flows[a]}

print(f"{'lookback':>9}{'平均池':>8}{'抓到訊號':>9}{'覆蓋率':>8}"
      f"{'10日超額':>10}{'勝率':>7}   {'高分訊號':>8}{'高分超額':>10}")
print("─"*78)
for lb in (5,10,20,30,40,999):
    sizes=[]; got=[]
    for d in sorted({x["d"] for x in ev}):
        u=uni_at(d,lb); sizes.append(len(u))
        got += [x for x in ev if x["d"]==d and x["c"] in u]
    e=[x["e10"] for x in got if "e10" in x]
    hi=[x for x in got if x["score"]>=50 and "e10" in x]
    lab = "全部不濾" if lb==999 else f"{lb} 日"
    print(f"{lab:>9}{st.mean(sizes):>8.0f}{len(got):>9}{len(got)/len(ev)*100:>7.0f}%"
          f"{(st.mean(e) if e else 0):>+9.2f}%{(sum(1 for x in e if x>0)/len(e)*100 if e else 0):>6.0f}%"
          f"   {len(hi):>8}{(st.mean([x['e10'] for x in hi]) if hi else 0):>+9.2f}%")

print("\n=== 被濾掉的訊號表現如何？（lookback=20）===")
ins, outs = [], []
for d in sorted({x["d"] for x in ev}):
    u=uni_at(d,20)
    for x in ev:
        if x["d"]!=d or "e10" not in x: continue
        (ins if x["c"] in u else outs).append(x["e10"])
for nm,v in (("在池內",ins),("被濾掉",outs)):
    if len(v)<5: continue
    print(f"  {nm}  n={len(v):>3}  超額{st.mean(v):>+6.2f}%  中位{st.median(v):>+6.2f}%  "
          f"勝率{sum(1 for x in v if x>0)/len(v)*100:>5.1f}%")
