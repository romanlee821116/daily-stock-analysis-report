# -*- coding: utf-8 -*-
"""
把 ETF 報告當「第一層過濾」測：訊號日 D 時，該股近期是否出現在 ETF 報告裡？
⚠️ 嚴格 point-in-time：ETF 報告是盤後產出，所以 D 當天只能用 as_of <= D-1 的報告。
"""
import csv, importlib.util, os, pathlib, statistics as st, collections
# repo 根目錄由這支腳本自己的位置推導，不要寫死任何人的家目錄路徑。
# （2026-10-21 修：原本寫死 ~/mnt/... 那是 Claude 端的掛載點，
#  在使用者自己的 Mac 上一定 FileNotFoundError。）
REPO = pathlib.Path(__file__).resolve().parent.parent
sp=importlib.util.spec_from_file_location("bs",REPO/"tools"/"breakout_scan.py")
bs=importlib.util.module_from_spec(sp); sp.loader.exec_module(bs)

bars={}
for fn in ("prices_all.csv","prices_neutral.csv"):
    for r in csv.DictReader(open(REPO/"backtest"/fn)):
        bars.setdefault(r["code"],[]).append({"d":r["date"],"o":float(r["open"]),"h":float(r["high"]),
            "l":float(r["low"]),"c":float(r["close"]),"v":float(r["volume"])})
for c in bars: bars[c].sort(key=lambda x:x["d"])
bars={c:v for c,v in bars.items() if len(v)>=100}
U=sorted(bars); IDX={c:{x["d"]:k for k,x in enumerate(bars[c])} for c in U}
w=[]; flows=bs.load_etf_flows(REPO/"reports",w); fdays=sorted(flows)
print(f"價格 {len(U)} 檔；ETF 報告 {len(fdays)} 天 {fdays[0]}~{fdays[-1]}")

def pit(code, d, lb):
    """D 日可用的報告只到 D-1。回傳 (有沒有出現, 淨額, 去重買方檔數)。"""
    use=[a for a in fdays if a < d][-lb:]
    net, names, seen = 0.0, set(), False
    for a in use:
        r=flows.get(a,{}).get(code)
        if r:
            seen=True; net+=r["net"]
            if r["net"]>0: names|=set(r["buyer_list"])
    return seen, round(net,2), len(names)

def exc(c,j,h=10):
    b=bars[c]
    if j+h>=len(b): return None
    d=b[j]["d"]; pool=[]
    for x in U:
        if d in IDX[x] and IDX[x][d]+h<len(bars[x]):
            pool.append((bars[x][IDX[x][d]+h]["c"]/bars[x][IDX[x][d]]["c"]-1)*100)
    if len(pool)<8: return None
    return (b[j+h]["c"]/b[j]["c"]-1)*100-sum(pool)/len(pool)

flat={"net":0.0,"buyers":0}
ev=[]
for c in U:
    b=bars[c]
    for j in range(25,len(b)):
        d=b[j]["d"]
        if d <= fdays[0]: continue           # 報告涵蓋期之前不評估
        i=bs.indicators(b[:j+1],flat,0,0)
        if not i or bs.classify(i,None)[0]!="起漲": continue
        e=exc(c,j)
        if e is None: continue
        s5,net5,nb5 = pit(c,d,5)
        s10,_,_     = pit(c,d,10)
        ev.append({"c":c,"d":d,"e":e,"score":bs.score(i,"起漲"),
                   "in5":s5,"in10":s10,"net5":net5,"nb5":nb5})
print(f"報告涵蓋期內的起漲訊號：{len(ev)} 個\n")

def rep(nm,g):
    if len(g)<4: print(f"  {nm:<34} n={len(g)} 太少"); return
    e=[x["e"] for x in g]; t=st.mean(e)/((st.pstdev(e) or 1e-9)/len(e)**0.5)
    print(f"  {nm:<34} n={len(g):>3}  超額{st.mean(e):>+6.2f}%  中位{st.median(e):>+6.2f}%  "
          f"勝率{sum(1 for x in e if x>0)/len(e)*100:>5.1f}%  t={t:>+5.2f}")
print("ETF 第一層過濾（嚴格 point-in-time，只用 D-1 以前的報告）：")
rep("不過濾（全部訊號）", ev)
rep("近5日報告有出現", [x for x in ev if x["in5"]])
rep("近5日報告沒出現", [x for x in ev if not x["in5"]])
rep("近10日報告有出現", [x for x in ev if x["in10"]])
rep("近5日出現且淨買>0", [x for x in ev if x["in5"] and x["net5"]>0])
rep("近5日淨買>0 且買方>=2檔", [x for x in ev if x["net5"]>0 and x["nb5"]>=2])
rep("近5日淨買>0 且買方>=3檔", [x for x in ev if x["net5"]>0 and x["nb5"]>=3])
rep("近5日淨賣（淨額<0）", [x for x in ev if x["in5"] and x["net5"]<0])
print("\n疊加排序分 >=50：")
hi=[x for x in ev if x["score"]>=50]
rep("排序分>=50（不看ETF）", hi)
rep("排序分>=50 且 近5日有出現", [x for x in hi if x["in5"]])
rep("排序分>=50 且 近5日淨買>0", [x for x in hi if x["net5"]>0])
