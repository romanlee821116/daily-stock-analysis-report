#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
breakout_scan.py — 起漲點追蹤 每日掃描
=====================================

對應 Notion SOP「起漲點追蹤 SOP（自動排程用）」。
門檻全部集中在 PARAMS，**改這裡就要同步改 SOP 第 2 節**，反之亦然。

執行：
    python3 tools/breakout_scan.py                 # 掃描今天
    python3 tools/breakout_scan.py --date 20261016 # 指定資料日
    python3 tools/breakout_scan.py --dry-run       # 不寫檔，只印摘要
    python3 tools/breakout_scan.py --selftest      # 用合成資料驗證狀態機與評分

輸出：
    data/scan/{run_date}.json   當日掃描結果（Cowork 排程讀這個）
    data/scan/state.json        觀察池狀態（不要刪，刪了要重新暖機）

⚠️ 與 SOP 第 1 節的一處刻意差異（2026/10/19）
----------------------------------------------
SOP 原本寫 ETF 流向走 etfedge。本腳本改為**解析本機 reports/*.html**
（ETF tracker 排程每天 06:00 產出的同源報告）。理由：
  1. 同一份資料，少一個對外爬蟲與其失敗模式；
  2. 解析器已對照原始 HTML 逐筆驗證過；
  3. 報告模板換過三代，解析器以標題文字錨定、已容忍。
若要改回 etfedge，替換 load_etf_flows() 即可，其餘不受影響。

資料來源
--------
  價量      yfinance（需要網路）
  法人      TWSE T86 / TPEx 盤後（需要網路）
  ETF 流向  本機 reports/*.html（不需網路）
"""

from __future__ import annotations

import argparse
import json
import sys as _sys
import os
import re
import sys
import time
import html as _html
from bisect import bisect_left
from datetime import date, datetime, timedelta
from pathlib import Path

# ────────────────────────────── 門檻（＝SOP 第 2 節） ──────────────────────────────

PARAMS = {
    # 起漲
    "launch_breakout_lookback": 20,     # 收盤 > 前 N 日最高
    "launch_vol_ratio_min":     1.5,    # 量比 ≥（或見 launch_strong_gain）
    "launch_strong_gain":       7.0,    # 當日漲幅 % ≥ 此值時豁免量比門檻
    "launch_day_gain_min":      3.0,    # 當日漲幅 % ≥
    "launch_upper_shadow_max":  0.60,   # 上影線 ≤ 當日振幅 ×
    "launch_ma20_bias_max":     25.0,   # 20MA 乖離 % ≤

    # 已發動
    "extended_ma20_bias":       10.0,   # 20MA 乖離 % >
    "extended_gain5":           12.0,   # 5 日漲幅 % >

    # 蓄勢
    "coil_range_max":           15.0,   # 20 日區間振幅 % ≤
    "coil_ma_spread_max":       3.0,    # 5/10/20MA 最大差距 % ≤
    "coil_vol_shrink_max":      0.7,    # 5 日均量 ÷ 前 120 日均量 ≤
    "coil_base_vol_window":     120,
    "coil_base_vol_min_days":   60,
    "coil_base_vol_exclude":    5,

    # 潛伏
    "latent_etf_lookback":      5,      # 近 N 個 as_of 的 ETF 合計
    "latent_etf_buyers_min":    2,      # 且淨買方 ≥ N 檔
    "latent_trust_streak_min":  3,      # 或 投信連買 ≥ N 日
    "latent_gain5_max":         3.0,    # 且 5 日漲幅 % <

    # 共用
    "ma_long":                  60,     # 收盤 > 60MA
    "range_lookback":           20,

    # 狀態維持
    "watch_expire_days":        10,     # 潛伏/蓄勢 連續 N 日不符合才退出
    "launch_hold_days":         3,      # 起漲後 N 日內守住突破價就維持

    # 結果判定（第 6 節）
    "hit_return10":             5.0,    # 10 日報酬 % ≥
    "hit_maxgain10":           10.0,    # 或 10 日內最高漲幅 % ≥
    "fail_return10":           -3.0,    # 10 日報酬 % ≤
    "backfill_done_days":       20,     # N 日後 回填完成

    # 排序分（2026-10-20 重寫，見 backtest/RESULTS_20261019.md 第五輪）
    # ⚠️ 舊版配分（籌碼40＋型態35＋觸發25）回測四分位非單調：
    #    Q1 -1.48% / Q2 +3.96% / Q3 +3.61% / Q4 +2.90%，沒有鑑別力。
    # 新版只用三個實測有效的變數，門檻內四分位勝率 35%→47%→53%→71%。
    # 錨點是照「切兩半」的方向手訂的整數，不是擬合出來的係數。
    "score_shape_w":           40,   # 突破前 20 日振幅：越緊越好
    "score_range_full":        10.0, #   振幅 <=10% 給滿分
    "score_range_zero":        40.0, #   振幅 >=40% 給 0
    "score_vol_w":             30,   # 量比：越小越好（漲停鎖死量縮是強勢）
    "score_vol_full":           0.5, #   量比 <=0.5 給滿分
    "score_vol_zero":           2.5, #   量比 >=2.5 給 0
    "score_gain_w":            30,   # 當日漲幅：越大越好
    "score_gain_zero":          3.0, #   漲幅 <=3% 給 0
    "score_gain_full":         10.0, #   漲幅 >=10% 給滿分
    # 籌碼：第一輪回測各門檻 t 都 ≈ 0，沒有可測得的選股能力 → 預設不計分。
    # 要放回去就把權重調大（分數仍會被壓回 0~100）。
    "score_chip_w":             0,
    # 觀察池（2026-10-21 改成 point-in-time，見 build_universe）
    "universe_lookback":       20,   # 用最近 N 個報告日出現過的個股當觀察池
    "universe_min":            30,   # 低於此數視為暖機不足，改用 THEMES 保底
    # 核心名單（2026-10-21 加入，見 tools/build_core.py 與 build_universe）
    "core_max_age_days":       14,   # 核心名單超過這麼多天沒更新就發警告（仍會用）
    "score_report_min":        50,   # 建議只看分數 >= 此值的起漲訊號
    #   回測：>=0 超額+2.25%/t=1.33、>=40 +5.16%/t=2.43、>=50 +7.15%/t=2.59（勝率66.7%）
}

STATES = ("潛伏", "蓄勢", "起漲", "已發動", "失效")
WATCHING = ("潛伏", "蓄勢")

# 觀察池：應與 ETF SOP 第 3 節的主題分類一致。
# code -> 主題（Notion「主題」select 的 18 類之一）
THEMES = {
    "2330": "晶圓代工",      "2303": "晶圓代工",      "6770": "晶圓代工",
    "2454": "IC設計/ASIC",   "3443": "IC設計/ASIC",   "3661": "IC設計/ASIC",
    "5274": "IC設計/ASIC",   "3529": "IC設計/ASIC",   "6526": "IC設計/ASIC",
    "2379": "IC設計/ASIC",   "3034": "IC設計/ASIC",   "8299": "IC設計/ASIC",
    "2308": "散熱與電源",    "6412": "散熱與電源",    "3017": "散熱與電源",
    "3324": "散熱與電源",    "3653": "散熱與電源",    "8996": "散熱與電源",
    "2376": "AI伺服器ODM",   "3231": "AI伺服器ODM",   "6669": "AI伺服器ODM",
    "2382": "AI伺服器ODM",   "2317": "AI伺服器ODM",   "2377": "AI伺服器ODM",
    "3706": "AI伺服器ODM",   "8210": "AI伺服器ODM",
    "2383": "PCB/CCL/載板",  "3037": "PCB/CCL/載板",  "2368": "PCB/CCL/載板",
    "8046": "PCB/CCL/載板",  "3189": "PCB/CCL/載板",  "6274": "PCB/CCL/載板",
    "4958": "PCB/CCL/載板",  "2313": "PCB/CCL/載板",  "3044": "PCB/CCL/載板",
    "6213": "PCB/CCL/載板",  "8358": "PCB/CCL/載板",  "1815": "CCL與上游材料",
    "1802": "CCL與上游材料", "5340": "CCL與上游材料", "5475": "CCL與上游材料",
    "2449": "封測與測試介面", "3711": "封測與測試介面", "6257": "封測與測試介面",
    "6515": "封測與測試介面", "6510": "封測與測試介面", "7769": "封測與測試介面",
    "6239": "封測與測試介面", "3264": "封測與測試介面", "8150": "封測與測試介面",
    "2408": "記憶體",        "2344": "記憶體",        "2337": "記憶體",
    "3260": "記憶體",        "4967": "記憶體",        "5289": "記憶體",
    "2327": "被動元件",      "2478": "被動元件",      "2428": "被動元件",
    "2472": "被動元件",      "3026": "被動元件",
    "6488": "半導體設備材料", "3131": "半導體設備材料", "6187": "半導體設備材料",
    "2467": "半導體設備材料", "1560": "半導體設備材料", "6196": "半導體設備材料",
    "2360": "半導體設備材料", "6640": "半導體設備材料", "6139": "半導體設備材料",
    "3081": "網通/光通訊",   "3491": "網通/光通訊",   "4979": "網通/光通訊",
    "2345": "網通/光通訊",   "6442": "網通/光通訊",   "3363": "網通/光通訊",
    "2455": "網通/光通訊",   "3234": "網通/光通訊",
    "3665": "連接器/機構件",  "2059": "連接器/機構件",  "3533": "連接器/機構件",
    "6805": "連接器/機構件",  "2476": "連接器/機構件",
    "3105": "功率半導體",    "2481": "功率半導體",    "5425": "功率半導體",
    "3707": "功率半導體",    "3016": "功率半導體",    "4991": "功率半導體",
    "1519": "工控與重電",    "1503": "工控與重電",    "1513": "工控與重電",
    "1504": "工控與重電",    "7750": "工控與重電",    "2395": "工控與重電",
    "3008": "面板光學LED",   "3406": "面板光學LED",   "2409": "面板光學LED",
    "2301": "消費電子零組件", "2357": "消費電子零組件", "6121": "消費電子零組件",
    "3702": "電子通路",      "3036": "電子通路",      "2347": "電子通路",
    "1303": "傳產與其他",    "1301": "傳產與其他",    "1326": "傳產與其他",
    "6505": "傳產與其他",    "1216": "傳產與其他",    "1101": "傳產與其他",
    "1605": "傳產與其他",    "2027": "傳產與其他",    "2603": "傳產與其他",
    "2615": "傳產與其他",    "2610": "傳產與其他",
    "2412": "電信",          "4904": "電信",          "3045": "電信",
    "2881": "金融",          "2882": "金融",          "2891": "金融",
    "2885": "金融",          "2884": "金融",          "2886": "金融",
}

# ────────────────────────────── 路徑 ──────────────────────────────

REPO = Path(__file__).resolve().parent.parent
SCAN_DIR = REPO / "data" / "scan"
STATE_PATH = SCAN_DIR / "state.json"
REPORTS_DIR = REPO / "reports"
CORE_PATH = REPO / "data" / "core_universe.json"

TPE = "Asia/Taipei"


def log(msg: str) -> None:
    print(f"[breakout_scan] {msg}", file=sys.stderr, flush=True)


def pct(a: float, b: float) -> float:
    """(a/b - 1) * 100，b 為 0 或 None 時回 0。"""
    if not b:
        return 0.0
    return (a / b - 1.0) * 100.0


def rnd(x, n=2):
    return None if x is None else round(float(x), n)


# ══════════════════════════════ 資料來源 ══════════════════════════════

def load_prices(codes, end: date, lookback_days: int = 400, suffix_cache=None):
    """
    回傳 {code: [{d, o, h, l, c, v}, ...]}，日期由舊到新，只到 end（含）。
    用 yfinance 批次抓；抓不到的代號不會出現在結果裡（呼叫端要容忍）。
    """
    try:
        import yfinance as yf
    except ImportError:
        raise SystemExit(
            "缺少 yfinance。請在這台 Mac 執行：python3 -m pip install --user yfinance"
        )

    start = end - timedelta(days=lookback_days)
    out, missing = {}, []
    got_suffix = {}

    # 上市 .TW 與上櫃 .TWO 都試；先一次抓 .TW，失敗的再試 .TWO
    def _grab(suffix, want):
        tickers = [f"{c}{suffix}" for c in want]
        if not tickers:
            return {}
        df = yf.download(
            tickers=" ".join(tickers),
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True,
        )
        if df is None or len(df) == 0:
            return {}

        # ⚠️ 取欄位的方式（2026-10-21 修，踩過的坑）
        # 舊版寫 `df[t] if len(tickers) > 1 else df`，假設「單一 ticker 回平欄位」。
        # yfinance 1.2.0 起，單一 ticker 加 group_by="ticker" 一樣回 MultiIndex，
        # 於是 sub 仍是兩層欄位，下一行 dropna(subset=["Close"]) 直接丟 KeyError，
        # 而且那個例外沒被接住 → 整批（不只那一檔）全部陪葬。
        # 實際災情：sorted(THEMES) 第 1 批 25 檔（含 2330、2317、2303）整批消失，
        # 逐檔補抓因為每次都是單一 ticker，又踩同一個雷，一檔都救不回來。
        # → 改成只看欄位是不是 MultiIndex，不看 ticker 數量。
        multi = hasattr(df.columns, "nlevels") and df.columns.nlevels > 1

        res = {}
        for c in want:
            t = f"{c}{suffix}"
            try:
                if multi:
                    if t not in df.columns.get_level_values(0):
                        continue
                    sub = df[t]
                else:
                    sub = df
                if "Close" not in sub.columns:
                    continue
                sub = sub.dropna(subset=["Close"])
                if sub.empty:
                    continue
                bars = []
                for ts, row in sub.iterrows():
                    try:
                        bars.append({
                            "d": ts.date().isoformat(),
                            "o": float(row["Open"]), "h": float(row["High"]),
                            "l": float(row["Low"]),  "c": float(row["Close"]),
                            "v": float(row["Volume"]),
                        })
                    except (TypeError, ValueError, KeyError):
                        continue        # 單一壞列不該毀掉整檔
                if bars:
                    res[c] = bars
                    got_suffix[c] = suffix
            except Exception:           # noqa: BLE001
                # 單一代號出問題就跳過它，絕對不要讓它帶走整批。
                continue
        return res

    # ⚠️ 上櫃股的 .TW 一定 404（2026-10-21 實測每天固定 20 檔刷版面）。
    # suffix_cache 記住每一檔上次成功的後綴，下次直接用對的那個：
    # 省掉 20 次無謂請求，也讓 log 裡的 possibly delisted 真的代表有問題。
    # 快取只是加速，不是真相來源 —— 用快取沒抓到的，照樣走原本的兩輪流程補。
    cache = suffix_cache if isinstance(suffix_cache, dict) else {}
    first = {".TW": [], ".TWO": []}
    for c in codes:
        first.setdefault(cache.get(c, ".TW"), []).append(c)

    for sfx in (".TW", ".TWO"):
        if not first.get(sfx):
            continue
        try:
            out.update(_grab(sfx, first[sfx]))
        except Exception:               # noqa: BLE001
            pass

    # 還沒抓到的，再用另一個後綴試一次（新進榜的個股第一次會走到這裡）
    missing = [c for c in codes if c not in out]
    if missing:
        retry = {".TW": [], ".TWO": []}
        for c in missing:
            retry[".TWO" if cache.get(c, ".TW") == ".TW" else ".TW"].append(c)
        for sfx in (".TW", ".TWO"):
            if not retry[sfx]:
                continue
            try:
                out.update(_grab(sfx, retry[sfx]))
            except Exception:           # noqa: BLE001
                pass

    # 回寫快取（只記成功的；失敗的不要寫，免得把暫時性失敗固化成錯的後綴）
    if isinstance(suffix_cache, dict):
        for c, sfx in got_suffix.items():
            suffix_cache[c] = sfx
    return out


def _twse_json(url, params, warnings, label):
    import urllib.parse
    import urllib.request
    try:
        q = urllib.parse.urlencode(params)
        req = urllib.request.Request(
            f"{url}?{q}",
            headers={"User-Agent": "Mozilla/5.0 (breakout_scan)"},
        )
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"{label} 取得失敗：{type(exc).__name__} {exc}")
        return None


def load_institutional(days_back: int, end: date, warnings):
    """
    回傳 {code: {"trust": [(date, net_shares), ...], "foreign": [...]}}，由舊到新。
    來源：TWSE T86（上市）。上櫃取不到時只記 warning，不中斷。
    """
    base = "https://www.twse.com.tw/rwd/zh/fund/T86"
    res = {}
    fetched = 0
    d = end
    tries = 0
    while fetched < days_back and tries < days_back * 2:
        tries += 1
        if d.weekday() < 5:
            js = _twse_json(base,
                            {"date": d.strftime("%Y%m%d"),
                             "selectType": "ALL", "response": "json"},
                            warnings, f"T86 {d.isoformat()}")
            if js and js.get("stat") == "OK" and js.get("data"):
                fetched += 1
                for row in js["data"]:
                    code = row[0].strip()
                    try:
                        foreign = float(row[4].replace(",", ""))
                        trust = float(row[10].replace(",", ""))
                    except (IndexError, ValueError):
                        continue
                    slot = res.setdefault(code, {"trust": [], "foreign": []})
                    slot["trust"].append((d.isoformat(), trust))
                    slot["foreign"].append((d.isoformat(), foreign))
            time.sleep(1.2)   # 對證交所客氣一點
        d -= timedelta(days=1)

    if fetched < days_back:
        warnings.append(f"法人資料僅取得 {fetched} 天（目標 {days_back} 天），投信連買可能低估")
    for slot in res.values():
        slot["trust"].sort()
        slot["foreign"].sort()
    return res


def _strip(h: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", _html.unescape(h))).strip()


def load_etf_flows(reports_dir: Path, warnings):
    """
    解析本機 reports/*.html（ETF tracker 的產出）→
      {as_of: {code: {net, buyers, sellers, name, theme, buyer_list, seller_list}}}

    ⚠️ 合併規則（2026-10-19 修正，踩過的坑）
    同一天同一檔可能同時出現在「個股排行」與「多檔共識訊號」兩張表。
    舊版「共識節優先」會低估買方檔數：共識表只列出 >=3 檔的那一側，少數側的
    ETF 根本不會出現；排行表的「買/賣檔數」欄才是完整的 N/M。
    實例：2026-08-20 2454 共識表只給賣方 7 檔，排行表寫明「1 / 7」。
    → 檔數一律取兩表較大者；ETF 名單取共識節（只有它有名單）。

    以 <h2> 標題文字錨定，容忍三代以上模板（章節編號會飄）。
    """
    def sections(s):
        hs = list(re.finditer(r"<h2[^>]*>(.*?)</h2>", s, re.S))
        for i, m in enumerate(hs):
            end = hs[i + 1].start() if i + 1 < len(hs) else len(s)
            yield _strip(m.group(1)), s[m.end():end]

    def colmap(hdr):
        m = {}
        for i, c in enumerate(hdr):
            t = _strip(c)
            if   re.search(r"代號", t):           m["code"] = i
            elif re.search(r"名稱", t):           m["name"] = i
            elif re.search(r"個股", t):           m["codename"] = i
            elif re.search(r"淨額|淨買賣超", t):   m["net"] = i
            elif re.search(r"方向", t):           m["dir"] = i
            elif re.search(r"買方", t):           m["buyers"] = i
            elif re.search(r"賣方", t):           m["sellers"] = i
            elif re.search(r"參與", t):           m["parts"] = i
            elif re.search(r"檔數", t):           m["cnt"] = i
            elif re.search(r"主題|族群", t):       m["theme"] = i
        return m

    def num(x):
        m = re.search(r"-?\d+(?:\.\d+)?", _strip(x).replace(",", "").replace("+", ""))
        return float(m.group(0)) if m else None

    flows = {}
    files = sorted(p for p in reports_dir.glob("*.html")
                   if re.fullmatch(r"\d{8}\.html", p.name))
    if not files:
        warnings.append(f"找不到任何 ETF 報告（{reports_dir}），潛伏訊號的籌碼條件將全部不成立")
        return flows

    for fp in files:
        d = fp.stem
        as_of = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        s = fp.read_text(encoding="utf-8", errors="replace")
        s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
        s = re.sub(r"<style.*?</style>", "", s, flags=re.S)
        day = flows.setdefault(as_of, {})
        for head, body in sections(s):
            if not ("多檔共識" in head or re.search(r"個股(資金流|淨買)", head)):
                continue
            for tbl in re.findall(r"<table.*?</table>", body, re.S):
                rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, re.S)
                if not rows:
                    continue
                hdr = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", rows[0], re.S)
                cm = colmap(hdr)
                if "net" not in cm or not ("code" in cm or "codename" in cm):
                    continue
                for tr in rows[1:]:
                    tds = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)
                    if len(tds) < len(hdr) - 1:
                        continue
                    g = lambda k: (tds[cm[k]] if k in cm and cm[k] < len(tds) else "")
                    if "code" in cm:
                        mc = re.match(r"(\d{4})", _strip(g("code")))
                    else:
                        mc = re.match(r"(\d{4})", _strip(g("codename")))
                    if not mc:
                        continue
                    code = mc.group(1)
                    net = num(g("net"))
                    if net is None:
                        continue
                    buyers = re.findall(r"\b00\d{3}A\b", g("buyers"))
                    sellers = re.findall(r"\b00\d{3}A\b", g("sellers"))
                    if not buyers and not sellers and "parts" in cm:
                        p = re.findall(r"\b00\d{3}A\b", g("parts"))
                        if "賣" in _strip(g("dir")) or net < 0:
                            sellers = p
                        else:
                            buyers = p
                    nb, ns = len(buyers), len(sellers)
                    if not (nb or ns):
                        mc2 = re.search(r"(\d+)\s*/\s*(\d+)",
                                        " ".join(_strip(t) for t in tds))
                        if mc2:
                            nb, ns = int(mc2.group(1)), int(mc2.group(2))
                    name = _strip(g("name")) if "name" in cm else ""
                    if not name and "codename" in cm:
                        name = re.sub(r"^\d{4}\s*", "", _strip(g("codename")))
                    theme = _strip(tds[cm["theme"]]) if "theme" in cm else ""
                    if theme and re.fullmatch(r"[-\d.,%+ ]+", theme):
                        theme = ""

                    prev = day.get(code)
                    if prev is None:
                        day[code] = {
                            "net": net, "buyers": nb, "sellers": ns,
                            "name": name, "theme": theme,
                            "buyer_list": buyers, "seller_list": sellers,
                        }
                    else:
                        prev["buyers"] = max(prev["buyers"], nb)
                        prev["sellers"] = max(prev["sellers"], ns)
                        if abs(net) > abs(prev["net"]):
                            prev["net"] = net
                        prev["name"] = prev["name"] or name
                        prev["theme"] = prev["theme"] or theme
                        if buyers and not prev["buyer_list"]:
                            prev["buyer_list"] = buyers
                        if sellers and not prev["seller_list"]:
                            prev["seller_list"] = sellers
    return flows


