#!/usr/bin/env python3
"""彤程新材603650大宗交易每日监控"""
import os; os.environ["no_proxy"]="*"; os.environ["NO_PROXY"]="*"
import akshare as ak
from datetime import date
today = date.today().strftime("%Y%m%d")
df = ak.stock_dzjy_mrmx(symbol="A股", start_date=today, end_date=today)
if df is None or len(df)==0:
    print(f"{today} 无大宗数据")
else:
    m = df[df['证券代码']=='603650']
    if len(m)==0:
        print(f"{today} 彤程新材 无大宗")
    else:
        total_vol = int(m['成交量'].sum())
        total_amt = m['成交额'].sum()/1e4
        close = m['收盘价'].iloc[0]
        trade = m['成交价'].iloc[0]
        disc = m['折溢率'].iloc[0]*100
        sellers = list(m['卖方营业部'].unique())
        inst = m[m['买方营业部']=='机构专用']
        inst_vol = int(inst['成交量'].sum()) if len(inst)>0 else 0
        print(f"{today} 彤程新材 {len(m)}笔  共{total_vol}股  总额{total_amt:.0f}万")
        print(f"  收盘{close}  成交{trade}  折溢率{disc:.2f}%")
        print(f"  卖方: {sellers}")
        if inst_vol>0:
            print(f"  机构接货: {inst_vol}股")
