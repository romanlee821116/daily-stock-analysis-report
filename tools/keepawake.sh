#!/bin/bash
# 交易日清晨讓 Mac 保持清醒到 09:30，確保雲端排程（06:00 ETF tracker、07:25 盤前報告）
# 觸發時連得到這台 Mac。
#
# 為什麼需要（2026/11/11 診斷）：
#   pmset 05:45 的排程喚醒只是「短暫醒來」，跑完 05:50 prefetch、06:05 掃描後，
#   沒有使用者操作的 MacBook 很快又睡回去。07:25 盤前報告觸發時雲端連不到 Mac
#   → 排程被標 device_absent 暫停 → 要等你 09:00 打開電腦才補跑（11/06、11/10 都是 09:01 才跑）。
#   本機 launchd 有跑 ≠ Claude 桌面 App 連得上雲端。
#
# 做三件事：
#   1. caffeinate 擋住系統／顯示器／磁碟休眠到 09:30
#   2. 確認 Claude 桌面 App 在跑（沒跑就叫起來）
#   3. 每 5 分鐘寫一行心跳到 data/awake.log，雲端排程可以讀它判斷 Mac 當時是不是醒著
set -u
cd "$(dirname "$0")/.." || exit 1
LOG="data/awake.log"
mkdir -p data
END_HHMM="${END_HHMM:-0930}"

now=$(date +%s)
end=$(date -j -f "%Y%m%d%H%M" "$(date +%Y%m%d)${END_HHMM}" +%s 2>/dev/null || echo $((now + 13500)))
secs=$(( end - now )); [ "$secs" -lt 600 ] && secs=600

power=$(pmset -g batt 2>/dev/null | head -1 | sed "s/.*'\(.*\)'.*/\1/")
lid=$(ioreg -r -k AppleClamshellState -d 4 2>/dev/null | grep -o '"AppleClamshellState" = [A-Za-z]*' | awk '{print $3}')
echo "$(date '+%F %T') keepawake 開始｜電源=${power:-?}｜螢幕蓋上=${lid:-?}｜保持 ${secs}s" >> "$LOG"
[ "$lid" = "Yes" ] && echo "$(date '+%F %T') ⚠️ 螢幕是蓋上的：MacBook 蓋上且沒接外接螢幕時，caffeinate 也擋不住休眠" >> "$LOG"
[ "$power" = "Battery Power" ] && echo "$(date '+%F %T') ⚠️ 使用電池：建議插電，否則 -s 無效、只剩 -i 防閒置休眠" >> "$LOG"

caffeinate -dimsu -t "$secs" &
CAF=$!

if ! pgrep -xq "Claude"; then
  open -g -a "Claude" && echo "$(date '+%F %T') Claude App 原本沒在跑，已叫起" >> "$LOG"
fi

while kill -0 "$CAF" 2>/dev/null; do
  app=$(pgrep -xq "Claude" && echo 在跑 || echo 沒跑)
  echo "$(date '+%F %T') 心跳｜Claude App ${app}" >> "$LOG"
  sleep 300
done
echo "$(date '+%F %T') keepawake 結束" >> "$LOG"
# 只保留最近 2000 行
tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
