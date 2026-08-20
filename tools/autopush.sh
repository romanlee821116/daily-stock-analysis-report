#!/bin/bash
set -uo pipefail
cd "$(dirname "$0")/.."
[ -x tools/build-index.sh ] && bash tools/build-index.sh
git add -A -- . ':!.autopush.log'
if git diff --staged --quiet; then
  echo "$(date '+%F %T') 沒有變更,不 push。"
  exit 0
fi
git commit -q -m "報告 $(date '+%Y-%m-%d')"
if git push -q origin HEAD; then
  echo "$(date '+%F %T') push 成功: $(git log -1 --oneline)"
else
  echo "$(date '+%F %T') push 失敗。檢查 git 憑證(兩個 GitHub 帳號時建議改用 SSH 別名)。" >&2
  exit 1
fi
