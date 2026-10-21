# -*- coding: utf-8 -*-
"""
ETF 籌碼訊號 → 前瞻報酬回測。
訊號定義與 breakout_scan.py 的「潛伏」籌碼條件一致（近5日去重 ETF 買方檔數）。
進場假設：訊號日收盤買進（不含滑價與手續費）。
"""
import csv, importlib.util, os, pathlib, statistics as st

# repo 根目錄由這支腳本自己的位置推導，不要寫死任何人的家目錄路徑。
# （2026-10-21 修：原本寫死 ~/mnt/... 那是 Claude 端的掛載點，
#  在使用者自己的 Mac 上一定 FileNotFoundError。）
REPO = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("bs", REPO / "tools" / "breakout_scan.py")
bs = importlib.util.module_from_spec(spec); spec.loader.exec_module(bs)

# ---- 價格 ----
px = {}
for r in csv.DictReader(open(REPO / "backtest" / "prices.csv")):
    px.setdefault(r["code"], []).append(
        (r["date"], float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])))
for c in px: px[c].sort()
PXD = {c: {d: i for i, (d, *_) in enumerate(b)} for c, b in px.items()}

# ---- ETF 金流 ----
w = []
flows = bs.load_etf_flows(REPO / "reports", w)
days = sorted(flows)

def chips(code, i, lookback=5):
    net, names = 0.0, set()
    for a in days[max(0, i - lookback + 1): i + 1]:
        r = flows.get(a, {}).get(code)
        if r:
            net += r["net"]
            if r["net"] > 0: names |= set(r["buyer_list"])
    return net, len(names)

def fwd(code, d, h):
    """訊號日 d 收盤進場，持有 h 個交易日的報酬 % 與期間最大漲幅 %。"""
    b, idx = px.get(code), PXD.get(code, {})
    if not b or d not in idx: return None
    i = idx[d]
    if i + h >= len(b): return None
    entry = b[i][4]
    ret = (b[i + h][4] / entry - 1) * 100
    mx = (max(x[2] for x in b[i + 1:i + h + 1]) / entry - 1) * 100
    mn = (min(x[3] for x in b[i + 1:i + h + 1]) / entry - 1) * 100
    return ret, mx, mn

# ---- 基準：同一天、同一池、所有有價格的股票（控制組） ----
def summarize(rows, label):
    if not rows:
        print(f"{label:<22}  n=0"); return
    r = [x[0] for x in rows]
    win = sum(1 for v in r if v > 0) / len(r) * 100
    print(f"{label:<22}  n={len(r):>4}  平均{st.mean(r):>+7.2f}%  "
          f"中位{st.median(r):>+7.2f}%  勝率{win:>5.1f}%  "
          f"最大回撤中位{st.median([x[2] for x in rows]):>+6.2f}%")

universe = sorted(set(px) & set(bs.THEMES))
print(f"價格涵蓋 {len(universe)} 檔；ETF 交易日 {len(days)} 天 "
      f"({days[0]} ~ {days[-1]})\n")

for h in (5, 10, 20):
    print(f"═══ 持有 {h} 個交易日 ═══")
    base = []
    for i, d in enumerate(days):
        for c in universe:
            f = fwd(c, d, h)
            if f: base.append(f)
    summarize(base, "基準（全池全日）")
    for k in (2, 3, 4, 5):
        ev = []
        for i, d in enumerate(days):
            for c in universe:
                net, nb = chips(c, i)
                if net > 0 and nb >= k:
                    f = fwd(c, d, h)
                    if f: ev.append(f)
        summarize(ev, f"ETF買方>={k}檔")
    print()

# ══════════ 剝除市場因子：同日相對報酬（訊號股 − 當日全池平均） ══════════
print("═" * 62)
print("同日相對報酬（已剝除大盤／族群共同漲跌）")
print("═" * 62)
import collections
for h in (5, 10, 20):
    print(f"\n--- 持有 {h} 日 ---")
    daily = {}
    for i, d in enumerate(days):
        vals = {c: fwd(c, d, h) for c in universe}
        vals = {c: v[0] for c, v in vals.items() if v}
        if len(vals) >= 5:
            daily[d] = (vals, sum(vals.values()) / len(vals))
    for k in (2, 3, 4, 5):
        ex, codes = [], collections.Counter()
        for i, d in enumerate(days):
            if d not in daily: continue
            vals, mkt = daily[d]
            for c, v in vals.items():
                net, nb = chips(c, i)
                if net > 0 and nb >= k:
                    ex.append(v - mkt); codes[c] += 1
        if not ex:
            print(f"  買方>={k}: n=0"); continue
        m = st.mean(ex); sd = st.pstdev(ex) or 1e-9
        t = m / (sd / len(ex) ** 0.5)
        top = codes.most_common(3)
        print(f"  買方>={k}:  n={len(ex):>4}  超額平均{m:>+6.2f}%  "
              f"中位{st.median(ex):>+6.2f}%  勝率{sum(1 for v in ex if v>0)/len(ex)*100:>5.1f}%  "
              f"t={t:>+5.2f}  涵蓋{len(codes)}檔 前3:{','.join(f'{a}×{b}' for a,b in top)}")
