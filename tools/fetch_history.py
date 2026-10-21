#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_history.py — 一次把觀察池的歷史日線抓齊，輸出回測用的 CSV。

為什麼需要這支：
    雲端沙箱連不到任何台股資料源（TWSE/TPEx/Yahoo 全被 egress 擋掉），
    回測的價格是靠 WebFetch 一檔一月手搬的，38 檔就到極限。
    這支在「你的 Mac」上跑，走 yfinance，一次抓完 124 檔。

用法：
    python3 -m pip install --user yfinance        # 只需一次
    python3 tools/fetch_history.py                # 預設：觀察池 + 對照組，近 2 年
    python3 tools/fetch_history.py --years 3
    python3 tools/fetch_history.py --codes 2330,2454 --out backtest/spot.csv
    python3 tools/fetch_history.py --resume       # 只補 CSV 裡還沒有的代號

輸出欄位與 backtest/prices_all.csv 相同：code,date,open,high,low,close,volume

⚠️ 價格慣例（跟既有的 prices_all.csv 一致，不要改）
    用 auto_adjust=False 取原始 OHLC（yfinance 已處理分割，但不處理除息），
    再跑「±11% 跳空 → 向前還原」。台股日漲跌幅 ±10%，相鄰交易日超過 ±11%
    必定是公司行為而不是行情。不還原的話除息日會變成假崩跌，觸發假停損。
    實例：2026-09-01→09-02 緯穎 −66.5%（1:3 分割）、2026-06-17 長榮 −12.0%（除息）。
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import sys
import time
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCANNER = REPO / "tools" / "breakout_scan.py"

# 對照組：確認完全沒出現在任何 ETF 報告裡的上市股，用來檢驗宇宙選擇偏誤。
# 見 backtest/RESULTS_20261019.md 第七輪。
# ⚠️ 這份名單會「過期」。ETF 報告每天新增，昨天乾淨的股票今天可能就被買進去了。
# 實例：2609 陽明原本在對照組，2026-10-21 重新檢查時已經出現在報告裡，必須移除。
# 程式每次執行都會自動重新驗證，被汙染的會印出來並自動剔除——不要手動忽略那個警告。
#
# 選股原則：THEMES 的日波動度中位數約 3.56%，對照組不能全是低波動的權值股，
# 否則「訊號在對照組無效」會分不清是宇宙偏誤還是 beta 差異。所以高低波動都放。
CONTROL = {
    # 偏高波動
    "2049": "上銀", "2492": "華新科", "2458": "義隆", "2637": "慧洋-KY",
    "2606": "裕民", "2542": "興富發", "1536": "和大", "2231": "為升",
    "2548": "華固", "5522": "遠雄", "9945": "潤泰新", "1319": "東陽",
    "2014": "中鴻", "2015": "豐興", "1609": "大亞",
    # 偏低波動
    "2002": "中鋼", "2912": "統一超", "2207": "和泰車", "2633": "台灣高鐵",
    "5880": "合庫金", "2801": "彰銀", "1227": "佳格", "1702": "南僑",
    "1229": "聯華", "9933": "中鼎", "1210": "大成", "1434": "福懋",
    "2105": "正新", "2201": "裕隆", "2204": "中華", "9904": "寶成",
    "9910": "豐泰",
}

GAP_LIMIT = 0.11          # 台股 ±10% 漲跌幅，超過 11% 視為公司行為
MAX_SESSION_GAP_DAYS = 6  # 相鄰 bar 超過這麼多日曆天就不當成單日跳空
BIG_ADJUST = 0.20         # 還原幅度超過這個就要人工對公司行為公告
MIN_BARS = 100            # 低於這個根數的代號不寫出（回測用不上）


