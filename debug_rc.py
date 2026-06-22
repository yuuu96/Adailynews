import json, numpy as np
from mootdx.quotes import Quotes
client = Quotes.factory(market="std", timeout=10)

LOOKBACK = 20

def get_klines(code):
    market = 1 if code.startswith(("6","9")) else 0
    df = client.bars(symbol=code, category=4, offset=LOOKBACK, market=market)
    if df is None or len(df) < 8: return None
    for c in ["open","close","high","low"]: df[c]=df[c].astype(float)
    return df

# test on a few tickers
for code in ["688017","600276","002129","300476"]:
    df = get_klines(code)
    if df is None: print(f"{code}: no data"); continue
    o,c,h,l = df["open"].values, df["close"].values, df["high"].values, df["low"].values
    n=len(c)
    highs,lows=[],[]
    for i in range(n):
        ref=max(o[i],c[i])
        if ref==0: highs.append(0); lows.append(0); continue
        u=(h[i]-ref)/c[i]*100; ll=(min(o[i],c[i])-l[i])/c[i]*100
        highs.append(u); lows.append(ll)
    cg=[0]*n; hs=[0]*n
    for i in range(n):
        if 4<=highs[i]<=10 and lows[i]<2: cg[i]=1
        if 4<=lows[i]<=10 and highs[i]<2: hs[i]=1
    zh=[0]*n
    for i in range(1,n): 
        if cg[i-1] and hs[i]: zh[i]=1
    has_zh=sum(zh[-7:])>=1
    ma7=np.mean(c[-7:]); slope=np.polyfit(np.arange(7),c[-7:],1)[0]
    trend = c[-1]>ma7 and slope>0
    n_cg=sum(cg); n_hs=sum(hs); n_zh=sum(zh)
    print(f"{code}: n={n} cg={n_cg} hs={n_hs} zh={n_zh} has_zh={has_zh} trend={trend} last={c[-1]:.2f} ma7={ma7:.2f} slope={slope:.4f}")
    if n_cg>0: 
        days=[i for i in range(n) if cg[i]]; print(f"  cg days: {days}")
        for d in days: print(f"    day{d}: O={o[d]:.2f} C={c[d]:.2f} H={h[d]:.2f} L={l[d]:.2f} upper={highs[d]:.2f} lower={lows[d]:.2f}")
    if n_hs>0:
        days=[i for i in range(n) if hs[i]]; print(f"  hs days: {days}")
        for d in days: print(f"    day{d}: O={o[d]:.2f} C={c[d]:.2f} H={h[d]:.2f} L={l[d]:.2f} upper={highs[d]:.2f} lower={lows[d]:.2f}")

