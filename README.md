# 台股主動式 ETF 每日資金流報告

每個交易日早上,Claude 的排程會抓 22 檔台股主動式 ETF 的持股異動、做分析,
把報告寫成 `reports/YYYYMMDD.html`,再由這台 Mac 上的一個 launchd 排程
自動 commit + push 上來。

- **報告產生**:Claude 排程(06:00 台北)——唯一的產生來源
- **推上 GitHub**:本機 launchd(06:15 台北)——只做 commit + push,不碰內容
- **公開網址**:https://romanlee821116.github.io/daily-stock-analysis-report/

## 結構

```
index.html            總覽(列出所有日期)——由 tools/build-index.sh 依檔名重建
reports/YYYYMMDD.html 每日報告
tools/build-index.sh  只列檔案重建 index,不抓資料、不做分析
tools/autopush.sh     commit + push(由 launchd 呼叫)
tools/setup-autopush.sh  一次性安裝腳本
```

## 一次性設定

```bash
bash tools/setup-autopush.sh "你的名字" "你在 romanlee821116 帳號用的 email"
```

它會設好這個 repo 專用的 commit 身分(不動全域設定,所以另一個 GitHub 帳號不受影響)、
裝好 06:15 的排程,並立刻試跑一次。

開啟公開網址:Settings → Pages → Source 選 **Deploy from a branch**,
Branch 選 `main`、資料夾選 **/ (root)**。

## 兩個 GitHub 帳號

commit 身分已用 `git config`(非 `--global`)綁在這個 repo。憑證若抓錯帳號,
改用 SSH 別名最保險:

```bash
# ~/.ssh/config
Host github-roman
  HostName github.com
  User git
  IdentityFile ~/.ssh/你的私鑰
  IdentitiesOnly yes
```

```bash
git remote set-url origin git@github-roman:romanlee821116/daily-stock-analysis-report.git
```

## 停用自動推送

```bash
launchctl unload ~/Library/LaunchAgents/com.roman.etf-report-autopush.plist
```

---

報告為持股異動的事實彙整與分類統計,不構成投資建議。
