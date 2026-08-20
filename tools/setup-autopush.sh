#!/bin/bash
# 在你的 Mac 上跑一次就好。做三件事:
#   1. 設定這個 repo 的 commit 身分(只影響這個 repo,不動全域設定)
#   2. 裝一個每個交易日 06:15 自動 commit + push 的排程(launchd)
#   3. 立刻試跑一次
#
# 用法:
#   bash tools/setup-autopush.sh "你的名字" "你在 romanlee821116 這個帳號用的 email"
#
# 想改用 SSH(兩個 GitHub 帳號時最保險),先手動跑:
#   git remote set-url origin git@github-roman:romanlee821116/daily-stock-analysis-report.git
# 並在 ~/.ssh/config 設好 github-roman 這個 Host 別名,再跑這支腳本。

set -euo pipefail

NAME="${1:-}"
EMAIL="${2:-}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.roman.etf-report-autopush"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$REPO/.autopush.log"

if [ -z "$NAME" ] || [ -z "$EMAIL" ]; then
  echo "用法: bash tools/setup-autopush.sh \"你的名字\" \"你的 email\"" >&2
  exit 1
fi

echo "==> repo: $REPO"
cd "$REPO"

# 1. 這個 repo 專用的身分(不動 --global,所以另一個 GitHub 帳號不受影響)
git config user.name  "$NAME"
git config user.email "$EMAIL"
echo "==> commit 身分已設為 $NAME <$EMAIL>(僅此 repo)"

# 2. 寫一支 push 腳本
cat > tools/autopush.sh <<'INNER'
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
INNER
chmod +x tools/autopush.sh
echo "==> 已寫入 tools/autopush.sh"

# 3. launchd:週一到週五 06:15
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$REPO/tools/autopush.sh</string></array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>6</integer><key>Minute</key><integer>15</integer></dict>
    <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>6</integer><key>Minute</key><integer>15</integer></dict>
    <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>6</integer><key>Minute</key><integer>15</integer></dict>
    <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>6</integer><key>Minute</key><integer>15</integer></dict>
    <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>6</integer><key>Minute</key><integer>15</integer></dict>
  </array>
</dict></plist>
PL

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "==> 排程已安裝:週一到週五 06:15 自動 commit + push"
echo "    紀錄檔:$LOG"
echo "    要停用:launchctl unload $PLIST"

# 4. 立刻試跑
echo "==> 現在試跑一次..."
bash tools/autopush.sh || {
  echo ""
  echo "試跑失敗。最常見原因是 git 憑證抓錯帳號(你有兩個 GitHub 帳號)。"
  echo "建議改成 SSH 別名:"
  echo "  1) ~/.ssh/config 加:"
  echo "       Host github-roman"
  echo "         HostName github.com"
  echo "         User git"
  echo "         IdentityFile ~/.ssh/你的私鑰"
  echo "         IdentitiesOnly yes"
  echo "  2) git remote set-url origin git@github-roman:romanlee821116/daily-stock-analysis-report.git"
  echo "  3) 再跑 bash tools/autopush.sh"
  exit 1
}
echo ""
echo "全部完成。"
