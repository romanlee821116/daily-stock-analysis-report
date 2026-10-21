# -*- coding: utf-8 -*-
"""82 個起漲訊號：score() 與各候選條件變數有沒有分辨贏家輸家的能力？"""
import csv, importlib.util, os, pathlib, statistics as st
# repo 根目錄由這支腳本自己的位置推導，不要寫死任何人的家目錄路徑。
# （2026-10-21 修：原本寫死 ~/mnt/... 那是 Claude 端的掛載點，
#  在使用者自己的 Mac 上一定 FileNotFoundError。）
REPO = pathlib.Path(__file__).resolve().parent.parent
sp=importlib.util.spec_from_file_location("bs",REPO/"tools"/"breakout_scan.py")
bs=importlib.util.module_from_spec(sp); sp.loader.exec_module(bs)
bars={}
for r in csv.DictReader(open(REPO/"backtest"/"prices_all.csv")):
    bars.setdefault(r["code"],[]).append({"d":r["date"],"o":float(r["open"]),"h":float(r["high"]),
        "l":float(r["low"]),"c":float(r["close"]),"v":float(r["volume"])})
for c in bars: bars[c].sort(key=lambda x:x["d"])
U=sorted(c for c in bars if len(bars[c])>=100); flat={"net":0.0,"buyers":0}
IDX={c:{b["d"]:k for k,b in enumerate(bars[c])} for c in U}
alld=sorted({b["d"] for c in U for b in bars[c]})

# 自建「市場」＝31 檔等權指數，用來算超額與多空格局
mkt={}
for d in alld:
    cs=[bars[c][IDX[c][d]]["c"] for c in U if d in IDX[c]]
    if len(cs)>=20: mkt[d]=sum(cs)/len(cs)
md=sorted(mkt)
mma20={d:(st.mean([mkt[x] for x in md[max(0,i-19):i+1]]) if i>=19 else None)
        for i,d in enumerate(md)}

def fwd(c,j,h):
    b=bars[c]
    if j+h>=len(b): return None
    r=(b[j+h]["c"]/b[j]["c"]-1)*100
    pool=[]
    d=b[j]["d"]
    for x in U:
        if d in IDX[x] and IDX[x][d]+h<len(bars[x]):
            pool.append((bars[x][IDX[x][d]+h]["c"]/bars[x][IDX[x][d]]["c"]-1)*100)
    return r-sum(pool)/len(pool) if len(pool)>=8 else None

ev=[]
for c in U:
    b=bars[c]
    for j in range(25,len(b)):
        i=bs.indicators(b[:j+1],flat,0,0)
        if not i or bs.classify(i,None)[0]!="起漲": continue
        d=b[j]["d"]
        ma=mma20.get(d)
        ev.append({"d":d,"code":c,"j":j,
                   "score":bs.score(i,"起漲"),
                   "gain":i["day_gain"],"vol":i["vol_ratio"] or 0,
                   "bias":i["ma20_bias"],"shadow":i["upper_shadow_ratio"]*100,
                   "close_pos":i["close_pos"]*100,
                   "range20":i["range20"],
                   "mkt_up":(ma is not None and mkt[d]>ma),
                   "e10":fwd(c,j,10)})
ev=[e for e in ev if e["e10"] is not None]
print(f"可評估訊號 {len(ev)} 個\n")

def split(name,key,rev=False):
    s=sorted(ev,key=lambda e:e[key],reverse=rev)
    n=len(s)//2
    lo,hi=s[:n],s[-n:]
    a=st.mean([e["e10"] for e in lo]); b=st.mean([e["e10"] for e in hi])
    wa=sum(1 for e in lo if e["e10"]>0)/len(lo)*100
    wb=sum(1 for e in hi if e["e10"]>0)/len(hi)*100
    print(f"  {name:<22} 低半 {a:>+6.2f}%(勝{wa:>4.0f}%)   高半 {b:>+6.2f}%(勝{wb:>4.0f}%)   差 {b-a:>+6.2f}pp")

print("依各變數切兩半，比 10 日超額報酬：")
for nm,k in (("score（現行評分）","score"),("當日漲幅","gain"),("量比","vol"),
             ("20MA乖離","bias"),("上影線%","shadow"),("收盤位置%","close_pos"),
             ("突破前20日振幅","range20")):
    split(nm,k)

up=[e for e in ev if e["mkt_up"]]; dn=[e for e in ev if not e["mkt_up"]]
print(f"\n依市場格局（31檔等權指數 vs 自身20MA）：")
for nm,g in (("指數在20MA之上",up),("指數在20MA之下",dn)):
    if not g: continue
    print(f"  {nm:<16} n={len(g):>3}  超額{st.mean([e['e10'] for e in g]):>+6.2f}%  "
          f"中位{st.median([e['e10'] for e in g]):>+6.2f}%  "
          f"勝率{sum(1 for e in g if e['e10']>0)/len(g)*100:>5.1f}%")

# 分數四分位
s=sorted(ev,key=lambda e:e["score"]); q=len(s)//4
print("\nscore 四分位：")
for i,nm in enumerate(("Q1最低","Q2","Q3","Q4最高")):
    g=s[i*q:(i+1)*q] if i<3 else s[3*q:]
    print(f"  {nm:<8} n={len(g):>3}  分數{g[0]['score']:.0f}~{g[-1]['score']:.0f}  "
          f"超額{st.mean([e['e10'] for e in g]):>+6.2f}%  勝率{sum(1 for e in g if e['e10']>0)/len(g)*100:>5.1f}%")
