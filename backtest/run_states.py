# -*- coding: utf-8 -*-
"""直接測 breakout_scan.py 的「起漲」「潛伏」條件本身的前瞻超額報酬。"""
import csv, importlib.util, os, pathlib, statistics as st, collections
# repo 根目錄由這支腳本自己的位置推導，不要寫死任何人的家目錄路徑。
# （2026-10-21 修：原本寫死 ~/mnt/... 那是 Claude 端的掛載點，
#  在使用者自己的 Mac 上一定 FileNotFoundError。）
REPO = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("bs", REPO/"tools"/"breakout_scan.py")
bs = importlib.util.module_from_spec(spec); spec.loader.exec_module(bs)
P = bs.PARAMS

bars = {}
for r in csv.DictReader(open(REPO/"backtest"/"prices.csv")):
    bars.setdefault(r["code"], []).append({"d": r["date"], "o": float(r["open"]),
        "h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"]), "v": float(r["volume"])})
for c in bars: bars[c].sort(key=lambda x: x["d"])
w=[]; flows = bs.load_etf_flows(REPO/"reports", w); fdays = sorted(flows)
universe = sorted(set(bars) & set(bs.THEMES))
alldates = sorted({b["d"] for c in universe for b in bars[c]})

def ind_at(c, j):
    """用 breakout_scan 的 indicators()，但只餵到第 j 根（含）。"""
    hist = bars[c][:j+1]
    if len(hist) < 25: return None
    fi = max([i for i, a in enumerate(fdays) if a <= hist[-1]["d"]], default=-1)
    fl = bs.etf_recent(flows, c, fdays[:fi+1], P["latent_etf_lookback"]) if fi >= 0 else {"net":0.0,"buyers":0}
    return bs.indicators(hist, fl, 0, 0)

def excess(events, h):
    by_day = collections.defaultdict(list)
    for c, j in events: by_day[bars[c][j]["d"]].append((c, j))
    out, codes = [], collections.Counter()
    for d, evs in by_day.items():
        pool = []
        for c in universe:
            idx = {b["d"]: i for i, b in enumerate(bars[c])}
            if d in idx and idx[d]+h < len(bars[c]):
                pool.append((bars[c][idx[d]+h]["c"]/bars[c][idx[d]]["c"]-1)*100)
        if len(pool) < 5: continue
        mkt = sum(pool)/len(pool)
        for c, j in evs:
            if j+h < len(bars[c]):
                out.append((bars[c][j+h]["c"]/bars[c][j]["c"]-1)*100 - mkt); codes[c]+=1
    return out, codes

CONDS = {}
def launch(i):
    return (i["close"] > i["hi_n"] and i["vol_ratio"] and i["vol_ratio"] >= P["launch_vol_ratio_min"]
            and i["day_gain"] >= P["launch_day_gain_min"]
            and i["upper_shadow_ratio"] <= P["launch_upper_shadow_max"]
            and i["ma20_bias"] is not None and i["ma20_bias"] <= P["launch_ma20_bias_max"])
def launch_nochip(i):   # 只有突破+量，不看漲幅/影線
    return i["close"] > i["hi_n"] and i["vol_ratio"] and i["vol_ratio"] >= P["launch_vol_ratio_min"]
def latent_nomA60(i):   # 潛伏去掉 60MA（資料長度不足）
    chips = (i["etf_net"] > 0 and i["etf_buyers"] >= P["latent_etf_buyers_min"])
    return chips and i["gain5"] is not None and i["gain5"] < P["latent_gain5_max"]
CONDS = {"起漲（完整5條件）": launch, "只要『破20日高+量比1.5』": launch_nochip,
         "潛伏（去掉60MA條件）": latent_nomA60}

cache = {}
for c in universe:
    for j in range(len(bars[c])):
        x = ind_at(c, j)
        if x: cache[(c, j)] = x

print(f"價格涵蓋 {len(universe)} 檔、{len(alldates)} 交易日；可判定的檔日 {len(cache)}\n")
for name, f in CONDS.items():
    ev = [(c, j) for (c, j), i in cache.items() if f(i)]
    print(f"── {name}：觸發 {len(ev)} 檔日 ──")
    if not ev: print("   無觸發\n"); continue
    for h in (5, 10, 20):
        ex, codes = excess(ev, h)
        if len(ex) < 8: print(f"   {h:>2}日: n={len(ex)} 樣本過少"); continue
        m = st.mean(ex); t = m/((st.pstdev(ex) or 1e-9)/len(ex)**0.5)
        print(f"   {h:>2}日: n={len(ex):>3}  超額{m:>+6.2f}%  中位{st.median(ex):>+6.2f}%  "
              f"勝率{sum(1 for x in ex if x>0)/len(ex)*100:>5.1f}%  t={t:>+5.2f}  {len(codes)}檔")
    print()