# ══════════════════════════════ 指標 ══════════════════════════════

def ma(vals, n):
    return sum(vals[-n:]) / n if len(vals) >= n else None


def indicators(bars, flows_recent, trust_streak, foreign_streak):
    """由價量算出判定與評分需要的全部指標。bars 由舊到新，最後一根是資料日。"""
    P = PARAMS
    closes = [b["c"] for b in bars]
    vols = [b["v"] for b in bars]
    last = bars[-1]
    n = len(bars)
    if n < 2:
        return None

    prev_close = closes[-2]
    rng_n = P["range_lookback"]

    # 前 N 日（不含今天）最高/最低
    hist = bars[-(rng_n + 1):-1]
    if len(hist) < 5:
        return None
    hi_n = max(b["h"] for b in hist)
    lo_n = min(b["l"] for b in hist)

    ma5, ma10, ma20 = ma(closes, 5), ma(closes, 10), ma(closes, 20)
    ma60 = ma(closes, P["ma_long"])
    vma20 = ma(vols, 20)
    vma5 = ma(vols, 5)

    # 蓄勢用的基準量：前 coil_base_vol_window 日、排除最近 coil_base_vol_exclude 日
    base_slice = vols[-(P["coil_base_vol_window"] + P["coil_base_vol_exclude"]):
                      -P["coil_base_vol_exclude"]] if n > P["coil_base_vol_exclude"] else []
    vbase = (sum(base_slice) / len(base_slice)
             if len(base_slice) >= P["coil_base_vol_min_days"] else None)

    day_range = last["h"] - last["l"]
    upper_shadow = last["h"] - max(last["c"], last["o"])

    ind = {
        "close": last["c"], "open": last["o"], "high": last["h"], "low": last["l"],
        "prev_close": prev_close,
        "day_gain": pct(last["c"], prev_close),
        "hi_n": hi_n, "lo_n": lo_n,
        "vol": last["v"],
        "vol_ratio": (last["v"] / vma20) if vma20 else None,
        "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
        "ma20_bias": pct(last["c"], ma20) if ma20 else None,
        "gain5": pct(last["c"], closes[-6]) if n >= 6 else None,
        "range20": pct(hi_n, lo_n) if lo_n else None,
        "ma_spread": (pct(max(ma5, ma10, ma20), min(ma5, ma10, ma20))
                      if (ma5 and ma10 and ma20) else None),
        "vol_shrink": (vma5 / vbase) if (vma5 and vbase) else None,
        "upper_shadow_ratio": (upper_shadow / day_range) if day_range > 0 else 0.0,
        "close_pos": ((last["c"] - last["l"]) / day_range) if day_range > 0 else 1.0,
        "etf_net": flows_recent["net"],
        "etf_buyers": flows_recent["buyers"],
        "trust_streak": trust_streak,
        "foreign_streak": foreign_streak,
    }
    return ind


