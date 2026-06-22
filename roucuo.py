#!/usr/bin/env python3
"""揉搓线选股 — 通达信指标转Python"""
import json, time, sys, numpy as np
from mootdx.quotes import Quotes

client = Quotes.factory(market="std", timeout=10)
codes = json.load(open("/tmp/a_codes.json"))
print(f"全A股票: {len(codes)} 只")

LOOKBACK = 20

def get_klines(code):
    market = 1 if code.startswith(("6","9")) else 0
    try:
        df = client.bars(symbol=int(code), category=4, offset=LOOKBACK, market=market)
    except:
        return None
    if df is None or len(df) < 8:
        return None
    cols = ["open","close","high","low"]
    for c in cols:
        df[c] = df[c].astype(float)
    return df

def check_stock(code):
    df = get_klines(code)
    if df is None:
        return None
    o, c, h, l = df["open"].values, df["close"].values, df["high"].values, df["low"].values
    n = len(c)
    if n < 8:
        return None
    # 计算每日形态
    highs = []
    lows = []
    for i in range(n):
        ref = max(o[i], c[i])
        if ref == 0:
            highs.append(0); lows.append(0); continue
        upper = (h[i] - ref) / c[i] * 100
        lower = (min(o[i], c[i]) - l[i]) / c[i] * 100
        highs.append(upper); lows.append(lower)
    # 冲高: 上影>=4 <=10 且下影<2
    chonggao = [0]*n
    for i in range(n):
        if 4 <= highs[i] <= 10 and lows[i] < 2:
            chonggao[i] = 1
    # 回升: 下影>=4 <=10 且上影<2
    huisheng = [0]*n
    for i in range(n):
        if 4 <= lows[i] <= 10 and highs[i] < 2:
            huisheng[i] = 1
    # 组合形态: REF(冲高,1) AND 回升
    zuhe = [0]*n
    for i in range(1, n):
        if chonggao[i-1] == 1 and huisheng[i] == 1:
            zuhe[i] = 1
    # 7日内有组合
    has_zuhe = sum(zuhe[-7:]) >= 1
    if not has_zuhe:
        return None
    # 趋势: CLOSE > MA(CLOSE,7) AND SLOPE(CLOSE,7) > 0
    ma7 = np.mean(c[-7:])
    if c[-1] <= ma7:
        return None
    if len(c) >= 8:
        x = np.arange(7)
        y = c[-7:]
        slope = np.polyfit(x, y, 1)[0]
        if slope <= 0:
            return None
    # 找到最近一次组合形态日
    last_zuhe_day = -1
    for i in range(n-1, n-8, -1):
        if zuhe[i] == 1:
            last_zuhe_day = i
            break
    return {
        "code": code,
        "last_price": round(float(c[-1]), 2),
        "ma7": round(float(ma7), 2),
        "slope": round(float(slope), 4),
        "combo_day": last_zuhe_day,
        "chonggao_price": round(float(c[last_zuhe_day-1]), 2),
        "huisheng_price": round(float(c[last_zuhe_day]), 2),
    }


results = []
for i, code in enumerate(codes):
    try:
        r = check_stock(code)
        if r:
            results.append(r)
    except:
        pass
    if (i+1) % 500 == 0:
        print(f"  {i+1}/{len(codes)}, 命中: {len(results)}")
    time.sleep(0.02)

print(f"\n{'='*60}")
print(f"揉搓线选股结果: {len(results)} 只")
print(f"{'='*60}")

if results:
    results.sort(key=lambda x: x["slope"], reverse=True)
    for i, r in enumerate(results):
        print(f"\n{i+1}. {r['code']}  现价={r['last_price']}  MA7={r['ma7']}  斜率={r['slope']:.4f}")
        print(f"   组合形态日: 冲高收盘{r['chonggao_price']} → 探底收盘{r['huisheng_price']}")
else:
    print("无符合条件个股")

import pandas as pd
df = pd.DataFrame(results)
print("\n\n汇总表:")
print(df.to_string(index=False))

with open("/tmp/roucuo_result.json","w") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
