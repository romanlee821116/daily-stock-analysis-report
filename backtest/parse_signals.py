# -*- coding: utf-8 -*-
"""ETF daily reports -> stock x date signal panel. Header-driven, tolerant of 3+ template generations."""
import re, os, csv, glob, html as H

def strip(h): return re.sub(r'\s+',' ', re.sub(r'<[^>]*>',' ', H.unescape(h))).strip()
def num(x):
    m = re.search(r'-?\d+(?:\.\d+)?', strip(x).replace(',',''))
    return float(m.group(0)) if m else None

def sections(s):
    hs=list(re.finditer(r'<h2[^>]*>(.*?)</h2>', s, re.S)); out=[]
    for i,m in enumerate(hs):
        end=hs[i+1].start() if i+1<len(hs) else len(s)
        out.append((strip(m.group(1)), s[m.end():end]))
    return out

def tables(h): return re.findall(r'<table.*?</table>', h, re.S)
def trs(t):    return re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S)
def cells(tr): return re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, re.S)

def colmap(hdr):
    m={}
    for i,c in enumerate(hdr):
        t=strip(c)
        if   re.search(r'代號',t):            m['code']=i
        elif re.search(r'名稱',t):            m['name']=i
        elif re.search(r'個股',t):            m['codename']=i
        elif re.search(r'淨額|淨買賣超',t):    m['net']=i
        elif re.search(r'方向',t):            m['dir']=i
        elif re.search(r'買方',t):            m['buyers']=i
        elif re.search(r'賣方',t):            m['sellers']=i
        elif re.search(r'參與',t):            m['parts']=i
        elif re.search(r'檔數',t):            m['cnt']=i
        elif re.search(r'主題|族群',t):        m['theme']=i
    return m

rows=[]; perfile={}
files=sorted(f for f in glob.glob('reports/*.html')
             if re.fullmatch(r'\d{8}\.html', os.path.basename(f)))
for fp in files:
    d=os.path.basename(fp)[:8]; date=f"{d[:4]}-{d[4:6]}-{d[6:]}"
    s=open(fp,encoding='utf-8').read()
    s=re.sub(r'<!--.*?-->','',s,flags=re.S); s=re.sub(r'<style.*?</style>','',s,flags=re.S)
    n0=len(rows)
    for head, body in sections(s):
        is_cons = '多檔共識' in head
        is_rank = bool(re.search(r'個股(資金流|淨買)', head))
        if not (is_cons or is_rank): continue
        for tbl in tables(body):
            rr=trs(tbl)
            if not rr: continue
            hdr=cells(rr[0]); cm=colmap(hdr)
            if 'net' not in cm or not ('code' in cm or 'codename' in cm): continue
            for tr in rr[1:]:
                tds=cells(tr)
                if len(tds) < len(hdr)-1: continue
                def g(k):
                    i=cm.get(k)
                    return tds[i] if i is not None and i < len(tds) else ''
                if 'code' in cm:
                    mc=re.match(r'(\d{4})', strip(g('code')))
                    if not mc: continue
                    code=mc.group(1); name=strip(g('name'))
                else:
                    mc=re.match(r'(\d{4})\s*(.*)', strip(g('codename')))
                    if not mc: continue
                    code, name = mc.group(1), mc.group(2).strip()
                net=num(g('net'))
                if net is None: continue
                buyers=sellers=[]
                if 'buyers' in cm or 'sellers' in cm:
                    buyers =re.findall(r'\b00\d{3}A\b', g('buyers'))
                    sellers=re.findall(r'\b00\d{3}A\b', g('sellers'))
                elif 'parts' in cm:
                    p=re.findall(r'\b00\d{3}A\b', g('parts'))
                    direction=strip(g('dir'))
                    if '賣' in direction or net<0: buyers,sellers=[],p
                    else: buyers,sellers=p,[]
                nb,ns=len(buyers),len(sellers)
                if not (nb or ns):
                    mc2=re.search(r'(\d+)\s*/\s*(\d+)', strip(g('cnt')) or ' '.join(strip(t) for t in tds))
                    if mc2: nb,ns=int(mc2.group(1)),int(mc2.group(2))
                    elif 'cnt' in cm:
                        c=num(g('cnt')) or 0
                        if '賣' in strip(g('dir')) or net<0: ns=int(c)
                        else: nb=int(c)
                theme=strip(g('theme'))
                rows.append(dict(date=date, code=code, name=name, net_yi=net,
                                 n_buy=nb, n_sell=ns, theme=theme,
                                 buyers='|'.join(buyers), sellers='|'.join(sellers),
                                 src='consensus' if is_cons else 'rank'))
    perfile[date]=len(rows)-n0

best={}
for r in rows:
    k=(r['date'],r['code']); p=best.get(k)
    if p is None: best[k]=r; continue
    if r['src']=='consensus' and p['src']!='consensus':
        r['theme']=r['theme'] or p['theme']; best[k]=r
    else:
        if not p['theme'] and r['theme']: p['theme']=r['theme']
        if (r['n_buy']+r['n_sell'])>(p['n_buy']+p['n_sell']):
            p['n_buy'],p['n_sell']=r['n_buy'],r['n_sell']
            p['buyers'],p['sellers']=r['buyers'],r['sellers']

out=sorted(best.values(), key=lambda r:(r['date'], -abs(r['net_yi'])))
cols=['date','code','name','net_yi','n_buy','n_sell','theme','buyers','sellers','src']
with open('backtest/signal_panel.csv','w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore'); w.writeheader()
    for r in out: w.writerow(r)

days=sorted({r['date'] for r in out})
print(f"files parsed  : {len(files)}")
print(f"trading days  : {len(days)}  {days[0]} .. {days[-1]}")
print(f"panel rows    : {len(out)}")
print(f"distinct stks : {len({r['code'] for r in out})}")
print(f"with ETF lists: {sum(1 for r in out if r['buyers'] or r['sellers'])}")
empty=[d for d,n in sorted(perfile.items()) if n==0]
print("empty days    :", empty or "none")
