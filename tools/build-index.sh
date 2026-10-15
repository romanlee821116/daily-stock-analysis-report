#!/bin/bash
# 依 premarket/ 與 reports/ 裡的檔案重建 index.html。
# 這個腳本只列檔案、不抓資料、不做任何分析——報告內容一律由 Claude 排程產生。
set -euo pipefail
cd "$(dirname "$0")/.."

RECENT=8   # sidebar 直接展開的筆數,其餘收進「更多」

# 贊助連結(sidebar 底部)
KOFI_URL="https://ko-fi.com/Y4A328TJ0Y"
KOFI_EMBED="${KOFI_URL}/?hidefeed=true&widget=true&embed=true&preview=true"

# 掃一個目錄,新到舊輸出「日期<TAB>路徑」。
# 檔名只要含 8 位數日期就算,所以 20260820.html 與
# twse_night_brief_20260820.html 都吃得下——排程交付的原檔名可以直接丟進來。
# 同一天有多個檔時只取排序最前的那個。
scan() {
  local dir=$1 f base d
  for f in $(ls -1 "$dir"/*.html 2>/dev/null); do
    base=$(basename "$f" .html)
    d=$(printf '%s' "$base" | grep -oE '[0-9]{8}' | tail -1) || true
    [ -n "$d" ] || continue
    printf '%s\t%s\n' "$d" "$f"
  done | sort -r | awk -F'\t' '!seen[$1]++'
}

# 有幾行(空字串算 0 行——wc -l 對空字串會回 1,不能直接用)
count() {
  if [ -z "$1" ]; then echo 0; else printf '%s\n' "$1" | wc -l | tr -d ' '; fi
}

# 產生一個分類的 sidebar 區塊。
# $1=分類標題 $2=view 前綴 $3=報告標題前綴 $4=清單內容 $5=是否為預設選中分類(1/0)
group() {
  local title=$1 pre=$2 label=$3 list=$4 is_default=$5
  local n=0 total d f pretty cls tag row out="" more=""
  total=$(count "$list")

  printf '<div class="grp">\n<div class="grp-h">%s</div>\n' "$title"
  if [ "$total" -eq 0 ]; then
    printf '<p class="empty">尚無內容</p>\n</div>\n'
    return 0
  fi

  while IFS=$'\t' read -r d f; do
    n=$((n + 1))
    pretty="${d:0:4}-${d:4:2}-${d:6:2}"
    cls=""
    tag=""
    if [ "$n" -eq 1 ]; then
      tag='<span class="tag">最新</span>'
      if [ "$is_default" = "1" ]; then cls=' class="on"'; fi
    fi
    row="<li><a${cls} href=\"${f}\" data-view=\"${pre}-${d}\" data-title=\"${label} ${pretty}\">${pretty}${tag}</a></li>"$'\n'
    if [ "$n" -le "$RECENT" ]; then out+="$row"; else more+="$row"; fi
  done <<< "$list"

  printf '<ul>\n%s</ul>\n' "$out"
  if [ -n "$more" ]; then
    printf '<details><summary>更多 %s 筆</summary>\n<ul>\n%s</ul>\n</details>\n' \
      "$((total - RECENT))" "$more"
  fi
  printf '</div>\n'
  return 0
}

pre_list=$(scan premarket)
etf_list=$(scan reports)
pre_total=$(count "$pre_list")
etf_total=$(count "$etf_list")

# 預設顯示:盤前分析優先(有內容才算),否則 ETF 追蹤
first_line=""
default_pre=0
first_label=""
if [ "$pre_total" -gt 0 ]; then
  default_pre=1
  first_line=${pre_list%%$'\n'*}
  first_label="盤前分析"
elif [ "$etf_total" -gt 0 ]; then
  first_line=${etf_list%%$'\n'*}
  first_label="ETF 每日追蹤"
fi

if [ -n "$first_line" ]; then
  first_date=${first_line%%$'\t'*}
  first_src=${first_line#*$'\t'}
  first_title="${first_label} ${first_date:0:4}-${first_date:4:2}-${first_date:6:2}"
else
  first_src=""
  first_title="尚無報告"
fi

etf_default=0
if [ "$default_pre" = "0" ] && [ "$etf_total" -gt 0 ]; then etf_default=1; fi

nav_pre=$(group "每日盤前分析" pre "盤前分析" "$pre_list" "$default_pre")
nav_etf=$(group "ETF 每日追蹤" etf "ETF 每日追蹤" "$etf_list" "$etf_default")

if [ -n "$first_src" ]; then
  stage="<iframe id=\"view\" src=\"${first_src}\" title=\"${first_title}\"></iframe>"
else
  stage='<p class="blank">還沒有任何報告。每個交易日早上由 Claude 排程產生後會出現在左側。</p>'
fi

cat > index.html <<HTML
<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>台股每日追蹤</title>
<style>
:root{color-scheme:light dark;
 --plane:#f9f9f7;--surface:#fcfcfb;--tp:#0b0b0b;--ts:#52514e;--mu:#898781;
 --grid:#e1e0d9;--acc:#2a78d6;--hi:rgba(11,11,11,.05)}
@media (prefers-color-scheme:dark){:root{
 --plane:#0d0d0d;--surface:#1a1a19;--tp:#fff;--ts:#c3c2b7;--mu:#898781;
 --grid:#2c2c2a;--acc:#3987e5;--hi:rgba(255,255,255,.06)}}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--plane);color:var(--tp);
 font:15px/1.6 system-ui,-apple-system,"Segoe UI","Noto Sans TC","PingFang TC",sans-serif}
.app{display:flex;height:100%}
.side{flex:0 0 250px;width:250px;background:var(--surface);border-right:1px solid var(--grid);
 overflow-y:auto;padding:20px 0 24px}
.brand{padding:0 18px 10px;font-size:15px;font-weight:600;letter-spacing:-.01em}
.brand small{display:block;font-weight:400;font-size:12px;color:var(--mu);margin-top:2px}
.grp{padding:12px 0 2px}
.grp-h{padding:0 18px 6px;font-size:12px;color:var(--mu)}
.side ul{list-style:none;margin:0;padding:0}
.side a{display:flex;justify-content:space-between;align-items:center;gap:8px;
 padding:6px 18px;color:var(--ts);text-decoration:none;font-size:14px;
 font-variant-numeric:tabular-nums;border-left:2px solid transparent}
.side a:hover{background:var(--hi);color:var(--tp)}
.side a.on{color:var(--acc);border-left-color:var(--acc);background:var(--hi);font-weight:500}
.tag{font-size:11px;color:var(--mu)}
.side a.on .tag{color:var(--acc)}
summary{padding:6px 18px;font-size:12px;color:var(--mu);cursor:pointer}
summary:hover{color:var(--tp)}
.empty{padding:0 18px;margin:0;font-size:13px;color:var(--mu)}
.foot{margin:18px 18px 0;padding-top:14px;border-top:1px solid var(--grid);
 font-size:11px;line-height:1.5;color:var(--mu)}
.support{margin:18px 18px 0;display:flex;flex-direction:column;gap:6px}
.support-h{font-size:12px;color:var(--mu)}
.support a{display:block;padding:6px 10px;border:1px solid var(--grid);border-radius:6px;
 color:var(--ts);font-size:13px;text-decoration:none}
.support a:hover{color:var(--tp);border-color:var(--acc);background:var(--hi)}
.kofi{width:min(400px,calc(100vw - 32px));height:min(740px,calc(100vh - 32px));padding:0;
 border:1px solid var(--grid);border-radius:12px;background:var(--surface);color:var(--tp);overflow:hidden}
.kofi::backdrop{background:rgba(0,0,0,.45)}
.kofi-bar{display:flex;justify-content:space-between;align-items:center;
 padding:10px 10px 10px 16px;border-bottom:1px solid var(--grid);font-size:14px}
.kofi-x{border:0;background:none;color:var(--mu);font-size:22px;line-height:1;padding:2px 8px;cursor:pointer}
.kofi-x:hover{color:var(--tp)}
.kofi iframe{height:calc(100% - 49px);background:#fff}
.stage{flex:1;min-width:0}
iframe{display:block;width:100%;height:100%;border:0;background:var(--plane)}
.blank{padding:40px 24px;color:var(--mu)}
@media (max-width:760px){
 .app{flex-direction:column}
 .side{flex:0 0 auto;width:auto;border-right:0;border-bottom:1px solid var(--grid);
  display:flex;align-items:flex-start;gap:14px;overflow-x:auto;padding:12px 0}
 .brand{padding:0 14px;white-space:nowrap}
 .brand small{display:none}
 .grp{padding:0}
 .grp-h{padding:0 10px 2px}
 .side ul{display:flex;gap:2px}
 .side a{border-left:0;border-bottom:2px solid transparent;padding:2px 10px;white-space:nowrap}
 .side a.on{border-bottom-color:var(--acc);border-left-color:transparent}
 .side details{display:none}
 .support{margin:0 14px 0 0;flex-direction:row;align-items:center}
 .support-h{display:none}
 .support a{white-space:nowrap;padding:2px 10px;border:1px solid var(--grid)}
 .foot{display:none}
 .kofi{width:100vw;height:100dvh;max-width:none;max-height:none;margin:0;border:0;border-radius:0}
 .stage{flex:1;min-height:0}
}
</style></head>
<body><div class="app">
<aside class="side">
<div class="brand">台股每日追蹤<small>盤前分析 × 主動式 ETF 資金流</small></div>
${nav_pre}
${nav_etf}
<div class="support">
<div class="support-h">覺得有幫助? 歡迎贊助</div>
<a id="kofi-open" href="${KOFI_URL}" target="_blank" rel="noopener">☕ 在 Ko-fi 請我喝咖啡</a>
</div>
<p class="foot">資料來源 etfedge.xyz｜報告由 Claude 每日排程產生。<br>
本站為事實彙整與分類統計,不構成投資建議。</p>
</aside>
<main class="stage">${stage}</main>
</div>
<dialog class="kofi" id="kofi" aria-label="贊助">
<div class="kofi-bar">覺得有幫助? 歡迎贊助<button class="kofi-x" type="button" aria-label="關閉">×</button></div>
<iframe data-src="${KOFI_EMBED}" title="Ko-fi 贊助"></iframe>
</dialog>
<script>
// 贊助視窗:點側欄按鈕才載入 Ko-fi,cmd/ctrl 點擊維持開新分頁
(function(){
  var dlg=document.getElementById('kofi'),btn=document.getElementById('kofi-open');
  if(!dlg||!btn||!dlg.showModal)return;
  var f=dlg.querySelector('iframe');
  btn.addEventListener('click',function(e){
    if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey||e.button!==0)return;
    e.preventDefault();
    if(!f.getAttribute('src'))f.setAttribute('src',f.getAttribute('data-src'));
    dlg.showModal();
  });
  dlg.querySelector('.kofi-x').addEventListener('click',function(){dlg.close()});
  dlg.addEventListener('click',function(e){if(e.target===dlg)dlg.close()});
})();
</script>
<script>
(function(){
  var frame=document.getElementById('view');
  if(!frame)return;
  var links=[].slice.call(document.querySelectorAll('.side a[data-view]'));
  function show(a,push){
    frame.src=a.getAttribute('href');
    frame.title=a.getAttribute('data-title');
    links.forEach(function(x){x.classList.toggle('on',x===a)});
    document.title=a.getAttribute('data-title')+'｜台股每日追蹤';
    if(push)history.replaceState(null,'','#'+a.getAttribute('data-view'));
  }
  links.forEach(function(a){
    a.addEventListener('click',function(e){
      // 讓 cmd/ctrl/中鍵點擊維持「開新分頁看完整報告」的預設行為
      if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey||e.button!==0)return;
      e.preventDefault();
      show(a,true);
      if(window.innerWidth<=760)frame.scrollIntoView({block:'start'});
    });
  });
  var h=location.hash.slice(1);
  if(h){
    var target=links.filter(function(a){return a.getAttribute('data-view')===h})[0];
    if(target)show(target,false);
  }
  // 報告頁底部有「回總覽」連結,在框架內看是多餘的,載入後移除。
  frame.addEventListener('load',function(){
    try{
      var d=frame.contentDocument;
      if(!d)return;
      [].slice.call(d.querySelectorAll('a[href\$="index.html"]')).forEach(function(el){
        (el.closest('p')||el).remove();
      });
    }catch(err){}
  });
})();
</script>
</body></html>
HTML

echo "index.html 重建完成(盤前 ${pre_total} 份、ETF ${etf_total} 份)"
