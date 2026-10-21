# -*- coding: utf-8 -*-
"""
131 檔 × 2 年的決定性回測。

樣本切分（很重要）：
  起漲參數校準用 2026-09-18~10-07 的 7 個案例；排序分錨點用 2026-05~10 的訊號。
  → 2026-05-01 之前（約 1.6 年）**完全沒參與過任何校準**，是真的樣本外。
"""
import csv, importlib.util, os, pathlib, statistics as st, collections, sys
# repo 根目錄由這支腳本自己的位置推導，不要寫死任何人的家目錄路徑。
# （2026-10-21 修：原本寫死 ~/mnt/... 那是 Claude 端的掛載點，
#  在使用者自己的 Mac 上一定 FileNotFoundError。）
REPO = pathlib.Path(__file__).resolve().parent.parent
sp = importlib.util.spec_from_file_location("bs", REPO/"tools"/"breakout_scan.py")
bs = importlib.util.module_from_spec(sp); sp.loader.exec_module(bs)

DROP = {"7750", "7769"}        # 2025-04 資料可疑，見 RESULTS；--keep-all 可保留
KEEP_ALL = "--keep-all" in sys.argv
# 對照組名單只有一份，住在 tools/fetch_history.py 的 CONTROL。
# （2026-10-21 踩的坑：那邊從 7 檔擴到 32 檔，這裡忘了跟著改，
#  中立組樣本數卡在 n=31，整個宇宙偏誤檢驗等於白跑。）
_fh_spec = importlib.util.spec_from_file_location(
    "fetch_history", REPO / "tools" / "fetch_history.py")
_fh = importlib.util.module_from_spec(_fh_spec); _fh_spec.loader.exec_module(_fh)
NEUTRAL = set(_fh.CONTROL) - set(bs.THEMES)
CALIB_START = "2026-05-01"     # 這天之後才可能參與過校準

bars = {}
for r in csv.DictReader(open(REPO/"backtest"/"prices_history.csv")):
    if not KEEP_ALL and r["code"] in DROP: continue
    bars.setdefault(r["code"], []).append({"d":r["date"],"o":float(r["open"]),
        "h":float(r["high"]),"l":float(r["low"]),"c":float(r["close"]),"v":float(r["volume"])})
for c in bars: bars[c].sort(key=lambda x: x["d"])
U = sorted(bars)
IDX = {c:{x["d"]:k for k,x in enumerate(bars[c])} for c in U}
alld = sorted({x["d"] for c in U for x in bars[c]})
print(f"{len(U)} 檔 × {len(alld)} 交易日 {alld[0]} ~ {alld[-1]}"
      f"{'' if KEEP_ALL else '（已排除 7750/7769）'}")

# 每日等權報酬表，用來算同日超額
fwd = {h: {} for h in (5,10,20)}
for h in fwd:
    for d in alld:
        v=[]
        for c in U:
            i=IDX[c].get(d)
            if i is not None and i+h < len(bars[c]):
                v.append((bars[c][i+h]["c"]/bars[c][i]["c"]-1)*100)
        if len(v) >= 20: fwd[h][d] = sum(v)/len(v)

flat = {"net":0.0,"buyers":0}
WIN = 130                      # indicators 需要的最長視窗（120日量基準+5）
ev = []
for c in U:
    b = bars[c]
    for j in range(125, len(b)):
        i = bs.indicators(b[max(0,j-WIN):j+1], flat, 0, 0)
        if not i or bs.classify(i, None)[0] != "起漲": continue
        d = b[j]["d"]
        row = {"c":c,"d":d,"score":bs.score(i,"起漲"),
               "oos": d < CALIB_START, "neu": c in NEUTRAL}
        for h in (5,10,20):
            if j+h < len(b) and d in fwd[h]:
                row[f"e{h}"] = (b[j+h]["c"]/b[j]["c"]-1)*100 - fwd[h][d]
        ev.append(row)
print(f"起漲訊號 {len(ev)} 個\n")

def rep(nm, g, key="e10"):
    v=[x[key] for x in g if key in x]
    if len(v) < 8: print(f"  {nm:<30} n={len(v)} 太少"); return
    t=st.mean(v)/((st.pstdev(v) or 1e-9)/len(v)**0.5)
    print(f"  {nm:<30} n={len(v):>4}  超額{st.mean(v):>+6.2f}%  中位{st.median(v):>+6.2f}%  "
          f"勝率{sum(1 for x in v if x>0)/len(v)*100:>5.1f}%  t={t:>+5.2f}")

