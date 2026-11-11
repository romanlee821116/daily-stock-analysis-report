#!/bin/bash
# Claude 桌面 App 守護：每 5 分鐘檢查一次，App 沒在跑就自動重開，並記下「幾點發現它被關掉」。
# 2026/11/11：清晨排程連不到 Mac，Roman 確認是 Claude App 被關掉。原因還沒查到之前，先保證它會被叫回來，
# 同時用 data/claude-guard.log 留下證據，之後對照 App 自己的 log 找兇手（自動更新？防毒？當機？）。
cd "$(dirname "$0")/.." || exit 1
LOG="data/claude-guard.log"
if ! pgrep -xq "Claude"; then
  echo "$(date '+%F %T') ⚠️ Claude App 沒在跑 → 重新開啟" >> "$LOG"
  open -g -a "Claude" >> "$LOG" 2>&1
  sleep 20
  pgrep -xq "Claude" && echo "$(date '+%F %T') 已重新開啟" >> "$LOG" || echo "$(date '+%F %T') ❌ 重開失敗" >> "$LOG"
fi
tail -n 1000 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
