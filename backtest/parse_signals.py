#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_signals.py — ETF 共識買盤訊號面板（回測用）

⚠️ 這支程式**不自己解析 HTML**。
解析器只有一份，住在 tools/breakout_scan.py 的 load_etf_flows()。
2026-10-19 之前這裡有第二份解析器，結果兩邊對同一天同一檔給出不同的買方檔數
（51 筆不一致），所以合併掉了。要改解析行為請改 breakout_scan.py，不要改這裡。

執行：python3 backtest/parse_signals.py
輸出：backtest/signal_panel.csv
"""

from __future__ import annotations

import csv
import importlib.util
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCANNER = REPO / "tools" / "breakout_scan.py"
OUT = REPO / "backtest" / "signal_panel.csv"


def load_scanner():
    if not SCANNER.exists():
        sys.exit(f"找不到解析器 {SCANNER}")
    spec = importlib.util.spec_from_file_location("breakout_scan", SCANNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    bs = load_scanner()
    warnings: list[str] = []
    flows = bs.load_etf_flows(REPO / "reports", warnings)

    rows = []
    for as_of in sorted(flows):
        for code, r in flows[as_of].items():
            rows.append({
                "date": as_of,
                "code": code,
                "name": r["name"],
                "net_yi": r["net"],
                "n_buy": r["buyers"],
                "n_sell": r["sellers"],
                "theme": r["theme"],
                "buyers": "|".join(r["buyer_list"]),
                "sellers": "|".join(r["seller_list"]),
            })
    rows.sort(key=lambda x: (x["date"], -abs(x["net_yi"])))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    days = sorted({r["date"] for r in rows})
    idx = {d: i for i, d in enumerate(days)}
    n = len(days)

    print(f"交易日   : {n}  {days[0]} .. {days[-1]}")
    print(f"面板筆數 : {len(rows)}")
    print(f"個股數   : {len({r['code'] for r in rows})}")
    print(f"有ETF名單: {sum(1 for r in rows if r['buyers'] or r['sellers'])}")
    for w_ in warnings:
        print("WARN:", w_)

    print("\n=== 訊號事件數與可計算前瞻報酬的樣本數 ===")
    print(f"{'門檻':>8}{'事件數':>8}{'可算5日':>9}{'可算10日':>10}{'可算20日':>10}")
    for k in (3, 4, 5, 6):
        ev = [r for r in rows if r["n_buy"] >= k]
        c = [sum(1 for r in ev if idx[r["date"]] + h < n) for h in (5, 10, 20)]
        print(f"{'買方>=' + str(k):>8}{len(ev):>8}{c[0]:>9}{c[1]:>10}{c[2]:>10}")

    ev3 = [r for r in rows if r["n_buy"] >= 3]
    u = Counter(r["code"] for r in ev3)
    print(f"\n買方>=3 的 {len(ev3)} 筆事件涵蓋 {len(u)} 檔；"
          f"前 25 檔佔 {sum(c for _, c in u.most_common(25)) / len(ev3) * 100:.0f}%")
    (REPO / "backtest" / "top25.txt").write_text(
        "\n".join(f"{c} {next(r['name'] for r in rows if r['code'] == c)}"
                  for c, _ in u.most_common(25)) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