def etf_recent(flows, code, as_of_list, lookback):
    """近 N 個 as_of 的 ETF 合計淨買與淨買方檔數。"""
    net, buyers = 0.0, 0
    for a in as_of_list[-lookback:]:
        rec = flows.get(a, {}).get(code)
        if rec:
            net += rec["net"]
            if rec["net"] > 0:
                buyers += rec["buyers"]
    return {"net": round(net, 2), "buyers": buyers}


def streak(series, positive=True):
    """由最新往回數連續同向天數。series = [(date, value), ...] 由舊到新。"""
    k = 0
    for _, v in reversed(series):
        if (v > 0) if positive else (v < 0):
            k += 1
        else:
            break
    return k


# ══════════════════════════════ 狀態機（＝SOP 第 2 節） ══════════════════════════════

def classify(ind, prev):
    """
    回傳 (state, trigger_desc)。判定順序由上到下，先符合者為準。
    prev 是 state.json 裡這檔的前次紀錄（可能是 None）。
    """
    P = PARAMS
    prev_state = (prev or {}).get("state")
    prev_stop = (prev or {}).get("stop")

    # 1 失效
    if prev_state in ("潛伏", "蓄勢", "起漲") and prev_stop and ind["close"] < prev_stop:
        return "失效", f"收盤 {ind['close']:.2f} 跌破停損參考 {prev_stop:.2f}"

    # 2 起漲
    checks = [
        ind["close"] > ind["hi_n"],
        # ⚠️ 量能條件（2026-10-19 校準，踩過的坑）
        # 原本只看「量比 >= 1.5」，結果 7 個真實起漲日有 5 個被擋掉。
        # 原因：漲停鎖死當天沒人賣，量反而縮——量縮是強勢特徵，不是弱勢。
        # 實例：2026-09-18 3443 創意 +10.00% 量比 1.43、8996 高力 +10.00% 量比 0.59，
        #       兩檔後 10 日最大漲幅 +21.8% / +16.4%。
        # → 改成「量比達標 或 漲幅達漲停級」。完全拿掉量比會讓 10 日超額翻負，別拿掉。
        (( ind["vol_ratio"] is not None
           and ind["vol_ratio"] >= P["launch_vol_ratio_min"])
         or ind["day_gain"] >= P["launch_strong_gain"]),
        ind["day_gain"] >= P["launch_day_gain_min"],
        ind["upper_shadow_ratio"] <= P["launch_upper_shadow_max"],
        ind["ma20_bias"] is not None and ind["ma20_bias"] <= P["launch_ma20_bias_max"],
    ]
    if all(checks):
        return "起漲", (
            f"收盤 {ind['close']:.2f} > 前20日高 {ind['hi_n']:.2f}；"
            f"量比 {ind['vol_ratio']:.2f}；漲幅 {ind['day_gain']:.2f}%；"
            f"上影線 {ind['upper_shadow_ratio'] * 100:.0f}%；"
            f"20MA乖離 {ind['ma20_bias']:.2f}%"
        )

    # 3 已發動
    if ((ind["ma20_bias"] is not None and ind["ma20_bias"] > P["extended_ma20_bias"])
            or (ind["gain5"] is not None and ind["gain5"] > P["extended_gain5"])):
        return "已發動", (
            f"20MA乖離 {ind['ma20_bias']:.2f}%／5日漲幅 "
            f"{(ind['gain5'] if ind['gain5'] is not None else float('nan')):.2f}%"
        )

    above_ma60 = ind["ma60"] is not None and ind["close"] > ind["ma60"]

    # 4 蓄勢
    if (ind["range20"] is not None and ind["range20"] <= P["coil_range_max"]
            and ind["ma_spread"] is not None and ind["ma_spread"] <= P["coil_ma_spread_max"]
            and ind["vol_shrink"] is not None and ind["vol_shrink"] <= P["coil_vol_shrink_max"]
            and above_ma60):
        return "蓄勢", (
            f"20日振幅 {ind['range20']:.2f}%；均線糾結 {ind['ma_spread']:.2f}%；"
            f"量縮 {ind['vol_shrink']:.2f}；收盤站上60MA"
        )

    # 5 潛伏
    chips = ((ind["etf_net"] > 0 and ind["etf_buyers"] >= P["latent_etf_buyers_min"])
             or ind["trust_streak"] >= P["latent_trust_streak_min"])
    if (chips and ind["gain5"] is not None and ind["gain5"] < P["latent_gain5_max"]
            and above_ma60):
        return "潛伏", (
            f"ETF近{P['latent_etf_lookback']}日淨買 {ind['etf_net']:+.2f}億／"
            f"{ind['etf_buyers']}檔；投信連買 {ind['trust_streak']} 日；"
            f"5日漲幅 {ind['gain5']:.2f}%"
        )

    return None, ""


