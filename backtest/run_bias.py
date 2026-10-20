# -*- coding: utf-8 -*-
"""宇宙偏誤檢驗：同一套訊號 + 排序分，在「被 ETF 報告選中」與「完全沒出現」兩組上跑。"""
import csv, importlib.util, os, pathlib, statistics as st, sys
REPO=pathlib.Path(os.path.expanduser("~/mnt/daily-stock-analysis-report"))
sp=importlib.util.spec_from_file_location("bs",REPO/"tools"/"breakout_scan.py")
bs=importlib.util.module_from_spec(sp); sp.loader.exec_module(bs)

def load(fn):
    b={}
    for r in csv.DictReader(open(REPO/"backtest"/fn)):
        b.setdefault(r["code"],[]).append({"d":r["date"],"o":float(r["open"]),"h":float(r["high"]),
            "l":float(r["low"]),"c":float(r["close"]),"v":float(r["volume"])})
    for c in b: b[c].sort(key=lambda x:x["d"])
    return {c:v for c,v in b.items() if len(v)>=100}

def analyse(name, bars):
    U=sorted(bars); flat={"net":0.0,"buyers":0}
    IDX={c:{x["d"]:k for k,x in enumerate(bars[c])} for c in U}
    def exc(c,j,h=10):
        b=bars[c]
        if j+h>=len(b): return None
        d=b[j]["d"]; pool=[]
        for x in U:
            if d in IDX[x] and IDX[x][d]+h<len(bars[x]):
                pool.append((bars[x][IDX[x][d]+h]["c"]/bars[x][IDX[x][d]]["c"]-1)*100)
        if len(pool)<4: return None
        return (b[j+h]["c"]/b[j]["c"]-1)*100-sum(pool)/len(pool)
    ev=[];truth=0;hit=0
    for c in U:
        b=bars[c]
        for j in range(25,len(b)):
            i=bs.indicators(b[:j+1],flat,0,0)
            if not i: continue
            trig = bs.classify(i,None)[0]=="起漲"
            tr=False
            if j+10<len(b) and b[j]["c"]>i["hi_n"]:
                tr=(max(x["h"] for x in b[j+1:j+11])/b[j]["c"]-1)*100>=15
            if tr: truth+=1
            if not trig: continue
            if tr: hit+=1
            e=exc(c,j)
            if e is not None: ev.append({"s":bs.score(i,"起漲"),"e":e,
                                         "oos":b[j]["d"]<"2026-08-01"})
    print(f"\n【{name}】{len(U)} 檔")
    print(f"  真實起漲日 {truth} 個；起漲訊號觸發 {len(ev)+0} 個（有10日後續的）；抓到 {hit}")
    if not ev: print("  無可評估訊號"); return
    for thr in (0, bs.PARAMS["score_report_min"]):
        g=[x for x in ev if x["s"]>=thr]
        if len(g)<4: print(f"  分數>={thr}: n={len(g)} 太少"); continue
        e=[x["e"] for x in g]
        t=st.mean(e)/((st.pstdev(e) or 1e-9)/len(e)**0.5)
        o=[x["e"] for x in g if x["oos"]]
        print(f"  分數>={thr:<2} n={len(g):>3}  超額{st.mean(e):>+6.2f}%  中位{st.median(e):>+6.2f}%  "
              f"勝率{sum(1 for x in e if x>0)/len(e)*100:>5.1f}%  t={t:>+5.2f}  "
              f"樣本外{(f'{st.mean(o):+.2f}%/n={len(o)}' if len(o)>=4 else f'n={len(o)}')}")

analyse("被汙染組：ETF 報告挑出來的 31 檔", load("prices_all.csv"))
analyse("中立組：完全沒出現在報告裡", load("prices_neutral.csv"))
