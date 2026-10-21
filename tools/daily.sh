#!/bin/bash
# 每天的例行工作：先更新核心名單，再跑起漲點掃描。
#
# 為什麼要有這支 wrapper：
#   core_universe.json 是靜態檔，不重跑 build_core.py 就會過期。
#   掃描器雖然會在超過 core_max_age_days（14 天）時發警告，
#   但警告只是警告 —— 成交值排名早就換人了，觀察池會慢慢失真。
#   點在於「每天用當下可得的資料重算排名」才是 point-in-time。
#
# 設計原則：build_core 失敗不得擋住掃描。
#   名單舊一天還能用（掃描器會自己警告），但掃描沒跑就是整天沒訊號。

set -u
cd "$(dirname "$0")/.." || exit 1
PY="${PY:-/usr/bin/python3}"

echo "===== $(date '+%Y-%m-%d %H:%M:%S') 開始 ====="

# 同時只跑一份，避免手動執行跟 launchd 撞在一起寫壞 state.json
LOCK="data/scan/.daily.lock"
mkdir -p data/scan
if ! mkdir "$LOCK" 2>/dev/null; then
    echo "另一份 daily.sh 還在跑（$LOCK 存在），本次跳過"
    exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

echo "--- 更新核心名單 ---"
if "$PY" tools/build_core.py --days 5 --top 150; then
    echo "核心名單更新完成"
else
    echo "⚠️ 核心名單更新失敗（rc=$?），沿用舊檔繼續掃描"
fi

echo "--- 起漲點掃描 ---"
"$PY" tools/breakout_scan.py
rc=$?
echo "===== $(date '+%Y-%m-%d %H:%M:%S') 結束（掃描 rc=$rc）====="
exit $rc
