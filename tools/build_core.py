#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_core.py — 產生「核心觀察名單」：全市場近 N 日平均成交金額前 M 名。

為什麼需要這個（見 backtest/RESULTS_20261019.md 第七、十、十一輪）：
    原本的觀察池是 ETF 報告出現過的個股。實測問題有二：
      1. 覆蓋率只有 43%，一半的起漲訊號落在池外；
      2. 半導體只涵蓋 29 檔，ETF 買賣超排行每天只列前幾名，尾巴進不來。
    核心名單用「成交金額排名」這種規則產生，不是人工挑的，所以沒有選樣偏誤，
    而且只用當下可得的資料，是 point-in-time 的。

    最終觀察池 = ETF 池 ∪ 核心名單（見 breakout_scan.build_universe）。

用法（要在你的 Mac 上跑，雲端沙箱連不到證交所）：
    python3 tools/build_core.py                 # 近 5 個交易日、前 150 名
    python3 tools/build_core.py --top 200 --days 10
    python3 tools/build_core.py --selftest      # 純解析邏輯自測，不連網

輸出：data/core_universe.json
    {"as_of": "2026-10-21", "days": 5, "top": 150,
     "codes":     {"2330": {"name": "台積電", "turnover": 1.2e8,
                            "industry": "半導體業"}, ...},   # 觀察池用（前 N 名）
     "directory": {"2330": {"name": "台積電",
                            "industry": "半導體業"}, ...}}   # 查表用（全市場上市）

⚠️ point-in-time 的界線
    這份名單是用「執行當下」的成交金額算的，往後每天掃描用它沒有問題。
    但拿它回測過去就是前視偏誤 —— 回測要逐月重算當時的排名，不能用今天這份。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "data" / "core_universe.json"
UA = {"User-Agent": "Mozilla/5.0 (build_core)"}

TWSE = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
# 產業別代碼 01~38 加管理股票 80。不寫死「代碼→產業名」對照表：
# 證交所的回應標題就是「每日收盤行情(半導體業)」，名稱直接從標題取，
# 代碼表哪天增刪我們也不會標錯。
INDUSTRY_TYPES = [f"{i:02d}" for i in range(1, 39)] + ["80"]
TITLE_RE = re.compile(r"每日收盤行情\s*[（(]\s*(.+?)\s*[）)]")
TPEX = "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc"


def fetch_json(url: str, params: dict, timeout: int = 25):
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{q}", headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def pick_rows(js) -> list[list[str]]:
    """
    從 TWSE MI_INDEX 的回應挑出「每日收盤行情（全部）」那張表。

    ⚠️ 這個回應有好幾張表（漲跌證券數、大盤統計、各類指數…），
    欄位名稱與表數會隨日期變動，所以用「欄位裡同時有證券代號和成交金額」
    來認表，不要靠固定索引 —— 之前 ETF 報告的解析器就是靠索引才一直壞掉。
    """
    if not isinstance(js, dict):
        return []
    tables = js.get("tables")
    if not tables:
        if js.get("fields") and js.get("data"):
            tables = [{"fields": js["fields"], "data": js["data"]}]
        else:
            return []
    for t in tables:
        f = [str(x) for x in (t.get("fields") or [])]
        if any("證券代號" in x for x in f) and any("成交金額" in x for x in f):
            i_code = next(i for i, x in enumerate(f) if "證券代號" in x)
            i_name = next((i for i, x in enumerate(f) if "證券名稱" in x), i_code + 1)
            i_val = next(i for i, x in enumerate(f) if "成交金額" in x)
            out = []
            for row in (t.get("data") or []):
                if len(row) <= max(i_code, i_name, i_val):
                    continue
                out.append([str(row[i_code]).strip(),
                            str(row[i_name]).strip(),
                            str(row[i_val]).strip()])
            return out
    return []


def pick_industry_name(js) -> str | None:
    """從 MI_INDEX 回應的 title 取產業名稱，例如「…每日收盤行情(半導體業)」→「半導體業」。"""
    if not isinstance(js, dict):
        return None
    cands = [js.get("title")]
    for t in (js.get("tables") or []):
        if isinstance(t, dict):
            cands.append(t.get("title"))
    for c in cands:
        if not c:
            continue
        m = TITLE_RE.search(str(c))
        if m and m.group(1):
            return m.group(1)
    return None


