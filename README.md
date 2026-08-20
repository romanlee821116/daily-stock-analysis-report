# 台股主動式 ETF 每日資金流報告

每個交易日早上,Claude 的排程會抓 22 檔台股主動式 ETF 的持股異動、做分析,
把報告寫成 `reports/YYYYMMDD.html`,再由這台 Mac 上的一個 launchd 排程
自動 commit + push 上來。

- **報告產生**:Claude 排程(06:00 台北)——唯一的產生來源
  - 盤前分析寫到 `premarket/YYYYMMDD.html`
  - ETF 追蹤寫到 `reports/YYYYMMDD.html`
- **推上 GitHub**:本機 launchd(06:15 台北)——只做 commit + push,不碰內容
- **公開網址**:https://romanlee821116.github.io/daily-stock-analysis-report/

## 結構

```
index.html            入口(左側 side tab + 右側報告)——由 tools/build-index.sh 依檔名重建
premarket/YYYYMMDD.html  每日盤前分析
reports/YYYYMMDD.html    ETF 每日追蹤報告
tools/build-index.sh  只列檔案重建 index,不抓資料、不做分析
tools/autopush.sh     commit + push(由 launchd 呼叫)
tools/setup-autopush.sh  一次性安裝腳本
```


報告為持股異動的事實彙整與分類統計,不構成投資建議。
