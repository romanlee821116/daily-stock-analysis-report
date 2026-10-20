# -*- coding: utf-8 -*-
"""設計新排序分：(a) 量比該不該留在門檻 (b) 新分數是否單調。"""
import csv, importlib.util, os, pathlib, statistics as st
REPO=pathlib.Path(os.path.expanduser("~/mnt/daily-stock-analysis-report"))
sp=importlib.util.spec_from_file_location("bs",REPO/"tools"/"breakout_scan.py")
bs=importlib.util.module_from_spec(sp); sp.loader.exec_module(bs); P=bs.PARAMS
bars={}
for r in csv.DictReader(open(REPO/"backtest"/"prices_all.csv")):
    bars.setdefault(r["code"],[]).append({"d":r["date"],"o":float(r["open"]),"h":float(r["high"]),
        "l":float(r["low"]),"c":float(r["close"]),"v":float(r["volume"])})
for c in bars: bars[c].sort(key=lambda x:x["d"])
U=sorted(c for c in bars if len(bars[c])>=100); flat={"net":0.0,"buyers":0}
IDX={c:{b["d"]:k for k,b in enumerate(bars[c])} for c in U}
def fwd(c,j,h=10):
    b=bars[c]
    if j+h>=len(b): return None
    d=b[j]["d"]; pool=[]
    for x in U:
        if d in IDX[x] and IDX[x][d]+h<len(bars[x]):
            pool.append((bars[x][IDX[x][d]+h]["c"]/bars[x][IDX[x][d]]["c"]-1)*100)
    if len(pool)<8: return None
    return (b[j+h]["c"]/b[j]["c"]-1)*100-sum(pool)/len(pool)

# 把所有「過了非量能條件」的日子都收集起來，再看量比門檻的影響
cand=[]
for c in U:
    b=bars[c]
    for j in range(25,len(b)):
        i=bs.indicators(b[:j+1],flat,0,0)
        if not i: continue
        if not (i["close"]>i["hi_n"] and i["day_gain"]>=P["launch_day_gain_min"]
                and i["upper_shadow_ratio"]<=P["launch_upper_shadow_max"]
                and i["ma20_bias"] is not None and i["ma20_bias"]<=P["launch_ma20_bias_max"]):
            continue
        e=fwd(c,j)
        if e is None: continue
        cand.append({"d":b[j]["d"],"c":c,"v":i["vol_ratio"] or 0,"g":i["day_gain"],
                     "rng":i["range20"] or 99,"bias":i["ma20_bias"],"e":e,
                     "oos":b[j]["d"]<"2026-08-01"})
def rep(nm,g):
    if len(g)<5: print(f"  {nm:<30} n={len(g)} 太少"); return
    e=[x["e"] for x in g]; t=st.mean(e)/((st.pstdev(e) or 1e-9)/len(e)**0.5)
    o=[x["e"] for x in g if x["oos"]]
    print(f"  {nm:<30} n={len(g):>3}  超額{st.mean(e):>+6.2f}%  中位{st.median(e):>+6.2f}%  "
          f"勝率{sum(1 for x in e if x>0)/len(e)*100:>5.1f}%  t={t:>+5.2f}  "
          f"樣本外{(f'{st.mean(o):+.2f}%/n={len(o)}' if len(o)>=5 else f'n={len(o)}')}")

print(f"通過非量能條件的候選：{len(cand)} 個\n(a) 量比門檻的影響：")
rep("現行：量比>=1.5 或 漲幅>=7%", [x for x in cand if x["v"]>=1.5 or x["g"]>=7])
rep("完全不設量比門檻", cand)
rep("只留量比<1.5（反向門檻）", [x for x in cand if x["v"]<1.5])
rep("量比<2.0（寬鬆反向門檻）", [x for x in cand if x["v"]<2.0])

def clamp(x): return max(0.0,min(1.0,x))
def newscore(x):
    shape = 40*clamp((40-x["rng"])/30)        # 振幅 10%滿分 → 40%零分
    vol   = 30*clamp((2.5-x["v"])/2.0)        # 量比 0.5滿分 → 2.5零分
    gain  = 30*clamp((x["g"]-3)/7)            # 漲幅 3%零分 → 10%滿分
    return round(shape+vol+gain,1)
print("\n(b) 新排序分（無門檻，對全部候選排序）四分位：")
s=sorted(cand,key=newscore); q=len(s)//4
for i,nm in enumerate(("Q1最低","Q2","Q3","Q4最高")):
    g=s[i*q:(i+1)*q] if i<3 else s[3*q:]
    e=[x["e"] for x in g]
    print(f"  {nm:<8} n={len(g):>3}  分數{newscore(g[0]):>5.1f}~{newscore(g[-1]):>5.1f}  "
          f"超額{st.mean(e):>+6.2f}%  中位{st.median(e):>+6.2f}%  勝率{sum(1 for x in e if x>0)/len(e)*100:>5.1f}%")
print("\n  取分數最高的 N 個（模擬每日只進前幾名）：")
hi=sorted(cand,key=newscore,reverse=True)
for n in (10,20,30,40):
    rep(f"  Top {n}", hi[:n])
