# -*- coding: utf-8 -*-
"""31 檔 × 2026-05~10 的最終驗證（價格已做除權息還原）。"""
import csv, importlib.util, os, pathlib, statistics as st, collections
REPO=pathlib.Path(os.path.expanduser("~/mnt/daily-stock-analysis-report"))
sp=importlib.util.spec_from_file_location("bs",REPO/"tools"/"breakout_scan.py")
bs=importlib.util.module_from_spec(sp); sp.loader.exec_module(bs)
bars={}
for r in csv.DictReader(open(REPO/"backtest"/"prices_all.csv")):
    bars.setdefault(r["code"],[]).append({"d":r["date"],"o":float(r["open"]),"h":float(r["high"]),
        "l":float(r["low"]),"c":float(r["close"]),"v":float(r["volume"])})
for c in bars: bars[c].sort(key=lambda x:x["d"])
U=sorted(c for c in bars if len(bars[c])>=100)
flat={"net":0.0,"buyers":0}
print(f"樣本 {len(U)} 檔，{min(b['d'] for c in U for b in bars[c])} ~ "
      f"{max(b['d'] for c in U for b in bars[c])}\n")

ev=[]; truth=collections.defaultdict(list)
def seg(d): return "樣本外 05~07" if d<"2026-08-01" else ("過渡 08~09中" if d<"2026-09-18" else "樣本內 09-18~")
rows=collections.defaultdict(lambda:{"t":0,"T":0,"h":0,"r":[]})
for c in U:
    b=bars[c]
    for j in range(25,len(b)):
        i=bs.indicators(b[:j+1],flat,0,0)
        if not i: continue
        s=seg(b[j]["d"]); trig=bs.classify(i,None)[0]=="起漲"
        tr=False
        if j+10<len(b) and b[j]["c"]>i["hi_n"]:
            tr=(max(x["h"] for x in b[j+1:j+11])/b[j]["c"]-1)*100>=15
        if tr: rows[s]["T"]+=1
        if trig:
            ev.append((b[j]["d"],c,j)); rows[s]["t"]+=1
            if tr: rows[s]["h"]+=1
            if j+10<len(b): rows[s]["r"].append((b[j+10]["c"]/b[j]["c"]-1)*100)
print(f"{'期間':<16}{'觸發':>5}{'真實起漲':>9}{'抓到':>5}{'召回':>7}{'精準':>7}{'10日平均':>10}{'10日中位':>10}")
print("─"*72)
for s in ("樣本外 05~07","過渡 08~09中","樣本內 09-18~"):
    v=rows[s]; rec=v["h"]/v["T"]*100 if v["T"] else 0; pre=v["h"]/v["t"]*100 if v["t"] else 0
    a=f"{st.mean(v['r']):+.2f}%" if v["r"] else "—"; m=f"{st.median(v['r']):+.2f}%" if v["r"] else "—"
    print(f"{s:<16}{v['t']:>5}{v['T']:>9}{v['h']:>5}{rec:>6.0f}%{pre:>6.0f}%{a:>10}{m:>10}")

def excess(h):
    out=[]
    for d,c,j in ev:
        pool=[]
        for x in U:
            idx={b["d"]:k for k,b in enumerate(bars[x])}
            if d in idx and idx[d]+h<len(bars[x]):
                pool.append((bars[x][idx[d]+h]["c"]/bars[x][idx[d]]["c"]-1)*100)
        if len(pool)<8 or j+h>=len(bars[c]): continue
        out.append((bars[c][j+h]["c"]/bars[c][j]["c"]-1)*100-sum(pool)/len(pool))
    return out
print(f"\n全期 {len(ev)} 次訊號 · 同日超額報酬（剝除市場）")
for h in (5,10,20):
    e=excess(h)
    if len(e)<5: continue
    t=st.mean(e)/((st.pstdev(e) or 1e-9)/len(e)**0.5)
    print(f"  {h:>2}日 n={len(e):>3}  超額{st.mean(e):>+6.2f}%  中位{st.median(e):>+6.2f}%  "
          f"勝率{sum(1 for x in e if x>0)/len(e)*100:>5.1f}%  t={t:>+5.2f}")

raw,stp=[],[]
for d,c,j in ev:
    b=bars[c]
    if j+10>=len(b): continue
    e0,s0=b[j]["c"],b[j]["l"]
    raw.append((b[j+10]["c"]/e0-1)*100)
    o=next(((b[k]["c"]/e0-1)*100 for k in range(j+1,j+11) if b[k]["c"]<s0),None)
    stp.append(o if o is not None else (b[j+10]["c"]/e0-1)*100)
print(f"\n停損效果（n={len(raw)}）")
for nm,v in (("不設停損",raw),("跌破起漲日最低",stp)):
    print(f"  {nm:<14}平均{st.mean(v):>+7.2f}%  中位{st.median(v):>+7.2f}%  "
          f"最差{min(v):>+7.2f}%  勝率{sum(1 for x in v if x>0)/len(v)*100:>5.1f}%")

mon=collections.Counter(d[:7] for d,_,_ in ev)
print("\n各月觸發 vs 當月平均")
for m in sorted({b["d"][:7] for c in U for b in bars[c]}):
    rs=[]
    for c in U:
        s=[b for b in bars[c] if b["d"][:7]==m]
        if len(s)>=5: rs.append((s[-1]["c"]/s[0]["o"]-1)*100)
    if rs: print(f"  {m}  觸發 {mon[m]:>2} 次   當月平均 {st.mean(rs):>+6.1f}%")