def apply_maintenance(code, raw_state, trigger, ind, prev, data_date):
    """
    套用 SOP 第 2 節的「狀態維持」規則，回傳 (state, trigger, new_record)。
    new_record 是要寫回 state.json 的那一筆。
    """
    P = PARAMS
    prev_state = (prev or {}).get("state")
    state, trig = raw_state, trigger

    if state is None:
        # 本日不符合任何條件 —— 觀察中的要看是否已逾期
        if prev_state in WATCHING:
            miss = (prev or {}).get("miss", 0) + 1
            if miss >= P["watch_expire_days"]:
                state, trig = "失效", f"觀察逾 {P['watch_expire_days']} 日未發動"
            else:
                state = prev_state
                trig = (prev or {}).get("trigger", "")
                return state, trig, {
                    "state": state, "trigger": trig, "miss": miss,
                    "breakout": ind["hi_n"], "stop": ind["lo_n"],
                    "since": (prev or {}).get("since", data_date),
                }
        elif prev_state == "起漲":
            held = (prev or {}).get("held", 0) + 1
            bk = (prev or {}).get("breakout")
            if held <= P["launch_hold_days"] and bk and ind["close"] >= bk:
                return "起漲", (prev or {}).get("trigger", ""), {
                    "state": "起漲", "trigger": (prev or {}).get("trigger", ""),
                    "held": held, "breakout": bk, "stop": (prev or {}).get("stop"),
                    "since": (prev or {}).get("since", data_date),
                }
            state, trig = None, ""
        else:
            state, trig = None, ""

    if state is None:
        return None, "", None

    # 蓄勢不會降級回潛伏
    if state == "潛伏" and prev_state == "蓄勢":
        state, trig = "蓄勢", (prev or {}).get("trigger", trig)

    if state == "失效":
        return state, trig, None  # 移出觀察池

    if state == "起漲":
        rec = {
            "state": "起漲", "trigger": trig, "held": 0,
            "breakout": ind["hi_n"],      # 起漲前 20 日最高，固定
            "stop": ind["low"],           # 起漲當日最低，固定
            "since": data_date,
        }
    elif state in WATCHING:
        rec = {
            "state": state, "trigger": trig, "miss": 0,
            "breakout": ind["hi_n"], "stop": ind["lo_n"],   # 每天更新
            "since": (prev or {}).get("since", data_date)
                     if prev_state == state else data_date,
        }
    else:  # 已發動
        rec = {
            "state": state, "trigger": trig,
            "breakout": (prev or {}).get("breakout"),
            "stop": (prev or {}).get("stop"),
            "since": (prev or {}).get("since", data_date),
        }
    return state, trig, rec


def transition_type(prev_state, state):
    """SOP 第 3 節：只記轉換，不記每日狀態。回傳 None 代表不記錄。"""
    if prev_state == state:
        return None
    if state == "起漲":
        return "潛伏/蓄勢→起漲" if prev_state in WATCHING else "無→起漲"
    if state == "已發動":
        if prev_state in WATCHING:
            return "觀察→已發動"
        if prev_state == "起漲":
            return None          # 自然演進，不記
        return "無→已發動"
    if state in WATCHING:
        if prev_state is None or prev_state == "失效":
            return "進入觀察"
        if prev_state == "潛伏" and state == "蓄勢":
            return "進入觀察"
        return None
    if state == "失效":
        return "退出" if prev_state in ("潛伏", "蓄勢", "起漲") else None
    return None


def score(ind, state):
    """
    0～100 排序分，只用來排序，不參與狀態判定。

    ⚠️ 只有「起漲」的分數經過回測驗證（31 檔 × 2026-05~10、68 個訊號）：
       門檻內四分位的 10 日同日超額報酬 -4.44% / -0.27% / +8.05% / +5.64%，
       勝率 35.3% / 47.1% / 52.9% / 70.6%。
       觀察狀態（潛伏/蓄勢）當日多半沒有漲幅，分數會落在振幅＋量能兩項上，
       那是合理的排序，但沒有回測背書——不要拿它當進場依據。
    """
    P = PARAMS

    def ramp(x, zero, full):
        """x 從 zero 線性到 full，輸出 0~1；zero 可大於 full（反向）。"""
        if x is None:
            return 0.0
        if full == zero:
            return 0.0
        return max(0.0, min(1.0, (x - zero) / (full - zero)))

    shape = P["score_shape_w"] * ramp(
        ind["range20"] if ind["range20"] is not None else P["score_range_zero"],
        P["score_range_zero"], P["score_range_full"])
    vol = P["score_vol_w"] * ramp(
        ind["vol_ratio"] if ind["vol_ratio"] is not None else P["score_vol_zero"],
        P["score_vol_zero"], P["score_vol_full"])
    gain = P["score_gain_w"] * ramp(
        ind["day_gain"], P["score_gain_zero"], P["score_gain_full"])

    s = shape + vol + gain

    # 籌碼：預設權重 0（回測無 edge）。權重 >0 時才計入。
    if P["score_chip_w"] > 0:
        chip = 0.0
        if ind["etf_net"] > 0:
            chip += min(ind["etf_buyers"] / 4.0, 1.0) * 0.6
        chip += min(ind["trust_streak"] / 5.0, 1.0) * 0.4
        s += P["score_chip_w"] * chip

    return round(max(0.0, min(100.0, s)), 1)


# ══════════════════════════════ 回填（＝SOP 第 6 節） ══════════════════════════════

def bars_after(bars, d: str):
    """回傳資料日 d 之後（不含 d）的 bar 列表。"""
    dates = [b["d"] for b in bars]
    i = bisect_left(dates, d)
    if i < len(dates) and dates[i] == d:
        i += 1
    return bars[i:]


def judge(ret10, maxgain10, broke_stop):
    P = PARAMS
    if ret10 is None:
        return None
    if broke_stop or ret10 <= P["fail_return10"]:
        return "失敗"
    if ret10 >= P["hit_return10"] or (maxgain10 or 0) >= P["hit_maxgain10"]:
        return "命中"
    return "持平"


