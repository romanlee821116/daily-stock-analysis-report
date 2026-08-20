#!/bin/bash
# 由 launchd 每個交易日 06:15 呼叫。只做「重建 index → commit → push」,不產生任何報告內容。
set -uo pipefail
cd "$(dirname "$0")/.."

[ -x tools/build-index.sh ] && bash tools/build-index.sh

git add -A -- . ':!.autopush.log'
if git diff --staged --quiet; then
  echo "$(date '+%F %T') 沒有變更,不 push。"
  exit 0
fi
git commit -q -m "報告 $(date '+%Y-%m-%d')"

out=""; out2=""
if out=$(git push origin HEAD 2>&1); then
  echo "$(date '+%F %T') push 成功: $(git log -1 --oneline)"
  exit 0
fi

# 最常見的失敗:遠端有本機沒有的 commit(例如直接在 GitHub 網頁改過檔案)。
# 這種情況先 rebase 再重試一次,不需要人介入。
if printf '%s' "$out" | grep -qE 'rejected|fetch first|non-fast-forward'; then
  echo "$(date '+%F %T') 遠端有本機沒有的 commit,先 rebase 再重試…"
  if git pull --rebase --quiet origin main && out2=$(git push origin HEAD 2>&1); then
    echo "$(date '+%F %T') push 成功(rebase 後): $(git log -1 --oneline)"
    exit 0
  fi
  {
    echo "$(date '+%F %T') rebase 後仍失敗,需要手動處理。"
    printf '%s\n' "$out2"
    echo "提示:git status 看有沒有衝突;git rebase --abort 可以退回原狀。"
  } >&2
  exit 1
fi

# 其他失敗:憑證、網路、權限
{
  echo "$(date '+%F %T') push 失敗(不是 fast-forward 問題)。"
  printf '%s\n' "$out"
  echo "提示:若訊息提到 Permission denied / could not read from remote,"
  echo "     檢查 SSH 別名與金鑰(git remote -v 看用的是哪個 Host)。"
} >&2
exit 1
