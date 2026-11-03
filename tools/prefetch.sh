#!/bin/bash
# 交易日清晨、雲端排程開跑前執行(launchd 05:50):
#   1. 在本機抓 22 檔主動式 ETF 的 daily JSON,存到 data/etf-raw/{今天}/。
#      雲端排程的沙箱連不到 etfedge.xyz,原本只能靠 Claude in Chrome;
#      Chrome 擴充功能閒置一晚常常斷線,排程就會回「Chrome 橋接不可用」。
#      先在本機抓好,雲端直接讀檔,Chrome 只當備案。
#   2. 開一個 Chrome 分頁喚醒 Claude in Chrome 擴充功能,讓盤前分析查 MOPS / TWSE 時連得上。
set -u
cd "$(dirname "$0")/.." || exit 1

ETFS="00981A 00403A 00991A 00982A 00992A 00405A 00400A 00407A 00980A 00406A 00999A
00985A 00993A 00984A 00994A 00995A 00996A 00404A 00401A 00987A 00408A 00410A"
CHROME_PROFILE="Profile 3"   # 裝了 Claude in Chrome 的那個 profile

today=$(TZ=Asia/Taipei date +%Y%m%d)
out="data/etf-raw/${today}"
mkdir -p "$out"
echo "===== $(date '+%F %T') prefetch 開始 ====="

ok=0
fail=""
for code in $ETFS; do
  lower=$(printf '%s' "$code" | tr 'A-Z' 'a-z')
  tmp="${out}/.${code}.json"
  if curl -sf --retry 3 --retry-delay 5 -m 30 -A 'Mozilla/5.0' \
       "https://etfedge.xyz/preview/${lower}-daily.json" -o "$tmp" \
     && /usr/bin/python3 -c 'import json,sys; json.load(open(sys.argv[1]))["as_of"]' "$tmp" 2>/dev/null; then
    mv "$tmp" "${out}/${code}.json"
    ok=$((ok + 1))
  else
    rm -f "$tmp"
    fail="${fail} ${code}"
  fi
done

# 給雲端排程看的摘要:每檔的 as_of,一眼就知道哪幾檔資料日落後
/usr/bin/python3 - "$out" <<'PY' > "${out}/manifest.txt"
import json, os, sys
d = sys.argv[1]
for f in sorted(os.listdir(d)):
    if f.endswith(".json"):
        print(f[:-5], json.load(open(os.path.join(d, f)))["as_of"])
PY

echo "ETF JSON:成功 ${ok}/22 檔${fail:+,失敗:${fail}}"

# 只保留最近 10 天,避免資料夾無限長大
ls -1d data/etf-raw/20* 2>/dev/null | sort -r | tail -n +11 | xargs rm -rf

# Chrome 已在跑時,直接呼叫執行檔會把網址交給現有的 Chrome,在指定 profile 開新分頁
# (用 open -a ... --args 的話,參數只在 Chrome 尚未啟動時才有效)
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --profile-directory="${CHROME_PROFILE}" "https://claude.ai/" >/dev/null 2>&1 &
echo "已開分頁喚醒 Chrome 擴充功能(${CHROME_PROFILE})"

echo "===== $(date '+%F %T') prefetch 結束 ====="
