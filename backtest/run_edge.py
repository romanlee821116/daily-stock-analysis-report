# -*- coding: utf-8 -*-
"""比較「水準值」與「邊緣觸發」兩種籌碼訊號定義的同日超額報酬。"""
import csv, importlib.util, os, pathlib, statistics as st, collections
# repo 根目錄由這支腳本自己的位置推導，不要寫死任何人的家目錄路徑。
# （2026-10-21 修：原本寫死 ~/mnt/... 那是 Claude 端的掛載點，
#  在使用者自己的 Mac 上一定 FileNotFoundError。）
REPO = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("bs", REPO/"tools"/"breakout_scan.py")
bs = importlib.util.module_from_spec(spec); spec.loader.exec_module(bs)
px = {}
for r in csv.DictReader(open(REPO/"backtest"/"prices.csv")):
    px.setdefault(r["code"], []).append((r["date"], float(r["high"]), float(r["low"]), float(r["close"])))
for c in px: px[c].sort()
PXD = {c: {d: i for i, (d, *_) in enumerate(b)} for c, b in px.items()}
w=[]; flows = bs.load_etf_flows(REPO/"reports", w); days = sorted(flows)
universe = sorted(set(px) & set(bs.THEMES))

def chips(c, i, lb=5):
    net, names = 0.0, set()
    for a in days[max(0,i-lb+1):i+1]:
        r = flows.get(a, {}).get(c)
        if r:
            net += r["net"]
            if r["net"] > 0: names |= set(r["buyer_list"])
    return net, len(names)

def ret(c, d, h):
    b, idx = px.get(c), PXD.get(c, {})
    if not b or d not in idx: return None
    i = idx[d]
    return (b[i+h][3]/b[i][3]-1)*100 if i+h < len(b) else None

SIGS = {
  "水準：買方>=3":      lambda c,i: (lambda n,b: n>0 and b>=3)(*chips(c,i)),
  "水準：買方>=5":      lambda c,i: (lambda n,b: n>0 and b>=5)(*chips(c,i)),
  "邊緣：檔數較昨增加":  lambda c,i: i>0 and chips(c,i)[1] > chips(c,i-1)[1] and chips(c,i)[0]>0,
  "邊緣：檔數+2以上":    lambda c,i: i>0 and chips(c,i)[1] - chips(c,i-1)[1] >= 2 and chips(c,i)[0]>0,
  "邊緣：<=1檔躍到>=3":  lambda c,i: i>0 and chips(c,i-1)[1] <= 1 and chips(c,i)[1] >= 3,
  "邊緣：淨額由負轉正":  lambda c,i: i>0 and chips(c,i-1)[0] <= 0 < chips(c,i)[0],
}
for h in (5, 10, 20):
    print(f"\n═══ 持有 {h} 日 · 同日超額報酬 ═══")
    daily = {}
    for d in days:
        v = {c: ret(c,d,h) for c in universe}
        v = {c:x for c,x in v.items() if x is not None}
        if len(v) >= 5: daily[d] = (v, sum(v.values())/len(v))
    for name, f in SIGS.items():
        ex, codes = [], collections.Counter()
        for i, d in enumerate(days):
            if d not in daily: continue
            v, mkt = daily[d]
            for c in v:
                if f(c, i): ex.append(v[c]-mkt); codes[c]+=1
        if len(ex) < 10: print(f"  {name:<16} n={len(ex)} (樣本過少)"); continue
        m = st.mean(ex); t = m/((st.pstdev(ex) or 1e-9)/len(ex)**0.5)
        print(f"  {name:<16} n={len(ex):>4}  超額{m:>+6.2f}%  中位{st.median(ex):>+6.2f}%  "
              f"勝率{sum(1 for x in ex if x>0)/len(ex)*100:>5.1f}%  t={t:>+5.2f}  {len(codes)}檔")
