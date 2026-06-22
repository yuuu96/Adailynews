#!/usr/bin/env python3
"""下载指定开源证券研报PDF"""
import requests, time, re, os
from pathlib import Path

session = requests.Session()
session.proxies = {"http": None, "https": None}
session.trust_env = False
session.headers.update({"User-Agent":"Mozilla/5.0","Referer":"https://data.eastmoney.com/"})

API = "https://reportapi.eastmoney.com/report/list"
PDF_TPL = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"
TARGET = Path("./reports")
TARGET.mkdir(exist_ok=True)

# 搜索目标9篇
targets = [
    ("机器人", "机器人营收同比+687%"),
    ("机器人", "机器人业务从0到1突破"),
    ("机器人", "机器人/液冷新业务加速推进"),
    ("光模块", "光模块+AIPCB"),
    ("光模块", "AI算力基建驱动长期价值跃迁"),
    ("光模块", "算力×联接"),
    ("光模块", "内存互连全球龙头"),
    ("电子化学品", "大宗气/特气/现场制气"),
]

print("=== 搜索研报 ===")
for tup in targets:
    kw, title_key = tup[0], tup[1]
    for page in range(1, 4):
        params = {"industryCode":"*","pageSize":"30","industry":"*","rating":"*",
                  "ratingChange":"*","beginTime":"2026-04-01","endTime":"2030-01-01",
                  "pageNo":str(page),"fields":"","qType":"0",
                  "orgCode":"80000162","code":"","rcode":""}
        r = session.get(API, params=params, timeout=15)
        d = r.json()
        rows = d.get("data") or []
        if not rows: break
        for row in rows:
            title = row.get("title","")
            if title_key in title:
                ic = row.get("infoCode","")
                date = (row.get("publishDate","") or "")[:10]
                org = row.get("orgSName","")
                fn = re.sub(r'[\\/:*?"<>|]', "_", title)[:80]
                fname = f"{date}_{org}_{fn}.pdf"
                fp = TARGET / fname
                if fp.exists():
                    print(f"  EXISTS: {fname}")
                    continue
                url = PDF_TPL.format(info_code=ic)
                r2 = session.get(url, headers={"User-Agent":"Mozilla/5.0","Referer":"https://data.eastmoney.com/"}, timeout=60)
                if r2.status_code==200 and len(r2.content)>=1024:
                    fp.write_bytes(r2.content)
                    print(f"  DONE: {fname} ({len(r2.content)} bytes)")
                else:
                    print(f"  FAIL: {fname} status={r2.status_code}")
                time.sleep(0.5)
        time.sleep(0.3)
print("\n=== 完成 ===")
import os
for f in sorted(TARGET.iterdir()):
    print(f"  {f.name}")
