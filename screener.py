#!/usr/bin/env python3
"""条件选股"""
import json, urllib.request, time, os
os.environ["no_proxy"] = "*"

CONDITIONS = {
    "总市值(亿)": (50, 8000),
    "量比": (2, 5),
    "涨跌幅%": (0, 7.2),
}

BATCH = 80
codes = json.load(open("/tmp/a_codes.json"))
print(f"Total: {len(codes)} codes, batch={BATCH}")


def get_prefix(code):
    if code.startswith(("6","9")): return "sh"
    elif code.startswith("8"): return "bj"
    return "sz"

def tencent_batch(codes_batch):
    prefixed = [f"{get_prefix(c)}{c}" for c in codes_batch]
    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0")
    resp = urllib.request.urlopen(req, timeout=15)
    data = resp.read().decode("gbk")
    results = {}
    for line in data.strip().split(";"):
        if "=" not in line or '"' not in line: continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53: continue
        code = key[2:]
        try:
            results[code] = {
                "name": vals[1],
                "price": float(vals[3]) if vals[3] else 0,
                "change_pct": float(vals[32]) if vals[32] else 0,
                "vol_ratio": float(vals[49]) if vals[49] else 0,
                "mcap_yi": float(vals[44]) if vals[44] else 0,
            }
        except: pass
    return results

all_matches = []
total = len(codes)
for i in range(0, total, BATCH):
    batch = codes[i:i+BATCH]
    try:
        quotes = tencent_batch(batch)
    except Exception as e:
        print(f"  Batch {i//BATCH+1} error: {e}")
        time.sleep(2)
        continue
    for code, q in quotes.items():
        if q["price"] == 0: continue
        mc = q["mcap_yi"]
        vr = q["vol_ratio"]
        cp = q["change_pct"]
        if not (50 <= mc <= 8000): continue
        if not (2 <= vr <= 5): continue
        if not (0 < cp <= 7.2): continue
        all_matches.append({
            "代码": code, "名称": q["name"], "现价": round(q["price"],2),
            "总市值(亿)": round(mc,1), "量比": round(vr,2),
            "涨跌幅%": round(cp,2),
        })
    if (i//BATCH+1) % 5 == 0:
        print(f"  Progress: {i+len(batch)}/{total}, matches so far: {len(all_matches)}")
    time.sleep(0.15)

import pandas as pd
df = pd.DataFrame(all_matches)
if len(df) > 0:
    df = df.sort_values("量比", ascending=False)
print(f"\n===== 筛选结果: {len(df)} 只 =====")
print(df.to_string(index=False))
