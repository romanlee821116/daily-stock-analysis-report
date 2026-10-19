# -*- coding: utf-8 -*-
"""挑出真實起漲日（突破20日高 + 後續10日最大漲幅>=15%），印出各條件的實際數值。"""
import csv, importlib.util, os, pathlib
REPO = pathlib.Path(os.path.expanduser("~/mnt/daily-stock-analysis-report"))
spec = importlib.util.spec_from_file_location("bs", REPO/"tools"/"breakout_scan.py")
bs = importlib.util.module_from_spec(spec); spec.loader.exec_module(bs); P = bs.PARAMS
bars={}
for r in csv.DictReader(open(REPO/"backtest"/"prices.csv")):
    bars.setdefault(r["code"],[]).append({"d":r["date"],"o":float(r["open"]),"h":float(r["high"]),
        "l":float(r["low"]),"c":float(r["close"]),"v":float(r["volume"])})
for c in bars: bars[c].sort(key=lambda x:x["d"])
w=[]; flows=bs.load_etf_flows(REPO/"reports",w); fdays=sorted(flows)
NAME={}
for a in fdays:
    for c,r in flows[a].items(): NAME.setdefault(c,r["name"])

cases=[]
for c in bars:
    b=bars[c]
    for j in range(len(b)):
        if j<25 or j+10>=len(b): continue
        i=bs.indicators(b[:j+1],{"net":0.0,"buyers":0},0,0)
        if not i: continue
        if b[j]["c"] <= i["hi_n"]: continue              # 必須突破
        mx=(max(x["h"] for x in b[j+1:j+11])/b[j]["c"]-1)*100
        if mx < 15: continue                              # 後續確實有行情
        cases.append((b[j]["d"], c, NAME.get(c,""), i, mx))
cases.sort()
print(f"真實起漲日（突破前20日高 且 後10日最大漲幅>=15%）：{len(cases)} 個\n")
hdr=f"{'日期':<11}{'代號':<6}{'名稱':<8}{'漲幅%':>7}{'量比':>6}{'上影%':>7}{'乖離%':>7}{'後10日最大%':>11}  現行判定"
print(hdr); print("─"*len(hdr)+"──────")
for d,c,n,i,mx in cases:
    ok=[]
    if i["day_gain"]<P["launch_day_gain_min"]: ok.append("漲幅")
    if not(i["vol_ratio"] and i["vol_ratio"]>=P["launch_vol_ratio_min"]): ok.append("量比")
    if i["upper_shadow_ratio"]>P["launch_upper_shadow_max"]: ok.append("上影線")
    if not(i["ma20_bias"] is not None and i["ma20_bias"]<=P["launch_ma20_bias_max"]): ok.append("乖離")
    verdict="✅ 起漲" if not ok else "❌ 卡在 "+"、".join(ok)
    print(f"{d:<11}{c:<6}{n:<8}{i['day_gain']:>+7.2f}{i['vol_ratio'] or 0:>6.2f}"
          f"{i['upper_shadow_ratio']*100:>7.0f}{i['ma20_bias'] or 0:>+7.2f}{mx:>+11.1f}  {verdict}")

from collections import Counter
cnt=Counter()
for d,c,n,i,mx in cases:
    if i["day_gain"]<P["launch_day_gain_min"]: cnt["漲幅>=3%"]+=1
    if not(i["vol_ratio"] and i["vol_ratio"]>=P["launch_vol_ratio_min"]): cnt["量比>=1.5"]+=1
    if i["upper_shadow_ratio"]>P["launch_upper_shadow_max"]: cnt["上影線<=30%"]+=1
    if not(i["ma20_bias"] is not None and i["ma20_bias"]<=P["launch_ma20_bias_max"]): cnt["乖離<=15%"]+=1
print(f"\n在這 {len(cases)} 個真實起漲日裡，各條件各擋掉幾個：")
for k,v in cnt.most_common(): print(f"  {k:<14}{v:>3} 個 ({v/len(cases)*100:.0f}%)")