print("═══ 1. 真樣本外 vs 校準期（10日同日超額）═══")
rep("真樣本外 (~2026-04)", [x for x in ev if x["oos"]])
rep("校準期 (2026-05~)",   [x for x in ev if not x["oos"]])
print("\n  只看排序分>=50：")
hi=[x for x in ev if x["score"]>=bs.PARAMS["score_report_min"]]
rep("  真樣本外", [x for x in hi if x["oos"]])
rep("  校準期",   [x for x in hi if not x["oos"]])

print("\n═══ 2. 排序分四分位（全期）═══")
s=sorted(ev,key=lambda x:x["score"]); q=len(s)//4
for k,nm in enumerate(("Q1最低","Q2","Q3","Q4最高")):
    g=s[k*q:(k+1)*q] if k<3 else s[3*q:]
    rep(f"{nm}（{g[0]['score']:.0f}~{g[-1]['score']:.0f}）", g)

print("\n═══ 3. 分數門檻（只用真樣本外）═══")
oos=[x for x in ev if x["oos"]]
for thr in (0,30,40,50,60):
    rep(f"分數>={thr}", [x for x in oos if x["score"]>=thr])

print("\n═══ 4. 持有期（真樣本外，分數>=50）═══")
g=[x for x in oos if x["score"]>=50]
for h in (5,10,20): rep(f"持有{h}日", g, f"e{h}")

print("\n═══ 5. 汙染組 vs 中立組（真樣本外）═══")
rep("汙染組(THEMES)", [x for x in oos if not x["neu"]])
rep("中立組(7檔)",     [x for x in oos if x["neu"]])

print("\n═══ 6. 逐季（全部訊號，10日）═══")
def q_of(d):
    y,m=int(d[:4]),int(d[5:7]); return f"{y}Q{(m-1)//3+1}"
for qq in sorted({q_of(x["d"]) for x in ev}):
    rep(qq, [x for x in ev if q_of(x["d"])==qq])

print("\n═══ 7. 事件重疊檢查：日叢集穩健 t ═══")
# 同一天同族群會一起觸發，訊號之間不獨立；把每日先平均再對「日」做 t 檢定。
def clustered(g, key="e10", label=""):
    byd=collections.defaultdict(list)
    for x in g:
        if key in x: byd[x["d"]].append(x[key])
    if len(byd) < 8: print(f"  {label:<28} 交易日數={len(byd)} 太少"); return
    daily=[sum(v)/len(v) for v in byd.values()]
    n=len(daily); m=st.mean(daily); t=m/((st.pstdev(daily) or 1e-9)/n**0.5)
    raw=[x[key] for x in g if key in x]
    rt=st.mean(raw)/((st.pstdev(raw) or 1e-9)/len(raw)**0.5)
    print(f"  {label:<28} 訊號{len(raw):>4} 散在 {n:>3} 個交易日  "
          f"每日平均超額{m:>+6.2f}%  t(日)={t:>+5.2f}   （原始 t={rt:+.2f}）")

oos=[x for x in ev if x["oos"]]
clustered(oos, "e10", "真樣本外 全部")
clustered([x for x in oos if x["score"]>=50], "e10", "真樣本外 分數>=50")
clustered([x for x in oos if x["score"]>=60], "e10", "真樣本外 分數>=60")
clustered([x for x in oos if x["score"]>=50], "e20", "真樣本外 分數>=50（20日）")
clustered(ev, "e10", "全期 全部")

print("\n  每日訊號數分佈：")
cnt=collections.Counter(x["d"] for x in ev)
vals=sorted(cnt.values())
print(f"    有訊號的交易日 {len(cnt)} 天；每日訊號數 中位{vals[len(vals)//2]}、"
      f"最多{max(vals)}、>=10檔的日子有 {sum(1 for v in vals if v>=10)} 天")

print("\n═══ 8. 扣成本後（來回 0.44%：手續費0.285%+證交稅0.15%，不含滑價）═══")
COST=0.44
for nm,g,key in (("分數>=50 持有10日",[x for x in oos if x["score"]>=50],"e10"),
                 ("分數>=50 持有20日",[x for x in oos if x["score"]>=50],"e20"),
                 ("分數>=60 持有20日",[x for x in oos if x["score"]>=60],"e20")):
    v=[x[key]-COST for x in g if key in x]
    if len(v)<8: continue
    byd=collections.defaultdict(list)
    for x in g:
        if key in x: byd[x["d"]].append(x[key]-COST)
    daily=[sum(a)/len(a) for a in byd.values()]
    t=st.mean(daily)/((st.pstdev(daily) or 1e-9)/len(daily)**0.5)
    print(f"  {nm:<22} n={len(v):>4}  淨超額{st.mean(v):>+6.2f}%  "
          f"中位{st.median(v):>+6.2f}%  勝率{sum(1 for x in v if x>0)/len(v)*100:>5.1f}%  t(日)={t:>+5.2f}")
