#!/usr/bin/env python3
"""Get industries for 74 stocks"""
import json, time, os
os.environ["no_proxy"] = "*"
os.environ["NO_PROXY"] = "*"
import akshare as ak

codes = [
"002129","601816","600698","000712","002585","002651","603111","600276","603776",
"601606","300427","301357","002387","603126","002608","600278","001207","300287",
"302132","002179","002112","002896","603386","600236","000837","002788","600550",
"300217","605580","605006","600819","600967","002265","600973","605255","300215",
"002975","603466","603738","603459","600734","600644","600353","600178","600545",
"000768","600184","300177","300968","300539","688545","601179","688332","002358",
"301007","300228","601566","688551","002038","000993","600839","600056","002396",
"600780","603757","603366","300252","000411","603033","002897","601858","000899",
"000722","300581"
]

industries = {}
for i, code in enumerate(codes):
    try:
        df = ak.stock_individual_info_em(symbol=code)
        row = df[df["item"]=="行业"]
        if len(row)>0:
            industries[code] = row["value"].values[0]
        else:
            industries[code] = "未知"
    except Exception as e:
        industries[code] = f"获取失败"
    if (i+1) % 10 == 0:
        print(f"  {i+1}/{len(codes)}")
    time.sleep(0.5)

with open("/tmp/a_industries.json","w") as f:
    json.dump(industries, f, ensure_ascii=False)
print("Done. Sorted by industry:")
from collections import Counter
cnt = Counter(industries.values())
for k, v in cnt.most_common():
    print(f"  {k}: {v}")

