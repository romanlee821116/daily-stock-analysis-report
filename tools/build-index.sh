#!/bin/bash
# 依 reports/ 裡的檔案重建 index.html。
# 這個腳本只列檔案、不抓資料、不做任何分析——報告內容一律由 Claude 排程產生。
set -euo pipefail
cd "$(dirname "$0")/.."

rows=""
for f in $(ls -1 reports/*.html 2>/dev/null | sort -r); do
  d=$(basename "$f" .html)
  [[ "$d" =~ ^[0-9]{8}$ ]] || continue
  pretty="${d:0:4}-${d:4:2}-${d:6:2}"
  rows+="<tr><th scope=\"row\"><a href=\"reports/${d}.html\">${pretty}</a></th></tr>"$'\n'
done
latest=$(ls -1 reports/*.html 2>/dev/null | sort -r | head -1 || true)
if [ -n "$latest" ]; then
  latest_link="<a href=\"${latest}\"><strong>→ 看最新一天的報告</strong></a>"
else
  rows="<tr><td>尚無報告。</td></tr>"
  latest_link="尚無報告。"
fi

cat > index.html <<HTML
<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>台股主動式ETF 每日資金流追蹤</title>
<style>
:root{color-scheme:light dark}
body{margin:0;background:#f9f9f7;color:#0b0b0b;
 font:15px/1.6 system-ui,-apple-system,"Segoe UI","Noto Sans TC","PingFang TC",sans-serif}
@media (prefers-color-scheme:dark){body{background:#0d0d0d;color:#fff}
 .card{background:#1a1a19!important;border-color:rgba(255,255,255,.10)!important}
 tbody tr{border-color:#2c2c2a!important} thead th{color:#898781!important}
 a{color:#3987e5!important} .mu{color:#898781!important}}
.wrap{max-width:760px;margin:0 auto;padding:32px 20px 72px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}
.lede{color:#52514e;margin:0 0 14px}
.card{background:#fcfcfb;border:1px solid rgba(11,11,11,.10);border-radius:12px;padding:8px 18px}
table{width:100%;border-collapse:collapse}
th{padding:9px 4px;text-align:left;font-weight:400}
thead th{font-size:12px;color:#898781;border-bottom:1px solid #e1e0d9}
tbody tr{border-bottom:1px solid #e1e0d9}
tbody tr:last-child{border-bottom:0}
a{color:#2a78d6}
.mu{color:#898781;font-size:12px}
footer{margin-top:40px;color:#898781;font-size:12px;border-top:1px solid #e1e0d9;padding-top:14px}
</style></head>
<body><div class="wrap">
<h1>台股主動式 ETF 每日資金流追蹤</h1>
<p class="lede">追蹤 22 檔台股主動式 ETF 的每日持股異動。每個交易日早上自動更新。</p>
<p>${latest_link}</p>
<div class="card"><table>
<thead><tr><th>資料日</th></tr></thead>
<tbody>
${rows}
</tbody></table></div>
<footer>資料來源 etfedge.xyz｜報告由 Claude 每日排程產生。<br>
本站為持股異動的事實彙整與分類統計,不構成投資建議。</footer>
</div></body></html>
HTML

echo "index.html 重建完成($(ls -1 reports/*.html 2>/dev/null | wc -l | tr -d ' ') 份報告)"