def build_backfill(records, prices, warnings):
    """對 state.json 裡尚未完成的紀錄算前瞻報酬；回傳 (backfill_rows, still_open)。"""
    P = PARAMS
    rows, still_open = [], []
    for r in records:
        if r.get("done"):
            continue
        bars = prices.get(r["code"])
        if not bars:
            still_open.append(r)
            warnings.append(f"回填找不到價格：{r['紀錄']}")
            continue
        fwd = bars_after(bars, r["date"])
        base = r["close"]
        upd = {"紀錄": r["紀錄"]}
        changed = False

        for k, n in (("5日後報酬%", 5), ("10日後報酬%", 10), ("20日後報酬%", 20)):
            if len(fwd) >= n and r.get(k) is None:
                upd[k] = rnd(pct(fwd[n - 1]["c"], base))
                r[k] = upd[k]
                changed = True

        if len(fwd) >= 10 and r.get("結果") is None:
            win = fwd[:10]
            maxgain = rnd(pct(max(b["h"] for b in win), base))
            broke = bool(r.get("stop")) and any(b["c"] < r["stop"] for b in win)
            res = judge(r.get("10日後報酬%"), maxgain, broke)
            upd["期間最大漲幅%"] = maxgain
            upd["結果"] = res
            r["期間最大漲幅%"], r["結果"] = maxgain, res
            changed = True

        if len(fwd) >= P["backfill_done_days"]:
            upd["回填完成"] = "__YES__"
            r["done"] = True
            changed = True

        if changed and len(upd) > 1:
            rows.append(upd)
        if not r.get("done"):
            still_open.append(r)
    return rows, still_open


# ══════════════════════════════ 主流程 ══════════════════════════════

def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log("state.json 壞了，當成首次執行（觀察池會重新暖機）")
    return {"stocks": {}, "records": [], "last_data_date": None}


