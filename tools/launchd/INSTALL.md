# 起漲點掃描 — 安裝（要在你自己的 macOS 上做，我碰不到）

這一步我做不到：Cowork 的 device_bash 跑在一個受限的 Linux VM 裡，
不是你的 macOS，看不到 launchd，而且連不到證交所與 Yahoo。以下要你自己跑。

## 0. 每天到底跑什麼

launchd 06:05 叫起 `tools/daily.sh`，它做兩件事：

1. `build_core.py` — 重算全市場近 5 日成交金額前 150 名（核心名單），順便抓產業別
2. `breakout_scan.py` — 觀察池＝**ETF 池 ∪ 核心名單**，掃起漲訊號

為什麼名單要每天重算：成交值排名會換人。拿一份舊名單一直用，
觀察池會慢慢失真，而且「用今天的名單看過去」就是前視偏誤。
每天重算才是 point-in-time。

build_core 失敗不會擋住掃描（沿用舊檔，掃描器會自己發過期警告）。
名單超過 14 天沒更新（`core_max_age_days`）就會在 warnings 裡提醒。

## 1. 裝 yfinance

```bash
cd ~/project/daily-stock-analysis-report
python3 -m pip install --user yfinance
```

⚠️ plist 用 `/usr/bin/python3`。確認**那一支**裝得到：

```bash
/usr/bin/python3 -c "import yfinance; print(yfinance.__version__)"
```

報 ModuleNotFoundError 的話，用 `which python3` 查出你實際在用的路徑，
把 plist 裡 `EnvironmentVariables` 的 `PY` 換成它。

## 2. 先手動跑一次

```bash
python3 tools/breakout_scan.py --selftest     # 64 項，應該全過
python3 tools/build_core.py  --selftest       # 18 項，應該全過
bash tools/daily.sh                           # 真的連網，約 3~4 分鐘
```

`daily.sh` 會印出核心名單前 10 名、掃描 counts 與 warnings。
首次執行一定會看到「首次執行：觀察池尚未暖機」——潛伏／蓄勢
要累積幾天才會穩定，那不是錯誤。

跑完檢查有沒有寫檔：

```bash
ls -la data/scan/
```

應該看到 `state.json` 和 `{日期}.json`。

## 3. 掛上 launchd（每天 06:05）

```bash
cp tools/launchd/com.roman.breakout-scan.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.roman.breakout-scan.plist 2>/dev/null
launchctl load  ~/Library/LaunchAgents/com.roman.breakout-scan.plist
launchctl list | grep breakout        # 應該看得到 com.roman.breakout-scan
```

之後看紀錄：`tail -80 data/scan/scan.log`

> 改過 plist 一定要 unload 再 load，launchd 不會自己重讀。

## 4. 還沒接的最後一段

掃描產出 `data/scan/{run_date}.json` 之後，要有人把它寫進 Notion。
目前**沒有任何排程會讀這個檔**（這正是起漲點追蹤一直是空的第二個原因）。
要接的話，得把起漲點 SOP 第 5 節加進「ETF tracker」排程的 prompt。
那會動到綁了資料夾的排程，需要你在對話裡核准一次。

## 已知缺口

- `build_core.py` **只含上市（TWSE）**。上櫃目前靠 ETF 池補一部分。
- 觀察池裡少數個股會是「未分類」：在 ETF 池但沒主題、又不在成交值前 150 名
  （所以沒對到產業別）。最近一次是 3 檔，不影響選股——`score()` 不看主題。
