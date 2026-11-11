#!/bin/bash
# 在你自己的 Mac 終端機跑：bash tools/install-claude-guard.sh
cd "$(dirname "$0")/.."
cp tools/launchd/com.roman.claude-guard.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.roman.claude-guard.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/com.roman.claude-guard.plist
launchctl list | grep claude-guard && echo "✅ 守護已掛上（每 5 分鐘檢查一次）"
echo
echo "===== 找兇手：Claude App 昨晚到今早是怎麼結束的 ====="
echo "--- 1. App 自己的紀錄（更新／結束）"
grep -h -i -E "quit|before-quit|will-quit|update|install|relaunch|exit|crash" ~/Library/Logs/Claude/main*.log 2>/dev/null | tail -25
echo "--- 2. 當機報告"
ls -lt ~/Library/Logs/DiagnosticReports 2>/dev/null | grep -i claude | head -5
echo "--- 3. 系統紀錄（過去 24 小時誰結束了 Claude）"
log show --last 24h --style compact --predicate 'eventMessage CONTAINS[c] "Claude" AND (eventMessage CONTAINS[c] "terminat" OR eventMessage CONTAINS[c] "killed" OR eventMessage CONTAINS[c] "quit")' 2>/dev/null | tail -20