def load_core_universe(run_date: date, warnings):
    """
    讀 tools/build_core.py 產出的核心名單（全市場日均成交金額前 N 名）。

    為什麼需要（見 backtest/RESULTS_20261019.md 第十一輪）：
        純 ETF 觀察池只涵蓋 43~48% 的起漲訊號，半導體只有 29 檔 ——
        ETF 買賣超排行每天只列前幾名，尾巴進不來。
        核心名單用「成交金額排名」這種規則產生，不是人工挑的，
        所以沒有選樣偏誤，而且只用執行當下可得的資料。

    回傳 (core, directory)：
        core      = {code: 產業別}，前 N 名，決定誰進觀察池
        directory = {code: {"name", "industry"}}，全市場上市，純查表用
    檔案不存在就回 ({}, {}) 並發警告（不中斷，ETF 池還在）。
    """
    if not CORE_PATH.exists():
        warnings.append(
            f"核心名單 {CORE_PATH.name} 不存在，本次只用 ETF 池"
            "（覆蓋率實測只有 43~48%）；請在本機跑 python3 tools/build_core.py")
        return {}, {}
    try:
        js = json.loads(CORE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        warnings.append(f"核心名單讀取失敗（{e}），本次只用 ETF 池")
        return {}, {}

    codes = js.get("codes") or {}
    if not isinstance(codes, dict) or not codes:
        warnings.append("核心名單是空的，本次只用 ETF 池")
        return {}, {}

    as_of = js.get("as_of")
    if as_of:
        try:
            age = (run_date - date.fromisoformat(as_of)).days
        except ValueError:
            age = None
            warnings.append(f"核心名單的 as_of 格式看不懂（{as_of}），當成未知新舊")
        if age is not None and age > PARAMS["core_max_age_days"]:
            warnings.append(
                f"核心名單是 {as_of} 產的、已經 {age} 天沒更新"
                f"（上限 {PARAMS['core_max_age_days']} 天），成交值排名可能已經換人；"
                "本次照用，但請重跑 tools/build_core.py")
    else:
        warnings.append("核心名單沒有 as_of 欄位，無法判斷新舊")

    out = {c: (v.get("industry") if isinstance(v, dict) else None)
           for c, v in codes.items()}
    if not any(out.values()):
        warnings.append(
            "核心名單沒有產業別（舊版格式或當時用了 --no-industry），"
            "這些個股在報告裡會是未分類；重跑 tools/build_core.py 即可補上")

    # directory 是 2026-10-21 才加的，舊檔沒有 → 回空字典，呼叫端自己 fallback
    raw = js.get("directory")
    directory = {c: v for c, v in raw.items()
                 if isinstance(v, dict)} if isinstance(raw, dict) else {}
    if not directory:
        warnings.append(
            "核心名單沒有 directory（舊版格式），個股名稱與非前 150 名的產業別"
            "會查不到；重跑 tools/build_core.py 即可補上")
    return out, directory


def build_universe(flows, run_date: date, state, warnings, core=None):
    """
    逐日 point-in-time 觀察池：只用 as_of < 執行日 的 ETF 報告。回傳 {code: 主題}。

    為什麼要這樣做（見 backtest/RESULTS_20261019.md 第七、十輪）：
        原本的 THEMES 是回頭從「整段期間」的 ETF 報告挑出來的固定名單，
        等於選樣本時已經知道未來誰會活躍 —— 前視偏誤。
        改成「當天只能看 D−1 以前的報告」就沒有這個問題，而且這正是
        實際運作的樣子：ETF tracker 盤後產報告，隔天早上掃描器才跑。

    已在追蹤的個股（潛伏/蓄勢/起漲/已發動）一律保留在池內，
    否則手上還在觀察的標的會因為某天沒上榜就整個消失。
    """
    P = PARAMS
    usable = [a for a in sorted(flows) if a < run_date.isoformat()]
    recent = usable[-P["universe_lookback"]:]
    uni = {}
    for a in recent:
        for code, r in flows[a].items():
            uni[code] = r.get("theme") or THEMES.get(code)

    etf_n = len(uni)

    # 核心名單：規則產生的全市場成交值前 N 名，補 ETF 池漏掉的那一半。
    # ETF 報告有給主題就以報告為準（比較新），核心名單只負責「把人放進來」。
    # 主題優先序：ETF 報告（最新、最具體）> THEMES（人工標）> 核心名單的產業別。
    # 產業別只是「半導體業」這種粗分類，沒有主題貼切，所以排最後，
    # 但總比整片未分類好 —— 日報是按主題分組的。
    core = core or {}
    for code, industry in core.items():
        uni.setdefault(code, THEMES.get(code) or industry)

    held = set(state.get("stocks", {}))
    for code in held:
        uni.setdefault(code, THEMES.get(code))

    if len(uni) < P["universe_min"]:
        warnings.append(
            f"ETF 報告僅涵蓋 {len(usable)} 天、觀察池只有 {len(uni)} 檔"
            f"（低於 {P['universe_min']}），暖機不足，本次改用 THEMES 保底名單")
        for code, th in THEMES.items():
            uni.setdefault(code, th)
    else:
        # ⚠️ recent 可能是空的：核心名單自己就能撐過 universe_min，
        #    這時 ETF 報告一份都還沒有，recent[0] 會 IndexError。
        span = (f"近 {len(recent)} 個報告日 {recent[0]}~{recent[-1]}"
                if recent else "尚無可用報告")
        warnings.append(
            f"觀察池共 {len(uni)} 檔＝ETF 池 {etf_n} 檔（{span}）"
            f"∪ 核心名單 {len(core)} 檔，"
            f"其中 {len(held & set(uni))} 檔是既有追蹤標的")
    return uni


def run(run_date: date, dry_run=False):
    warnings = []
    state = load_state()
    first_run = not state["stocks"]
    if first_run:
        warnings.append("首次執行：觀察池尚未暖機，潛伏/蓄勢訊號不完整")

    log("解析 ETF 流向…")
    flows = load_etf_flows(REPORTS_DIR, warnings)
    as_of_list = sorted(flows)
    if as_of_list and len(as_of_list) < 10:
        warnings.append(f"ETF 流向僅累積 {len(as_of_list)} 天，暖機期、潛伏訊號不完整")

    core, directory = load_core_universe(run_date, warnings)
    universe = build_universe(flows, run_date, state, warnings, core)

    # 個股名稱：ETF 報告最新最準（含上櫃），查不到再問 directory（只有上市）。
    # 兩邊都沒有就留空字串 —— 絕不自己編一個名字。
    names = {}
    for a in sorted(flows):
        for c, r in flows[a].items():
            if r.get("name"):
                names[c] = r["name"]
    for c, v in directory.items():
        names.setdefault(c, v.get("name") or "")

    # 主題補洞：觀察池裡沒主題的，用 directory 的產業別頂著
    for c, th in list(universe.items()):
        if not th:
            universe[c] = (directory.get(c) or {}).get("industry")
    still_unknown = [c for c, th in universe.items() if not th]
    if still_unknown:
        warnings.append(
            f"{len(still_unknown)} 檔查不到主題或產業別（多半是上櫃股，"
            f"build_core 只含上市）：{'、'.join(sorted(still_unknown)[:8])}")
    codes = sorted(universe)
    log(f"抓價量 {len(codes)} 檔…")
    suffix_cache = state.get("suffix") if isinstance(state.get("suffix"), dict) else {}
    prices = load_prices(codes, run_date, suffix_cache=suffix_cache)
    state["suffix"] = {c: sfx for c, sfx in suffix_cache.items() if c in universe}
    if not prices:
        raise SystemExit("價量全部抓不到，可能是網路或 yfinance 問題；本日不產出")

    # 資料日 = 所有個股最新 bar 的眾數（避免個別停牌股拉錯日期）
    from collections import Counter
    last_dates = Counter(b[-1]["d"] for b in prices.values() if b)
    data_date = last_dates.most_common(1)[0][0]
    if data_date != run_date.isoformat():
        warnings.append(f"資料日 {data_date} 不等於執行日 {run_date.isoformat()}（假日或資料未更新）")
    if state.get("last_data_date") == data_date:
        warnings.append(f"data_date 與上一次相同（{data_date}），本次不應產生新轉換")

    missing = [c for c in codes if c not in prices]
    if missing:
        warnings.append(f"價量抓不到 {len(missing)} 檔：{','.join(missing[:12])}"
                        + ("…" if len(missing) > 12 else ""))

    log("抓法人…")
    inst = load_institutional(PARAMS["latent_trust_streak_min"] + 7, run_date, warnings)

    notion_rows, launched, watchlist, extended = [], [], [], []
    new_stocks = {}

    for code in codes:
        bars = prices.get(code)
        if not bars or bars[-1]["d"] != data_date:
            prev = state["stocks"].get(code)
            if prev:
                new_stocks[code] = prev      # 停牌/資料缺：狀態原樣保留
            continue

        slot = inst.get(code, {"trust": [], "foreign": []})
        ind = indicators(
            bars,
            etf_recent(flows, code, as_of_list, PARAMS["latent_etf_lookback"]),
            streak(slot["trust"]), streak(slot["foreign"]),
        )
        if ind is None:
            continue

        prev = state["stocks"].get(code)
        prev_state = (prev or {}).get("state")
        raw, trig = classify(ind, prev)
        st, trig, rec = apply_maintenance(code, raw, trig, ind, prev, data_date)
        if rec:
            new_stocks[code] = rec

        if st is None:
            continue

        sc = score(ind, st)
        theme = universe.get(code) or THEMES.get(code)
        row_base = {
            "代號": code, "名稱": names.get(code, ""), "主題": theme,
            "狀態": st, "前一狀態": prev_state or "無",
            "收盤": rnd(ind["close"]),
            "突破價": rnd((rec or {}).get("breakout") or ind["hi_n"]),
            "停損參考": rnd((rec or {}).get("stop") or ind["lo_n"]),
            "量比": rnd(ind["vol_ratio"]),
            "20MA乖離%": rnd(ind["ma20_bias"]),
            "5日漲幅%": rnd(ind["gain5"]),
            "20日區間振幅%": rnd(ind["range20"]),
            "ETF參與檔數": ind["etf_buyers"],
            "ETF近5日淨買(億)": rnd(ind["etf_net"]),
            "外資連買天數": ind["foreign_streak"],
            "投信連買天數": ind["trust_streak"],
            "排序分": sc,
            # 高分訊號＝分數 >= score_report_min。回測（31檔×2026-05~10、68個起漲訊號）
            # 顯示 >=50 那組 10 日同日超額 +7.15%／勝率 66.7%／t=+2.59，
            # 全部訊號則是 +2.25%／51.5%／t=+1.33。只有「起漲」的分數經過驗證。
            "高分訊號": "是" if (st == "起漲" and sc >= PARAMS["score_report_min"]) else "否",
        }

        tt = transition_type(prev_state, st)
        if tt:
            title = f"{data_date} {code} {prev_state or '無'}→{st}"
            notion_rows.append({
                **row_base, "轉換類型": tt, "觸發條件": trig,
                "紀錄": title, "資料日": data_date,
                "結果": "待回填" if st in ("起漲", "已發動") else None,
                "回填完成": "__NO__",
            })
            if st in ("起漲", "已發動"):
                state["records"].append({
                    "紀錄": title, "code": code, "date": data_date,
                    "close": ind["close"], "stop": (rec or {}).get("stop"),
                    "done": False,
                })

        if st == "起漲":
            launched.append({**row_base, "觸發條件": trig,
                             "是否自觀察池": prev_state in WATCHING})
        elif st in WATCHING:
            watchlist.append({**row_base,
                              "距突破%": rnd(pct(row_base["突破價"], ind["close"]))})
        elif st == "已發動":
            extended.append({"代號": code, "名稱": names.get(code, ""), "主題": theme,
                             "20MA乖離%": rnd(ind["ma20_bias"]),
                             "5日漲幅%": rnd(ind["gain5"])})

    log("回填前瞻報酬…")
    backfill, still_open = build_backfill(state["records"], prices, warnings)

    watchlist.sort(key=lambda r: -r["排序分"])
    launched.sort(key=lambda r: -r["排序分"])
    extended.sort(key=lambda r: -(r["20MA乖離%"] or 0))

    out = {
        "run_date": run_date.isoformat(),
        "data_date": data_date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "params_version": "2026-10-19",
        "notion_rows": notion_rows,
        "backfill": backfill,
        "launched": launched,
        "watchlist": watchlist[:10],
        "watchlist_full": watchlist,
        "extended": extended[:5],
        "warnings": warnings,
        "counts": {
            "universe": len(codes), "priced": len(prices),
            "launched": len(launched), "watching": len(watchlist),
            "extended": len(extended), "new_records": len(notion_rows),
            "backfilled": len(backfill),
        },
    }

    if dry_run:
        print(json.dumps(out["counts"], ensure_ascii=False, indent=2))
        for w in warnings:
            print("WARN:", w)
        return out

    SCAN_DIR.mkdir(parents=True, exist_ok=True)
    (SCAN_DIR / f"{run_date.strftime('%Y%m%d')}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    state["stocks"] = new_stocks
    state["records"] = still_open + [r for r in state["records"] if r.get("done")][-500:]
    state["last_data_date"] = data_date
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    log(f"完成：{out['counts']}")
    return out


# ══════════════════════════════ 自我測試 ══════════════════════════════

def _synth(n=200, base=100.0, step=0.0, vol=1000.0):
    bars, c = [], base
    for i in range(n):
        c = c * (1 + step)
        d = (date(2026, 1, 1) + timedelta(days=i)).isoformat()
        bars.append({"d": d, "o": c * 0.995, "h": c * 1.005,
                     "l": c * 0.99, "c": c, "v": vol})
    return bars


def selftest():
    P, fails = PARAMS, []

    def check(name, cond):
        print(f"  {'PASS' if cond else 'FAIL'}  {name}")
        if not cond:
            fails.append(name)

    flat = {"net": 0.0, "buyers": 0}
    print("狀態機：")

    # 起漲：量爆 + 大漲 + 突破
    bars = _synth()
    last = dict(bars[-1])
    prev_c = bars[-2]["c"]
    last.update(c=prev_c * 1.06, h=prev_c * 1.065, l=prev_c * 1.0,
                o=prev_c * 1.005, v=1000.0 * 3)
    bars[-1] = last
    ind = indicators(bars, flat, 0, 0)
    st, _ = classify(ind, None)
    check("爆量突破 → 起漲", st == "起漲")

    # 同形狀但量不足 → 不該是起漲
    bars2 = _synth()
    l2 = dict(bars2[-1]); pc = bars2[-2]["c"]
    l2.update(c=pc * 1.06, h=pc * 1.065, l=pc * 1.0, o=pc * 1.005, v=1000.0)
    bars2[-1] = l2
    st2, _ = classify(indicators(bars2, flat, 0, 0), None)
    check("量不足 → 不是起漲", st2 != "起漲")

    # 漲停鎖死：漲幅 >= launch_strong_gain 但量縮 → 仍應是起漲
    # （回歸測試：2026-09-18 3443/8996 都是 +10% 漲停、量比 1.43/0.59，舊條件全被擋）
    bars2b = _synth()
    l2b = dict(bars2b[-1]); pcb = bars2b[-2]["c"]
    l2b.update(c=pcb * 1.10, h=pcb * 1.10, l=pcb * 1.02, o=pcb * 1.02, v=600.0)
    bars2b[-1] = l2b
    indb = indicators(bars2b, flat, 0, 0)
    check("漲停鎖死量縮 → 仍是起漲", classify(indb, None)[0] == "起漲")
    check("  （確認量比確實低於門檻）",
          indb["vol_ratio"] < P["launch_vol_ratio_min"])

    # 邊界：漲幅低於 strong_gain 且量不足 → 不得放行
    bars2c = _synth()
    l2c = dict(bars2c[-1]); pcc = bars2c[-2]["c"]
    g = (P["launch_strong_gain"] - 0.5) / 100
    l2c.update(c=pcc * (1 + g), h=pcc * (1 + g), l=pcc, o=pcc, v=600.0)
    bars2c[-1] = l2c
    check(f"  （邊界）漲幅 {P['launch_strong_gain']-0.5}% + 量縮 → 不是起漲",
          classify(indicators(bars2c, flat, 0, 0), None)[0] != "起漲")

    # 上影線與乖離的新上限：剛好在界內應放行
    bars2d = _synth()
    l2d = dict(bars2d[-1]); pcd = bars2d[-2]["c"]
    cl = pcd * 1.06
    rng = cl - pcd * 1.0
    l2d.update(o=pcd * 1.005, c=cl, l=pcd * 1.0,
               h=cl + rng * (P["launch_upper_shadow_max"] - 0.05), v=1000.0 * 3)
    bars2d[-1] = l2d
    check(f"上影線 {int((P['launch_upper_shadow_max']-0.05)*100)}% → 仍是起漲",
          classify(indicators(bars2d, flat, 0, 0), None)[0] == "起漲")

    # 失效優先於一切
    ind3 = indicators(bars, flat, 0, 0)
    st3, _ = classify(ind3, {"state": "起漲", "stop": ind3["close"] + 50})
    check("跌破停損 → 失效（優先序最高）", st3 == "失效")

    # 已發動：乖離大
    # 注意：step=0.01 時 20MA 乖離僅 ~9.7%、未過 10% 門檻，屬正確不觸發。
    # 這裡用 1.5%/日（乖離 ~14.8%）確保越過門檻。
    bars4 = _synth(step=0.015)
    ind4 = indicators(bars4, flat, 0, 0)
    st4, _ = classify(ind4, None)
    check("乖離 >10% → 已發動", st4 == "已發動")
    check("  （門檻附近）1%/日 乖離未過 10% → 不觸發",
          classify(indicators(_synth(step=0.01), flat, 0, 0), None)[0] != "已發動")

    # 潛伏：投信連買 + 5 日沒漲 + 站上 60MA
    bars5 = _synth(step=0.0005)
    st5, _ = classify(indicators(bars5, flat, 5, 0), None)
    check("投信連買5日+盤整 → 潛伏或蓄勢", st5 in ("潛伏", "蓄勢"))

    print("狀態維持：")
    ind6 = indicators(_synth(), flat, 0, 0)
    s6, _, r6 = apply_maintenance("x", None, "", ind6,
                                  {"state": "潛伏", "miss": 3, "stop": 0.0}, "2026-10-19")
    check("潛伏未達門檻但未逾期 → 維持潛伏", s6 == "潛伏" and r6["miss"] == 4)

    s7, _, _ = apply_maintenance("x", None, "", ind6,
                                 {"state": "潛伏", "miss": P["watch_expire_days"] - 1,
                                  "stop": 0.0}, "2026-10-19")
    check(f"觀察逾 {P['watch_expire_days']} 日 → 失效", s7 == "失效")

    s8, _, _ = apply_maintenance("x", "潛伏", "t", ind6,
                                 {"state": "蓄勢", "stop": 0.0}, "2026-10-19")
    check("蓄勢不降級回潛伏", s8 == "蓄勢")

    print("轉換類型：")
    check("潛伏→起漲", transition_type("潛伏", "起漲") == "潛伏/蓄勢→起漲")
    check("無→起漲", transition_type(None, "起漲") == "無→起漲")
    check("起漲→已發動 不記錄", transition_type("起漲", "已發動") is None)
    check("已發動→無 不記錄", transition_type("已發動", None) is None)
    check("無→潛伏＝進入觀察", transition_type(None, "潛伏") == "進入觀察")
    check("潛伏→蓄勢＝進入觀察", transition_type("潛伏", "蓄勢") == "進入觀察")
    check("起漲→失效＝退出", transition_type("起漲", "失效") == "退出")

    print("結果判定：")
    check("10日 +6% → 命中", judge(6.0, 7.0, False) == "命中")
    check("10日 +1% 但最高 +12% → 命中", judge(1.0, 12.0, False) == "命中")
    check("10日 -4% → 失敗", judge(-4.0, 1.0, False) == "失敗")
    check("跌破停損 → 失敗", judge(2.0, 3.0, True) == "失敗")
    check("其餘 → 持平", judge(1.0, 2.0, False) == "持平")

    print("排序分：")
    best = dict(ind, range20=5.0, vol_ratio=0.4, day_gain=11.0)
    worst = dict(ind, range20=50.0, vol_ratio=3.0, day_gain=3.0)
    check("滿分情境 = 100", score(best, "起漲") == 100.0)
    check("零分情境 = 0", score(worst, "起漲") == 0.0)
    check("分數恆在 0~100",
          all(0 <= score(dict(ind, range20=r, vol_ratio=v, day_gain=g), "起漲") <= 100
              for r in (0, 25, 99) for v in (0, 1.5, 9) for g in (-5, 5, 30)))

    # 三個分項各自單調（其他兩項固定）
    base = dict(ind, range20=25.0, vol_ratio=1.5, day_gain=6.0)
    check("振幅越小分數越高",
          score(dict(base, range20=15.0), "起漲") > score(dict(base, range20=35.0), "起漲"))
    check("量比越小分數越高（漲停量縮是強勢）",
          score(dict(base, vol_ratio=0.8), "起漲") > score(dict(base, vol_ratio=2.2), "起漲"))
    check("漲幅越大分數越高",
          score(dict(base, day_gain=9.0), "起漲") > score(dict(base, day_gain=4.0), "起漲"))

    # 籌碼預設不計分
    chips_hi = dict(base, etf_net=9.0, etf_buyers=8, trust_streak=9)
    check("籌碼預設權重 0（回測無 edge）",
          score(chips_hi, "起漲") == score(base, "起漲"))

    # 缺值不得讓分數爆掉
    check("指標缺值時給 0 分不報錯",
          score(dict(base, range20=None, vol_ratio=None), "起漲")
          == round(PARAMS["score_gain_w"] * (6.0 - 3.0) / 7.0, 1))

    print("觀察池（build_universe，point-in-time）：")
    _flows = {
        "2026-10-16": {"1111": {"theme": "A"}, "2222": {"theme": "B"}},
        "2026-10-19": {"2222": {"theme": "B"}, "3333": {"theme": "C"}},
        "2026-10-20": {"4444": {"theme": "D"}},   # 執行日當天，不該被看到
    }
    _P = PARAMS["universe_min"]
    PARAMS["universe_min"] = 1                    # 暫時關掉保底，才測得到純邏輯
    try:
        w = []
        u = build_universe(_flows, date(2026, 10, 20), {"stocks": {}}, w)
        check("只用 D−1 以前的報告", set(u) == {"1111", "2222", "3333"})
        check("當天的報告不得外洩（4444 不在池內）", "4444" not in u)
        check("主題標籤取自報告", u["3333"] == "C")

        # 既有追蹤標的要保留，即使近期沒上榜
        u2 = build_universe(_flows, date(2026, 10, 20),
                            {"stocks": {"9999": {"state": "潛伏"}}}, [])
        check("既有追蹤標的保留在池內", "9999" in u2)

        # lookback 只取最近 N 個報告日
        _lb = PARAMS["universe_lookback"]; PARAMS["universe_lookback"] = 1
        u3 = build_universe(_flows, date(2026, 10, 20), {"stocks": {}}, [])
        check("lookback=1 只取最近一個報告日", set(u3) == {"2222", "3333"})
        PARAMS["universe_lookback"] = _lb

        # 暖機不足要退回 THEMES 並發警告
        PARAMS["universe_min"] = 10_000
        w4 = []
        u4 = build_universe(_flows, date(2026, 10, 20), {"stocks": {}}, w4)
        check("暖機不足改用 THEMES 保底", len(u4) > len(THEMES) - 1)
        check("暖機不足有發警告", any("暖機不足" in x for x in w4))

        # --- 核心名單聯集（2026-10-21）---
        # 上面測保底時把 universe_min 拉到 10000，這裡要放回來，
        # 否則 THEMES 保底會灌進來、測不到聯集本身。
        PARAMS["universe_min"] = 1
        _core = {"5555": "半導體業", "2222": "電子零組件業", "7777": None}
        u5 = build_universe(_flows, date(2026, 10, 20), {"stocks": {}}, [], _core)
        check("核心名單併進觀察池",
              set(u5) == {"1111", "2222", "3333", "5555", "7777"})
        check("ETF 報告的主題優先於核心名單的產業別", u5["2222"] == "B")
        check("核心名單獨有的個股用產業別當主題", u5["5555"] == "半導體業")
        check("核心名單沒產業別的才留白", u5["7777"] is None)

        # 核心名單缺席時不得整個壞掉
        u6 = build_universe(_flows, date(2026, 10, 20), {"stocks": {}}, [], None)
        check("沒有核心名單時照常運作", set(u6) == {"1111", "2222", "3333"})

        # 一份 ETF 報告都沒有、只靠核心名單撐起來時，警告字串不能 IndexError
        PARAMS["universe_min"] = 2
        w7 = []
        u7 = build_universe({}, date(2026, 10, 20), {"stocks": {}}, w7,
                            {"5555": "x", "6666": "y"})
        check("沒有任何報告、只有核心名單也能建池", set(u7) == {"5555", "6666"})
        check("沒有報告時的警告不得炸掉", any("尚無可用報告" in x for x in w7))
    finally:
        PARAMS["universe_min"] = _P

    print("核心名單讀取（load_core_universe）：")
    import tempfile as _tf
    _real_core = globals()["CORE_PATH"]
    try:
        with _tf.TemporaryDirectory() as _d:
            _d = Path(_d)

            globals()["CORE_PATH"] = _d / "missing.json"
            w = []
            check("檔案不存在回空字典",
                  load_core_universe(date(2026, 10, 21), w) == ({}, {}))
            check("檔案不存在要發警告", any("不存在" in x for x in w))

            _bad = _d / "bad.json"
            _bad.write_text("{這不是 json", encoding="utf-8")
            globals()["CORE_PATH"] = _bad
            w = []
            check("壞掉的 json 回空字典、不丟例外",
                  load_core_universe(date(2026, 10, 21), w) == ({}, {}))
            check("壞掉的 json 要發警告", any("讀取失敗" in x for x in w))

            _ok = _d / "ok.json"
            _ok.write_text(json.dumps(
                {"as_of": "2026-10-21",
                 "codes": {"2330": {"name": "台積電", "turnover": 1.0,
                                    "industry": "半導體業"}},
                 "directory": {"2330": {"name": "台積電",
                                        "industry": "半導體業"},
                               "2317": {"name": "鴻海",
                                        "industry": "其他電子業"}}},
                ensure_ascii=False), encoding="utf-8")
            globals()["CORE_PATH"] = _ok
            w = []
            _c, _dir = load_core_universe(date(2026, 10, 21), w)
            check("正常檔案讀出代號與產業別", _c == {"2330": "半導體業"})
            check("directory 讀得到股名",
                  _dir.get("2317", {}).get("name") == "鴻海")
            check("directory 涵蓋非前 N 名的個股", "2317" in _dir and "2317" not in _c)
            check("剛產出的名單不發過期警告", not any("沒更新" in x for x in w))

            # 過期：as_of 距執行日超過 core_max_age_days
            _old = _d / "old.json"
            _old.write_text(json.dumps(
                {"as_of": "2026-09-01",
                 "codes": {"2330": {"name": "台積電",
                                    "industry": "半導體業"}}},
                ensure_ascii=False), encoding="utf-8")
            globals()["CORE_PATH"] = _old
            w = []
            _r, _ = load_core_universe(date(2026, 10, 21), w)
            check("過期名單照樣回傳內容", _r == {"2330": "半導體業"})
            check("過期名單要發警告", any("沒更新" in x for x in w))

            # 舊版格式（沒有 industry 欄位）要能讀、但要提醒
            _noind = _d / "noind.json"
            _noind.write_text(json.dumps(
                {"as_of": "2026-10-21",
                 "codes": {"2330": {"name": "台積電"}}},
                ensure_ascii=False), encoding="utf-8")
            globals()["CORE_PATH"] = _noind
            w = []
            _c2, _d2 = load_core_universe(date(2026, 10, 21), w)
            check("舊版格式仍讀得到代號", _c2 == {"2330": None})
            check("舊版格式沒有 directory 要發警告",
                  _d2 == {} and any("directory" in x for x in w))
            check("沒有產業別要發警告", any("沒有產業別" in x for x in w))

            _empty = _d / "empty.json"
            _empty.write_text('{"as_of": "2026-10-21", "codes": {}}',
                              encoding="utf-8")
            globals()["CORE_PATH"] = _empty
            w = []
            check("空名單回空字典並警告",
                  load_core_universe(date(2026, 10, 21), w) == ({}, {})
                  and any("空的" in x for x in w))
    finally:
        globals()["CORE_PATH"] = _real_core

    print("取價（load_prices）：")
    # 用假的 yfinance 模擬兩種欄位結構，鎖死 2026-10-21 那個「整批陪葬」的 bug。
    try:
        import pandas as _pd
        import types as _types

        _idx = _pd.to_datetime(["2026-10-19", "2026-10-20", "2026-10-21"])

        def _flat():
            return _pd.DataFrame({"Open": [1.0, 2, 3], "High": [1.0, 2, 3],
                                  "Low": [1.0, 2, 3], "Close": [1.0, 2, 3],
                                  "Volume": [10.0, 20, 30]}, index=_idx)

        def _multi(tks, bad=()):
            cols, data = [], {}
            for t in tks:
                for f in ("Open", "High", "Low", "Close", "Volume"):
                    cols.append((t, f))
                    v = [None, None, None] if t in bad else [1.0, 2.0, 3.0]
                    data[(t, f)] = v
            return _pd.DataFrame(data, index=_idx,
                                 columns=_pd.MultiIndex.from_tuples(cols))

        def _with_fake(df_factory):
            fake = _types.ModuleType("yfinance")
            fake.download = lambda **kw: df_factory(kw["tickers"].split())
            _sys.modules["yfinance"] = fake
            try:
                return load_prices(["2330", "2317"], date(2026, 10, 21), 30)
            finally:
                _sys.modules.pop("yfinance", None)

        # 1) 多檔 + MultiIndex（正常情況）
        r1 = _with_fake(lambda tks: _multi(tks))
        check("多檔 MultiIndex 正常解析", set(r1) == {"2330", "2317"})

        # 2) 單檔也回 MultiIndex（yfinance >=1.2 的行為）→ 不得丟 KeyError
        def _single_multi(tks):
            return _multi(tks[:1]) if len(tks) == 1 else _multi(tks)
        fake = _types.ModuleType("yfinance")
        fake.download = lambda **kw: _single_multi(kw["tickers"].split())
        _sys.modules["yfinance"] = fake
        try:
            r2 = load_prices(["2330"], date(2026, 10, 21), 30)
        finally:
            _sys.modules.pop("yfinance", None)
        check("單檔回 MultiIndex 也能解析", "2330" in r2)

        # 3) 其中一檔全是 NaN → 另一檔仍要拿到（不得整批陪葬）
        r3 = _with_fake(lambda tks: _multi(tks, bad=[tks[0]]))
        check("單一壞檔不拖垮整批", "2317" in r3 and "2330" not in r3)

        # 3b) 後綴快取（2026-10-21）：上櫃股每天固定 404 刷版面
        #     模擬「只有 .TWO 查得到」的個股，驗證快取記得住、下次不再白跑 .TW。
        def _otc_only(tks):
            ok = [t for t in tks if t.endswith(".TWO")]
            return _multi(ok) if ok else _pd.DataFrame()

        calls = []
        fake = _types.ModuleType("yfinance")

        def _dl(**kw):
            calls.append(kw["tickers"])
            return _otc_only(kw["tickers"].split())
        fake.download = _dl
        _sys.modules["yfinance"] = fake
        try:
            cache = {}
            r3b = load_prices(["6223"], date(2026, 10, 21), 30, suffix_cache=cache)
            check("上櫃股第一次要靠 .TWO 補抓抓到", "6223" in r3b)
            check("成功的後綴有寫進快取", cache.get("6223") == ".TWO")
            check("第一次確實白跑了一輪 .TW",
                  any(t == "6223.TW" for t in calls))

            calls.clear()
            r3c = load_prices(["6223"], date(2026, 10, 21), 30, suffix_cache=cache)
            check("有快取時直接拿到", "6223" in r3c)
            check("有快取時不再試 .TW（省掉那 20 行 404）",
                  calls == ["6223.TWO"])

            # 快取寫錯（例如個股轉上市）也要能自己救回來
            bad = {"2330": ".TWO"}
            calls.clear()
            fake.download = lambda **kw: (calls.append(kw["tickers"])
                                          or _multi([t for t in kw["tickers"].split()
                                                     if t.endswith(".TW")]))
            r3d = load_prices(["2330"], date(2026, 10, 21), 30, suffix_cache=bad)
            check("快取指向錯的後綴時仍能補抓回來", "2330" in r3d)
            check("補抓成功後快取要被更正", bad.get("2330") == ".TW")

            # 沒給快取（舊呼叫方式）不得壞掉
            fake.download = _dl
            check("不給 suffix_cache 也要能運作",
                  "6223" in load_prices(["6223"], date(2026, 10, 21), 30))
        finally:
            _sys.modules.pop("yfinance", None)

        # 4) 平欄位（舊版 yfinance）仍要能解析
        fake = _types.ModuleType("yfinance")
        fake.download = lambda **kw: _flat()
        _sys.modules["yfinance"] = fake
        try:
            r4 = load_prices(["2330"], date(2026, 10, 21), 30)
        finally:
            _sys.modules.pop("yfinance", None)
        check("平欄位（舊版）仍可解析", "2330" in r4)

        # 5) download 直接丟例外 → 回空 dict，不得往外炸
        fake = _types.ModuleType("yfinance")
        def _boom(**kw): raise RuntimeError("rate limited")
        fake.download = _boom
        _sys.modules["yfinance"] = fake
        try:
            r5 = load_prices(["2330"], date(2026, 10, 21), 30)
        finally:
            _sys.modules.pop("yfinance", None)
        check("download 爆掉時回空 dict 不外拋", r5 == {})
    except ImportError:
        check("（略過 load_prices 測試：沒有 pandas）", True)

    print("回填視窗：")
    b = _synth(n=40, step=0.01)
    check("bars_after 取到之後的日期", bars_after(b, b[10]["d"])[0]["d"] == b[11]["d"])

    print()
    if fails:
        print(f"❌ {len(fails)} 項失敗：" + "；".join(fails))
        return 1
    print("✅ 全部通過")
    return 0


def main():
    ap = argparse.ArgumentParser(description="起漲點追蹤 每日掃描")
    ap.add_argument("--date", help="資料日 YYYYMMDD，預設今天（台北）")
    ap.add_argument("--dry-run", action="store_true", help="不寫檔，只印摘要")
    ap.add_argument("--selftest", action="store_true", help="用合成資料驗證邏輯")
    a = ap.parse_args()

    if a.selftest:
        sys.exit(selftest())

    os.environ.setdefault("TZ", TPE)
    try:
        time.tzset()
    except AttributeError:
        pass
    d = datetime.strptime(a.date, "%Y%m%d").date() if a.date else date.today()
    run(d, dry_run=a.dry_run)


if __name__ == "__main__":
    main()