def fetch_industries(d: date, verbose=True) -> dict[str, str]:
    """
    逐一問各產業別的收盤行情，建 {證券代號: 產業名稱}。

    為什麼不用 openapi 的 t187ap03_L：
        那份的「產業別」欄位是代碼（"24"），不是名稱，還要另外一張對照表；
        這裡直接用 MI_INDEX 分產業查，產業名稱就寫在回應標題裡，
        而且順便確認這檔股票當天真的有在交易。
    """
    out: dict[str, str] = {}
    for t in INDUSTRY_TYPES:
        try:
            js = fetch_json(TWSE, {"date": d.strftime("%Y%m%d"),
                                   "type": t, "response": "json"})
            name = pick_industry_name(js)
            rows = pick_rows(js)
        except Exception as exc:                           # noqa: BLE001
            if verbose: print(f"  產業 {t} 取得失敗：{type(exc).__name__}")
            time.sleep(1.2)
            continue
        if name and rows:
            n = 0
            for code, _nm, _val in rows:
                if is_common_stock(code):
                    out[code] = name; n += 1
            if verbose: print(f"  產業 {t} {name}：{n} 檔")
        time.sleep(1.2)
    return out


def is_common_stock(code: str) -> bool:
    """只要普通股：4 位數字 1000~9999。排除 ETF(00xx)、權證、存託憑證、特別股。"""
    return len(code) == 4 and code.isdigit() and 1000 <= int(code) <= 9999


def to_float(s: str) -> float:
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def collect(days: int, verbose=True) -> dict[str, dict]:
    """往回找 days 個有資料的交易日，累加各檔成交金額。"""
    acc: dict[str, dict] = {}
    last_ok: date | None = None
    got, d, tries = 0, date.today(), 0
    while got < days and tries < days * 4:
        tries += 1
        if d.weekday() < 5:
            try:
                js = fetch_json(TWSE, {"date": d.strftime("%Y%m%d"),
                                       "type": "ALLBUT0999", "response": "json"})
                rows = pick_rows(js)
            except Exception as exc:                       # noqa: BLE001
                if verbose: print(f"  {d} 取得失敗：{type(exc).__name__}")
                rows = []
            if rows:
                got += 1
                if last_ok is None:
                    last_ok = d          # 最新的那個交易日，拿去查產業別
                for code, name, val in rows:
                    if not is_common_stock(code):
                        continue
                    a = acc.setdefault(code, {"name": name, "sum": 0.0, "n": 0})
                    a["sum"] += to_float(val); a["n"] += 1
                if verbose: print(f"  {d} 取得 {len(rows)} 檔（第 {got}/{days} 個交易日）")
            time.sleep(1.2)                                # 對證交所客氣一點
        d -= timedelta(days=1)
    return acc, last_ok


