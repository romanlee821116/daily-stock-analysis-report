# 起漲點掃描 — 安裝（要在你自己的 macOS 上做，我碰不到）

這一步我做不到：Cowork 的 device_bash 跑在一個受限的 Linux VM 裡，
不是你的 macOS，看不到 launchd 也沒有對外網路。以下三步要你自己跑一次。

## 1. 裝 yfinance

```bash
cd ~/project/daily-stock-analysis-report
python3 -m pip install --user yfinance
```

## 2. 先手動跑一次，確認能抓到資料

```bash
python3 tools/breakout_scan.py --selftest     # 邏輯自我測試，應該 24 項全過
python3 tools/breakout_scan.py --dry-run      # 真的連網抓資料，但不寫檔
```

`--dry-run` 會印出 counts 與 warnings。首次執行一定會看到
「首次執行：觀察池尚未暖機」，那是正常的 —— 潛伏／蓄勢需要幾天才會穩定。

確認沒問題後跑一次正式的：

```bash
python3 tools/breakout_scan.py
ls -la data/scan/
```

## 3. 掛上 launchd（每天 06:05）

```bash
cp tools/launchd/com.roman.breakout-scan.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.roman.breakout-scan.plist 2>/dev/null
launchctl load  ~/Library/LaunchAgents/com.roman.breakout-scan.plist
launchctl list | grep breakout        # 應該看得到 com.roman.breakout-scan
```

之後看紀錄：`tail -50 data/scan/scan.log`

> plist 寫死 `/usr/bin/python3`。若你用的是 Homebrew 或 pyenv 的 python，
> 用 `which python3` 把路徑換掉，否則 launchd 會找不到 yfinance。

## 4. 還沒接的最後一段

掃描產出 `data/scan/{run_date}.json` 之後，要有人把它寫進 Notion。
目前**沒有任何排程會讀這個檔**（這正是起漲點追蹤一直是空的第二個原因）。
要接的話，得把起漲點 SOP 第 5 節加進「ETF tracker」排程的 prompt。
那會動到綁了資料夾的排程，需要你在對話裡核准一次。
