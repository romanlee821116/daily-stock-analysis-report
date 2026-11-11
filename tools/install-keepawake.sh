#!/bin/bash
# 一次裝好「清晨保持清醒」：在你自己的 Mac 終端機跑  bash tools/install-keepawake.sh
set -e
cd "$(dirname "$0")/.."
echo "== 1/4 目前的排程喚醒設定"; pmset -g sched || true
echo "== 2/4 設定週一到週五 05:40 喚醒（需要輸入 Mac 密碼）"
sudo pmset repeat wakeorpoweron MTWRF 05:40:00
echo "== 3/4 插電時不自動休眠（螢幕可以關，系統不睡）"
sudo pmset -c sleep 0
echo "== 4/4 掛上 launchd"
cp tools/launchd/com.roman.keepawake.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.roman.keepawake.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.roman.keepawake.plist
launchctl list | grep -E "keepawake|prefetch|breakout" || true
pmset -g sched
echo
echo "完成。最近一週的睡眠紀錄（看 07:00~09:00 之間是不是 Sleep）："
pmset -g log | grep -E " (Sleep|Wake|DarkWake) " | grep -E "0[5-9]:[0-9]{2}:[0-9]{2}" | tail -30