def load_scanner():
    """解析器與取價邏輯只有一份，住在 breakout_scan.py。"""
    if not SCANNER.exists():
        sys.exit(f"找不到 {SCANNER}")
    spec = importlib.util.spec_from_file_location("breakout_scan", SCANNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


EPS = 0.005          # 容忍 yfinance 的浮點誤差（半分錢）

def sane(bars):
    """
    OHLC 合理性檢查。回傳 (壞列索引, 問題描述)。

    ⚠️ 只差一點點的視為浮點雜訊直接夾回去，不算壞列。
    實例：4991 於 2024-09-20 回 o=40.0 h=40.0 l=39.0 c=38.900001525878906，
    close 比 low 還低 0.1 —— 那是真的資料錯誤，不是浮點誤差，要剔除該列。
    舊版會因為這一列就丟掉整檔，太粗暴。
    """
    bad_idx, notes = [], []
    for i, b in enumerate(bars):
        hi_ok = b["h"] >= max(b["o"], b["c"]) - EPS
        lo_ok = b["l"] <= min(b["o"], b["c"]) + EPS
        # l <= h 也要給容差，否則「low 比 high 高 0.002」這種純浮點雜訊會被判成壞列。
        # 注意容差只放在比較上，不先夾值再比 —— 先夾的話 4991 那種
        # 「close 比 low 低 0.1」的真錯誤會被夾成合法，就漏掉了。
        if hi_ok and lo_ok and b["l"] <= b["h"] + EPS and b["l"] > 0 and b["v"] >= 0:
            # 夾回浮點雜訊
            b["h"] = max(b["h"], b["o"], b["c"])
            b["l"] = min(b["l"], b["o"], b["c"])
            continue
        bad_idx.append(i)
        notes.append(f"{b['d']} OHLC 不合理 o={b['o']:g} h={b['h']:g} "
                     f"l={b['l']:g} c={b['c']:g}")
    return bad_idx, notes


def _daydiff(a: str, b: str) -> int:
    ya, ma, da = (int(x) for x in a.split("-"))
    yb, mb, db = (int(x) for x in b.split("-"))
    return (date(yb, mb, db) - date(ya, ma, da)).days


def backadjust(bars):
    """
    就地向前還原除權息／分割造成的跳空。回傳 (已還原紀錄, 待人工確認的警告)。

    ⚠️ 只還原「向下」且「相鄰交易日」的跳空。踩過的坑（2026-10-21 Roman 實跑）：

    1. 向上跳空不自動還原。除權、除息、分割一律讓價格往**下**跳；
       向上跳空多半是資料缺漏或錯誤（減資確實會往上跳，但很罕見，
       寧可列出來讓人確認，也不要自動竄改真實行情）。
       實例：7769 在 2025-04 被「還原」了 +26.8%、+11.4%；7750 +19.5%。
       那段是 2025 年 4 月關稅崩盤後的反彈，是真行情，不是公司行為。

    2. 相鄰兩根 bar 若隔了超過 6 個日曆天（含連假約 4 天 ＋ 緩衝），
       代表資料本身有缺漏，兩根之間的落差不能當成單日跳空。
       實例：7769 2025-04-02→04-07 −33.3%，中間隔清明連假且有缺漏，
       台股單日跌幅上限 10%，不可能一根跌 33%。

    3. 同一檔還原超過 2 次就標記為可疑——正常個股半年內不會有三次公司行為。
    """
    notes, warns = [], []
    factors = [1.0] * len(bars)
    for i in range(1, len(bars)):
        p, q = bars[i - 1]["c"], bars[i]["c"]
        if p <= 0:
            continue
        ch = q / p - 1
        if abs(ch) <= GAP_LIMIT:
            continue
        span = _daydiff(bars[i - 1]["d"], bars[i]["d"])
        tag = f"{bars[i-1]['d']}→{bars[i]['d']} {ch*100:+.1f}%"
        if span > MAX_SESSION_GAP_DAYS:
            warns.append(f"{tag} 相隔 {span} 天，資料可能有缺漏 → 不還原，請人工確認")
            continue
        if ch > 0:
            warns.append(f"{tag} 向上跳空（除權息只會往下）→ 不還原，"
                         f"若確為減資請手動處理")
            continue
        k = q / p
        for j in range(i):
            factors[j] *= k
        notes.append(f"{tag} → 之前價格 ×{k:.4f}")
        # 單日跌超過 20% 只可能是大比例除權或分割（例如緯穎 1:3 的 −66.5%），
        # 也可能是資料錯。照樣還原，但一定要讓人看到去對一次公司行為公告。
        if ch < -BIG_ADJUST:
            warns.append(f"{tag} 幅度很大，已還原但請對照公司行為公告確認")
    if notes:
        for b, f in zip(bars, factors):
            for col in ("o", "h", "l", "c"):
                b[col] *= f
    if len(notes) > 2:
        warns.append(f"半年內還原 {len(notes)} 次，異常偏多，建議人工覆核這檔")
    return notes, warns


def selftest() -> None:
    """純邏輯自測：不需要網路或 yfinance。"""
    fails = []
    def check(name, cond):
        print(f"  {'PASS' if cond else 'FAIL'}  {name}")
        if not cond: fails.append(name)

    def mk(closes, start="2026-01-05", step=1):
        """連續交易日（預設每天一根，不跨週末問題：用 1 月的連續日即可）。"""
        y, m, d0 = (int(x) for x in start.split("-"))
        out = []
        for i, c in enumerate(closes):
            dd = date(y, m, d0) + timedelta(days=i * step)
            out.append({"d": dd.isoformat(), "o": c, "h": c, "l": c, "c": c, "v": 1000.0})
        return out

    print("OHLC 合理性：")
    check("正常 bar 無問題",
          sane([{"d":"2026-01-05","o":10,"h":11,"l":9,"c":10.5,"v":100}])[0] == [])
    # 4991 實例：close 比 low 低 0.1，是真錯誤
    idx, notes = sane([{"d":"2024-09-20","o":40.0,"h":40.0,"l":39.0,
                        "c":38.900001525878906,"v":100}])
    check("close 低於 low → 標為壞列", idx == [0])
    # 浮點雜訊應被夾回而非判壞（yfinance 最常見：close 比 high 高十億分之一）
    b = [{"d":"2026-01-05","o":10.0,"h":10.0,"l":9.9,"c":10.000000001,"v":100}]
    idx2, _ = sane(b)
    check("close 微幅高於 high → 夾回、不算壞列",
          idx2 == [] and b[0]["h"] >= b[0]["c"])
    # low 比 high 高一點點，也是雜訊
    b2b = [{"d":"2026-01-05","o":10.0,"h":9.999,"l":10.001,"c":10.0,"v":100}]
    check("low 微幅高於 high → 夾回、不算壞列", sane(b2b)[0] == [])
    # 但差 0.1 就是真錯誤，不能被容差吃掉
    check("差 0.1 仍判為壞列（4991 實例不得漏掉）",
          sane([{"d":"2024-09-20","o":40.0,"h":40.0,"l":39.0,
                 "c":38.900001525878906,"v":100}])[0] == [0])
    check("壞列只標那一列，不影響其他列",
          sane([{"d":"2026-01-05","o":10,"h":11,"l":9,"c":10,"v":100},
                {"d":"2026-01-06","o":10,"h":10,"l":9,"c":11,"v":100}])[0] == [1])

    print("跳空還原（只還原向下、且相鄰交易日）：")
    b = mk([7800, 2610, 2600])                       # 緯穎 1:3 分割
    adj, warn = backadjust(b)
    # 註：−66.5% 超過 BIG_ADJUST，所以「有還原」＋「有提醒對公告」都是預期行為。
    check("向下跳空（分割）有還原", len(adj) == 1)
    check("大幅分割只給提醒、不阻止還原",
          len(warn) == 1 and "公司行為公告" in warn[0])
    check("分割前價格縮為 1/3", abs(b[0]["c"] - 2610) < 1e-6)
    check("還原後序列連續",
          all(abs(b[i]["c"]/b[i-1]["c"]-1) <= GAP_LIMIT for i in range(1, len(b))))

    b2 = mk([220.5, 194.0, 193.0])                   # 長榮除息 −12%
    adj2, _ = backadjust(b2)
    check("除息 −12% 有還原", len(adj2) == 1 and abs(b2[0]["c"] - 194.0) < 1e-6)

    # ⚠ 新行為：向上跳空不還原（7769 2025-04 +26.8% 是真行情）
    b3 = mk([100.0, 127.0, 128.0])
    adj3, warn3 = backadjust(b3)
    check("向上跳空不還原", adj3 == [])
    check("向上跳空有發出警告", any("向上跳空" in w for w in warn3))
    check("向上跳空資料未被竄改", b3[0]["c"] == 100.0)

    # ⚠ 新行為：相隔太多天不還原（7769 2025-04-02→04-07 跨清明連假）
    b4 = mk([100.0, 67.0], step=10)
    adj4, warn4 = backadjust(b4)
    check("相隔過久不還原", adj4 == [])
    check("相隔過久有發出警告", any("缺漏" in w for w in warn4))
    check("相隔過久資料未被竄改", b4[0]["c"] == 100.0)

    # 相鄰交易日跨週末（週五→週一，3 天）仍應還原
    b5 = [{"d":"2026-01-09","o":100,"h":100,"l":100,"c":100.0,"v":1},
          {"d":"2026-01-12","o":87,"h":87,"l":87,"c":87.0,"v":1}]
    adj5, _ = backadjust(b5)
    check("跨週末（3天）仍視為相鄰、有還原", len(adj5) == 1)

    print("漲跌停不得被誤判：")
    b6 = mk([100.0, 110.0, 121.0])
    check("連續漲停不還原也不警告（未超過11%）", backadjust(b6) == ([], []))
    b7 = mk([100.0, 90.0, 81.0])
    check("連續跌停不還原", backadjust(b7)[0] == [])

    print("多次公司行為：")
    # 400 →200(分割) →198(跌1%) →99(分割)；還原後 100/100/99/99
    b8 = mk([400.0, 200.0, 198.0, 99.0])
    adj8, _ = backadjust(b8)
    check("兩次分割都被抓到", len(adj8) == 2)
    check("兩次分割累乘正確",
          all(abs(b8[i]["c"] - e) < 1e-6
              for i, e in enumerate((100.0, 100.0, 99.0, 99.0))))
    b9 = mk([800.0, 400.0, 200.0, 100.0, 50.0])
    _, warn9 = backadjust(b9)
    check("還原超過2次會標為可疑", any("異常偏多" in w for w in warn9))
    # 大幅還原要提醒對公告（緯穎 −66.5% 實例）
    b10 = mk([7800.0, 2610.0, 2600.0])
    adj10, warn10 = backadjust(b10)
    check("大幅還原仍會執行", len(adj10) == 1)
    check("大幅還原會提醒對公告", any("公司行為公告" in w for w in warn10))
    # 一般除息 −12% 不該觸發這個提醒
    _, warn11 = backadjust(mk([220.5, 194.0]))
    check("一般除息不觸發大幅提醒", not any("公司行為公告" in w for w in warn11))

    print("\n✅ 全部通過" if not fails else f"\n❌ {len(fails)} 項失敗：{fails}")
    sys.exit(1 if fails else 0)


def main() -> None:
    ap = argparse.ArgumentParser()
    if "--selftest" in sys.argv:
        selftest()
    ap.add_argument("--years", type=float, default=2.0, help="往回抓幾年（預設 2）")
    ap.add_argument("--out", default="backtest/prices_history.csv")
    ap.add_argument("--codes", help="只抓這些代號，逗號分隔；不給就用觀察池＋對照組")
    ap.add_argument("--no-control", action="store_true", help="不要對照組")
    ap.add_argument("--resume", action="store_true", help="略過 CSV 裡已有的代號")
    ap.add_argument("--batch", type=int, default=25, help="每批幾檔（預設 25）")
    args = ap.parse_args()

    bs = load_scanner()
    out = REPO / args.out

    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
        names = {}
    else:
        codes = sorted(bs.THEMES)
        names = dict(bs.THEMES)
        if not args.no_control:
            # 對照組必須「完全沒出現在任何 ETF 報告，也不在 THEMES」，否則對照無效。
            try:
                warn_etf: list[str] = []
                flows = bs.load_etf_flows(REPO / "reports", warn_etf)
                in_report = {c for a in flows for c in flows[a]}
            except Exception as exc:                  # noqa: BLE001
                print(f"⚠ 讀不到 ETF 報告（{type(exc).__name__}），"
                      f"無法驗證對照組是否被汙染，請自行確認")
                in_report = set()
            tainted = {c: n for c, n in CONTROL.items()
                       if c in in_report or c in bs.THEMES}
            if tainted:
                print("⚠ 對照組有 %d 檔已被汙染（出現在 ETF 報告或 THEMES），已自動剔除："
                      % len(tainted))
                for c, n in sorted(tainted.items()):
                    why = "在 THEMES" if c in bs.THEMES else "出現在 ETF 報告"
                    print(f"    {c} {n} — {why}")
                print("  請到 tools/fetch_history.py 的 CONTROL 把它們換掉。\n")
            ctrl = [c for c in sorted(CONTROL) if c not in tainted]
            codes += ctrl
            names.update(CONTROL)
            print(f"對照組：{len(ctrl)} 檔（原 {len(CONTROL)} 檔）")

    done, existing = set(), []
    if args.resume and out.exists():
        for r in csv.DictReader(out.open(encoding="utf-8")):
            done.add(r["code"]); existing.append(r)
        codes = [c for c in codes if c not in done]
        print(f"續抓模式：已有 {len(done)} 檔，待抓 {len(codes)} 檔")

    if not codes:
        print("沒有要抓的代號。"); return

    end = date.today()
    lookback = int(args.years * 365) + 40      # 多給一點暖身
    print(f"目標 {len(codes)} 檔，{end - timedelta(days=lookback)} ~ {end}\n")

    def grab(chunk):
        """抓一批，回傳 {code: bars}。整批空手就重試，再不行逐檔抓。

        ⚠️ yfinance 的第一次多檔請求很常整批靜默回空（冷啟動／限流）。
        2026-10-21 實跑就是這樣：sorted(THEMES) 的前 25 檔整批掉了，
        台積電、鴻海、聯電全被誤報成「已下市或代號有誤」。
        """
        for attempt in (1, 2):
            try:
                res = bs.load_prices(chunk, end, lookback_days=lookback)
            except SystemExit:
                raise
            except Exception as exc:                  # noqa: BLE001
                print(f"    第 {attempt} 次失敗：{type(exc).__name__} {exc}")
                res = {}
            if res:
                return res
            if attempt == 1 and len(chunk) > 1:
                print(f"    整批回空，5 秒後重試 …", flush=True)
                time.sleep(5)
        if len(chunk) == 1:
            return {}
        print(f"    重試仍整批回空，改逐檔抓 {len(chunk)} 檔 …", flush=True)
        out = {}
        for c in chunk:
            try:
                out.update(bs.load_prices([c], end, lookback_days=lookback))
            except Exception:                         # noqa: BLE001
                pass
            time.sleep(0.4)
        return out

    got, missing, reports, warnings = {}, [], [], []
    for i in range(0, len(codes), args.batch):
        chunk = codes[i:i + args.batch]
        print(f"[{i//args.batch + 1}/{(len(codes)-1)//args.batch + 1}] "
              f"抓 {len(chunk)} 檔 …", flush=True)
        res = grab(chunk)
        for c in chunk:
            bars = res.get(c)
            if not bars:
                missing.append(c); continue
            bars.sort(key=lambda x: x["d"])
            bad_idx, bad_notes = sane(bars)
            if bad_idx:
                reports.append(f"  {c} {names.get(c,'')}：剔除 {len(bad_idx)} 筆壞資料"
                               f"（{bad_notes[0]}）")
                bars = [b for k, b in enumerate(bars) if k not in set(bad_idx)]
            if len(bars) < MIN_BARS:
                missing.append(c); continue
            adj, warn = backadjust(bars)
            for n in adj:
                reports.append(f"  {c} {names.get(c,'')} 還原 {n}")
            for n in warn:
                warnings.append(f"  {c} {names.get(c,'')} ⚠ {n}")
            got[c] = bars
        time.sleep(1.0)

    out.parent.mkdir(parents=True, exist_ok=True)
    rows = list(existing)
    for c, bars in got.items():
        for b in bars:
            rows.append({"code": c, "date": b["d"],
                         "open": f"{b['o']:.4f}".rstrip("0").rstrip("."),
                         "high": f"{b['h']:.4f}".rstrip("0").rstrip("."),
                         "low":  f"{b['l']:.4f}".rstrip("0").rstrip("."),
                         "close": f"{b['c']:.4f}".rstrip("0").rstrip("."),
                         "volume": f"{b['v']:.0f}"})
    rows.sort(key=lambda r: (r["code"], r["date"]))
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["code","date","open","high","low","close","volume"])
        w.writeheader(); w.writerows(rows)

    allcodes = {r["code"] for r in rows}
    print(f"\n寫出 {out}：{len(rows)} 列、{len(allcodes)} 檔")
    if reports:
        print("\n資料修正（已自動處理）：")
        for r in reports: print(r)
    if warnings:
        print("\n⚠ 需要人工確認（未自動處理，資料維持原樣）：")
        for r in warnings: print(r)
    if missing:
        print(f"\n抓不到或資料不足 {len(missing)} 檔：")
        print("  " + " ".join(f"{c}{('(' + names[c] + ')') if c in names else ''}"
                              for c in sorted(set(missing))))
        print("  已重試並逐檔補抓過。上櫃股 load_prices 會自動試 .TWO；")
        print("  到這裡仍抓不到的，才可能是已下市、代號有誤，或 yfinance 沒有該檔。")
        print("  若整段連號都缺（例如排序後某一批全掉），那是限流 —— 隔幾分鐘用 --resume 再跑一次。")
    print("\n下一步：把這個檔名填進 backtest/ 的腳本（或改名成 prices_all.csv）再重跑回測。")


if __name__ == "__main__":
    main()