def selftest() -> None:
    fails = []
    def check(n, c):
        print(f"  {'PASS' if c else 'FAIL'}  {n}")
        if not c: fails.append(n)

    print("表格辨識：")
    js = {"tables": [
        {"fields": ["type", "漲跌證券數"], "data": [["上漲", "500"]]},
        {"fields": ["證券代號", "證券名稱", "成交股數", "成交金額", "收盤價"],
         "data": [["2330", "台積電", "35,209,944", "83,673,350,698", "2370.00"],
                  ["0050", "元大台灣50", "1,000", "5,000,000", "200.00"],
                  ["2317", "鴻海", "1,000", "1,000,000", "180.00"]]},
    ]}
    rows = pick_rows(js)
    check("認出正確的表（不是第一張）", len(rows) == 3)
    check("欄位取值正確", rows[0] == ["2330", "台積電", "83,673,350,698"])
    check("欄位順序變動仍能認", len(pick_rows({"tables": [
        {"fields": ["證券名稱", "成交金額", "證券代號"],
         "data": [["台積電", "1", "2330"]]}]})) == 1)
    check("沒有符合的表就回空", pick_rows({"tables": [
        {"fields": ["a", "b"], "data": [["1", "2"]]}]}) == [])
    check("舊格式（沒有 tables）也能解析", len(pick_rows(
        {"fields": ["證券代號", "證券名稱", "成交金額"],
         "data": [["2330", "台積電", "1"]]})) == 1)

    print("證券種類過濾：")
    check("普通股 2330 保留", is_common_stock("2330"))
    check("ETF 0050 排除", not is_common_stock("0050"))
    check("ETF 00878 排除", not is_common_stock("00878"))
    check("權證（6位英數）排除", not is_common_stock("03041P"))
    check("存託憑證 9103 保留（確實是普通股代號區間）", is_common_stock("9103"))

    print("產業名稱解析：")
    check("從標題取產業名", pick_industry_name(
        {"title": "115年10月21日 每日收盤行情(半導體業)"}) == "半導體業")
    check("全形括號也要認", pick_industry_name(
        {"title": "115年10月21日 每日收盤行情（電子零組件業）"}) == "電子零組件業")
    check("標題在 tables 裡也找得到", pick_industry_name(
        {"tables": [{"title": "(元,股)"},
                    {"title": "115年10月21日 每日收盤行情(光電業)"}]}) == "光電業")
    check("沒有可用標題回 None", pick_industry_name({"title": "(元,股)"}) is None)
    check("全部表不合規回 None", pick_industry_name({"tables": []}) is None)
    check("不是 dict 回 None", pick_industry_name(None) is None)

    print("數值解析：")
    check("千分位逗號", to_float("83,673,350,698") == 83673350698.0)
    check("壞值回 0 不報錯", to_float("--") == 0.0 and to_float(None) == 0.0)

    print("\n✅ 全部通過" if not fails else f"\n❌ {len(fails)} 項失敗：{fails}")
    sys.exit(1 if fails else 0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=5, help="用近幾個交易日的平均（預設5）")
    ap.add_argument("--top", type=int, default=150, help="取前幾名（預設150）")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--no-industry", dest="industry", action="store_false",
                    help="略過產業別（省約 50 秒，但觀察池會多很多未分類）")
    args = ap.parse_args()

    print(f"抓全市場成交金額（近 {args.days} 個交易日）…")
    acc, last_ok = collect(args.days)
    if not acc:
        sys.exit("一檔都沒抓到。證交所端點可能改了，或這台機器連不出去。")

    ranked = sorted(acc.items(), key=lambda kv: -(kv[1]["sum"] / max(kv[1]["n"], 1)))
    top = ranked[:args.top]

    ind: dict[str, str] = {}
    if args.industry and last_ok:
        print(f"\n抓產業別（{last_ok}，{len(INDUSTRY_TYPES)} 個產業）…")
        ind = fetch_industries(last_ok)
        miss = [c for c, _ in top if c not in ind]
        print(f"產業別對到 {len(ind)} 檔；前 {len(top)} 名裡有 {len(miss)} 檔沒對到"
              + (f"：{', '.join(miss[:10])}" if miss else ""))

    # directory：全市場上市普通股的「代號 → 股名＋產業」。
    # 為什麼不只存前 N 名（2026-10-21）：
    #   觀察池 = ETF 池 ∪ 核心名單，ETF 池裡有一堆不在前 N 名的個股，
    #   它們沒有產業別就只能掛「未分類」，而掃描輸出的「名稱」欄一直是空的。
    #   產業別本來就一次抓回全市場 1000 多檔，只存 150 筆是浪費。
    #   多存這一份，掃描器就能替任何上市個股查到股名與產業，不必多發任何請求。
    directory = {c: {"name": v["name"], "industry": ind.get(c)}
                 for c, v in sorted(acc.items())}

    out = {"as_of": date.today().isoformat(), "days": args.days, "top": args.top,
           "source": "TWSE MI_INDEX ALLBUT0999" + ("＋分產業收盤行情" if ind else ""),
           "codes": {c: {"name": v["name"],
                         "turnover": round(v["sum"] / max(v["n"], 1), 0),
                         "industry": ind.get(c)}
                     for c, v in top},
           "directory": directory}
    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n全市場普通股 {len(acc)} 檔 → 取前 {len(top)} 名，"
          f"另存 directory {len(directory)} 檔（股名＋產業），寫入 {p}")
    print("前 10 名：")
    for c, v in top[:10]:
        print(f"  {c} {v['name']:<10} 日均成交 {v['sum']/max(v['n'],1)/1e8:>8.1f} 億")
    print(f"第 {len(top)} 名門檻：日均成交 "
          f"{top[-1][1]['sum']/max(top[-1][1]['n'],1)/1e8:.2f} 億")
    print("\n⚠️ 只含上市（TWSE）。上櫃要另外處理，目前 ETF 池會補一部分。")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    main()
