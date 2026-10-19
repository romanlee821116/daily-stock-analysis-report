# -*- coding: utf-8 -*-
"""校準起漲條件：對 7 個真實起漲日求召回，同時看總觸發數與前瞻超額報酬。"""
import csv, importlib.util, os, pathlib, statistics as st, collections
REPO = pathlib.Path(os.path.expanduser("~/mnt/daily-stock-analysis-report"))
spec = importlib.util.spec_from_file_location("bs", REPO/"tools"/"breakout_scan.py")
bs = importlib.util.module_from_spec(spec); spec.loader.exec_module(bs)
bars={}
for r in csv.DictReader(open(REPO/"backtest"/"prices.csv")):
    bars.setdefault(r["code"],[]).append({"d":r["date"],"o":float(r["open"]),"h":float(r["high"]),
        "l":float(r["low"]),"c":float(r["close"]),"v":float(r["volume"])})
for c in bars: bars[c].sort(key=lambda x:x["d"])
universe=sorted(set(bars)&set(bs.THEMES))

cache={}
for c in universe:
    for j in range(len(bars[c])):
        if j<25: continue
        i=bs.indicators(bars[c][:j+1],{"net":0.0,"buyers":0},0,0)
        if i: cache[(c,j)]=i

TRUTH=set()
for (c,j),i in cache.items():
    b=bars[c]
    if j+10>=len(b) or b[j]["c"]<=i["hi_n"]: continue
    if (max(x["h"] for x in b[j+1:j+11])/b[j]["c"]-1)*100>=15: TRUTH.add((c,j))

def excess(ev,h):
    byd=collections.defaultdict(list)
    for c,j in ev: byd[bars[c][j]["d"]].append((c,j))
    out=[]
    for d,evs in byd.items():
        pool=[]
        for c in universe:
            idx={b["d"]:k for k,b in enumerate(bars[c])}
            if d in idx and idx[d]+h<len(bars[c]):
                pool.append((bars[c][idx[d]+h]["c"]/bars[c][idx[d]]["c"]-1)*100)
        if len(pool)<5: continue
        mkt=sum(pool)/len(pool)
        for c,j in evs:
            if j+h<len(bars[c]): out.append((bars[c][j+h]["c"]/bars[c][j]["c"]-1)*100-mkt)
    return out

def mk(vol, bias, shadow, strong_gain=None):
    def f(i):
        if i["close"]<=i["hi_n"] or i["day_gain"]<3.0: return False
        vr=i["vol_ratio"] or 0
        volok = vr>=vol or (strong_gain is not None and i["day_gain"]>=strong_gain)
        if not volok: return False
        if i["upper_shadow_ratio"]>shadow: return False
        if i["ma20_bias"] is None or i["ma20_bias"]>bias: return False
        return True
    return f

SETS={
 "現行 (1.5 / 15% / 30%)":              mk(1.5,15,0.30),
 "只放寬乖離 → 25%":                     mk(1.5,25,0.30),
 "只放寬上影線 → 60%":                   mk(1.5,15,0.60),
 "只放寬量比 → 1.2":                     mk(1.2,15,0.30),
 "量比1.2 + 乖離25%":                   mk(1.2,25,0.30),
 "量比1.2 + 乖離25% + 上影60%":          mk(1.2,25,0.60),
 "量比1.5或漲幅>=7% + 乖離25% + 上影60%": mk(1.5,25,0.60,strong_gain=7.0),
 "量比1.2或漲幅>=7% + 乖離25% + 上影60%": mk(1.2,25,0.60,strong_gain=7.0),
 "不看量比 + 乖離25% + 上影60%":          mk(0.0,25,0.60),
}
print(f"可判定檔日 {len(cache)}；真實起漲日 {len(TRUTH)} 個\n")
print(f"{'參數組':<36}{'觸發':>5}{'抓到':>6}{'召回':>7}{'精準':>7}{'5日超額':>9}{'10日超額':>10}")
print("─"*86)
for name,f in SETS.items():
    ev=[k for k,i in cache.items() if f(i)]
    hit=len([k for k in ev if k in TRUTH])
    rec=hit/len(TRUTH)*100
    prec=hit/len(ev)*100 if ev else 0
    e5,e10=excess(ev,5),excess(ev,10)
    s5=f"{st.mean(e5):+.2f}%" if len(e5)>=5 else f"n={len(e5)}"
    s10=f"{st.mean(e10):+.2f}%" if len(e10)>=5 else f"n={len(e10)}"
    print(f"{name:<36}{len(ev):>5}{hit:>6}{rec:>6.0f}%{prec:>6.0f}%{s5:>9}{s10:>10}")
