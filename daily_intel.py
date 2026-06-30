#!/usr/bin/env python3
"""Daily A-share intelligence collector and DeepSeek summarizer.

The script is intentionally defensive: every data source is optional, and a
failed source is surfaced in the report instead of aborting the whole run.
"""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import os
import re
import signal
import time
import traceback
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import requests

try:
    import akshare as ak
except Exception:  # pragma: no cover - handled at runtime
    ak = None

try:
    import pandas as pd
except Exception:  # pragma: no cover - handled at runtime
    pd = None


ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "reports" / "daily"
LATEST_JSON = REPORT_DIR / "latest.json"
LATEST_MD = REPORT_DIR / "latest.md"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
CN_TZ = ZoneInfo("Asia/Shanghai")
THEME_KEYWORDS = [
    "宁德",
    "宁德时代",
    "CATL",
    "英伟达",
    "NVIDIA",
    "GB200",
    "GB300",
    "Rubin",
    "AI",
    "算力",
    "CPO",
    "光模块",
    "液冷",
    "HBM",
    "半导体",
    "光刻胶",
    "电子特气",
    "硅片",
    "InP",
    "GaAs",
    "CMP",
    "ABF",
    "涨价",
    "断供",
    "储能",
    "锂矿",
    "碳酸锂",
    "锂电",
    "氦气",
    "氦",
    "VC",
    "电解液",
    "六氟磷酸锂",
    "六氟化钨",
    "磷化铟",
    "铋",
    "锑",
    "氮化镓",
    "铟",
    "氧化锆",
    "光刻胶",
    "石英砂",
    "钨",
    "锆",
    "铜",
    "银",
]

SOURCE_TIMEOUTS = {
    "同花顺热点": 15,
    "北向资金": 15,
    "涨停池": 25,
    "材料雷达": 45,
    "金属快讯": 15,
    "财联社快讯": 9,
    "产业新闻": 15,
    "重点公告": 18,
    "机构研报": 35,
    "期指席位": 45,
    "产业链行情": 30,
}

SOURCE_DEFS: list[tuple[str, Callable[[], Any]]] = []

WATCHLIST = {
    "英伟达/AI算力": ["300502", "300308", "300394", "300476", "002463", "688256", "688041"],
    "半导体材料": ["688300", "300054", "688126", "603650", "002409", "688146", "600703", "002549", "600360"],
    "储能锂矿": ["300750", "002466", "002460", "002738", "002756", "300274", "002812"],
    "电网电力": ["601179", "600550", "600973", "002498", "002560", "600236", "000899"],
}

FOCUS_TOPICS = {
    "宁德相关": ["宁德", "宁德时代", "CATL", "电池", "储能", "麒麟电池", "神行电池"],
    "美股科技": ["英伟达", "NVIDIA", "GB200", "GB300", "Rubin", "Blackwell", "NVL", "CUDA", "Apple", "Microsoft", "Alphabet", "Amazon", "Meta", "Tesla"],
    "韩股科技": ["SK Hynix", "SK海力士", "海力士", "三星", "Samsung", "HBM", "DRAM", "NAND", "存储", "AI内存", "晶圆代工"],
    "半导体上游材料": ["半导体", "光刻胶", "电子特气", "氦气", "氦", "硅片", "CMP", "ABF", "InP", "GaAs", "前驱体"],
    "亿纬锂能": ["亿纬锂能", "半年报", "业绩预告", "电池", "储能"],
}

FOCUS_EVENT_GROUPS = {
    "宁德时代": ["宁德", "宁德时代", "CATL", "枧下窝", "锂矿", "复产", "储能", "电池"],
    "美股科技": ["NVIDIA", "英伟达", "Rubin", "45摄氏度", "液冷", "GB200", "GB300", "Blackwell", "苹果", "Apple", "AAPL", "微软", "Microsoft", "MSFT", "谷歌", "Alphabet", "GOOGL", "亚马逊", "Amazon", "AMZN", "NVDA", "Meta", "META", "特斯拉", "Tesla", "TSLA", "财报", "业绩", "指引", "资本开支"],
    "韩股科技": ["SK Hynix", "SK海力士", "海力士", "三星", "Samsung", "HBM", "DRAM", "NAND", "存储", "先进封装", "AI内存", "AI 内存", "晶圆代工", "Foundry"],
    "半导体上游材料": ["日本酸素", "氦气", "氦", "光刻胶", "电子特气", "断供", "涨价", "六氟化钨"],
    "亿纬锂能": ["亿纬锂能", "半年报", "业绩预告", "电池", "储能"],
    "美国宏观与美联储": ["美国", "美联储", "Fed", "FOMC", "降息", "加息", "利率", "CPI", "PCE", "非农", "失业率", "初请", "ISM", "GDP", "美债", "美元"],
}

FOCUS_EVENT_ANCHORS = {
    "宁德时代": ["宁德", "宁德时代", "CATL", "枧下窝"],
    "美股科技": ["NVIDIA", "英伟达", "Rubin", "GB200", "GB300", "Blackwell", "苹果", "Apple", "AAPL", "微软", "Microsoft", "MSFT", "谷歌", "Alphabet", "GOOGL", "亚马逊", "Amazon", "AMZN", "NVDA", "Meta", "META", "特斯拉", "Tesla", "TSLA"],
    "韩股科技": ["SK Hynix", "SK海力士", "海力士", "三星", "Samsung", "HBM", "DRAM", "NAND"],
    "半导体上游材料": ["日本酸素", "氦气", "氦", "光刻胶", "电子特气", "六氟化钨"],
    "亿纬锂能": ["亿纬", "亿纬锂能", "EVE"],
    "美国宏观与美联储": ["美国", "美联储", "Fed", "FOMC", "CPI", "PCE", "非农", "失业率", "初请", "ISM", "GDP", "美债"],
}

FOREIGN_ORG_KEYWORDS = [
    "高盛",
    "Goldman",
    "摩根士丹利",
    "Morgan Stanley",
    "摩根大通",
    "JPMorgan",
    "JP Morgan",
    "瑞银",
    "UBS",
    "花旗",
    "Citi",
    "Citigroup",
    "野村",
    "Nomura",
    "麦格理",
    "Macquarie",
    "美银",
    "BofA",
    "Bank of America",
]

FOCUS_STOCKS = {
    "300750": "宁德时代",
    "300014": "亿纬锂能",
}

TRACKED_ANALYSTS = [
    {"sector": "传媒", "broker": "广发", "aliases": ["旷石", "钻石"]},
    {"sector": "医药", "broker": "中信建投", "aliases": ["贺菊颖"]},
    {"sector": "医药", "broker": "兴业证券", "aliases": ["孙媛媛"]},
    {"sector": "金属新材料", "broker": "长江", "aliases": ["王鹤涛"]},
    {"sector": "金属新材料", "broker": "民生", "aliases": ["邱祖学"]},
    {"sector": "金属新材料", "broker": "中信", "aliases": ["王介超"]},
    {"sector": "金属新材料", "broker": "国君", "aliases": ["李鹏飞"]},
    {"sector": "电子", "broker": "广发", "aliases": ["耿正"]},
    {"sector": "电子", "broker": "中信建投", "aliases": ["刘双锋"]},
    {"sector": "新能源与电力设备", "broker": "长江", "aliases": ["邬博花"]},
    {"sector": "新能源与电力设备", "broker": "东吴", "aliases": ["曾朵红"]},
    {"sector": "能源", "broker": "广发", "aliases": ["果鹏"]},
    {"sector": "轻工造纸", "broker": "申万", "aliases": ["周海晨"]},
]

BROKER_ALIAS_MAP = {
    "广发": ["广发", "广发证券"],
    "中信建投": ["中信建投", "中信建投证券"],
    "兴业证券": ["兴业", "兴业证券"],
    "长江": ["长江", "长江证券"],
    "民生": ["民生", "民生证券"],
    "中信": ["中信", "中信证券"],
    "国君": ["国君", "国泰君安"],
    "东吴": ["东吴", "东吴证券"],
    "申万": ["申万", "申万宏源"],
}

MATERIAL_SIGNAL_WORDS = [
    "涨价",
    "断供",
    "紧缺",
    "库存低",
    "库存低位",
    "出口管制",
    "限制出口",
    "停产",
    "检修",
    "供需缺口",
    "供给收缩",
    "价格上行",
    "进口受限",
]

MATERIAL_CONFIG = [
    {
        "name": "碳酸锂",
        "category": "锂电材料",
        "keywords": ["碳酸锂", "锂盐", "锂矿"],
        "futures_symbol": "碳酸锂",
        "inventory_symbol": "碳酸锂",
        "unit": "元/吨",
        "tightness": "中性偏紧",
        "expansion": "中等：资源、盐湖/矿山和爬坡周期约束较强",
        "related_codes": ["002466", "002460", "300750", "002756", "002192", "002240", "002176", "000762", "603399", "000792"],
    },
    {
        "name": "VC电解液",
        "category": "锂电添加剂",
        "keywords": ["VC", "电解液", "添加剂", "碳酸亚乙烯酯"],
        "tightness": "跟随电解液需求和装置开工变化",
        "expansion": "中等：化工合成壁垒不极高，但客户认证和环保约束重要",
        "related_codes": ["002709", "300037", "300073", "002407", "688353"],
    },
    {
        "name": "六氟磷酸锂",
        "category": "锂电电解质",
        "keywords": ["六氟磷酸锂", "LiPF6", "电解质", "六氟"],
        "tightness": "周期弹性高，需跟踪价格和库存拐点",
        "expansion": "中等偏难：氟化工、安全环保和客户认证影响扩产",
        "related_codes": ["002709", "002407", "002326", "300037", "002759"],
    },
    {
        "name": "氦气",
        "category": "电子特气/稀有气体",
        "keywords": ["氦气", "氦", "Helium"],
        "tightness": "偏紧：海外气源、LNG副产和运输约束明显",
        "expansion": "难：资源禀赋决定供给，新增产能周期长",
        "related_codes": ["603318", "002549", "688146", "688267", "688268", "002971", "688106"],
    },
    {
        "name": "六氟化钨",
        "category": "半导体前驱体",
        "keywords": ["六氟化钨", "WF6", "钨前驱体", "钨"],
        "tightness": "需跟踪先进制程和存储扩产需求",
        "expansion": "难：高纯工艺、客户认证和安全环保门槛高",
        "related_codes": ["688146", "688268", "002409", "600360", "600378", "688549"],
    },
    {
        "name": "磷化铟",
        "category": "化合物半导体",
        "keywords": ["磷化铟", "InP", "铟磷"],
        "tightness": "偏紧：受光通信和射频需求拉动",
        "expansion": "难：晶体生长、衬底良率和认证周期长",
        "related_codes": ["002428", "600141", "600206"],
    },
    {
        "name": "小金属综合",
        "category": "小金属/半导体材料",
        "keywords": ["铋", "金属铋", "秘", "锑", "锑矿", "三氧化二锑", "铟", "金属铟", "ITO", "氧化锆", "锆", "锆英砂"],
        "tightness": "关注出口管制、伴生资源和小金属库存变化",
        "expansion": "中等偏难：多为伴生资源，新增供给弹性有限",
        "related_codes": ["600497", "000960", "600531", "600301", "002155", "000060", "000878", "600362", "002167", "002149", "300224"],
    },
    {
        "name": "光刻胶",
        "category": "半导体材料",
        "keywords": ["光刻胶", "日本光刻胶", "KrF", "ArF", "EUV"],
        "tightness": "高端品类偏紧，海外供应扰动敏感",
        "expansion": "难：配方、验证、客户导入和稳定性门槛高",
        "related_codes": ["603650", "300054", "688199", "300576", "300346", "002643"],
    },
    {
        "name": "半导体硅片",
        "category": "半导体材料",
        "keywords": ["半导体硅片", "硅片", "硅材料", "大硅片", "抛光片", "外延片"],
        "tightness": "关注存储和先进制程扩产带来的硅片需求变化",
        "expansion": "难：晶体生长、良率、客户认证和产线爬坡周期较长",
        "related_codes": ["688126", "605358", "002129", "688233", "688432"],
    },
    {
        "name": "其它",
        "category": "第三代半导体/耗材",
        "keywords": ["氮化镓", "GaN", "第三代半导体", "石英砂", "高纯石英", "石英坩埚"],
        "tightness": "结构性偏紧：高端衬底、外延和高纯耗材更关键",
        "expansion": "难：工艺、矿源品质、良率和客户认证周期约束明显",
        "related_codes": ["600703", "688234", "300373", "300102", "603688", "300395", "600293"],
    },
]

POSITIVE_WORDS = [
    "上调",
    "买入",
    "增持",
    "超预期",
    "景气",
    "涨价",
    "供需缺口",
    "国产替代",
    "订单",
    "突破",
    "加速",
    "高增",
]
NEGATIVE_WORDS = [
    "下调",
    "减持",
    "低于预期",
    "承压",
    "库存",
    "价格下跌",
    "需求疲弱",
    "制裁",
    "断供风险",
    "亏损",
]


@dataclass
class SourceResult:
    name: str
    ok: bool
    data: Any
    error: str | None = None
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
        }


def ensure_env() -> None:
    os.environ.setdefault("no_proxy", "*")
    os.environ.setdefault("NO_PROXY", "*")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)


def _source_worker(fn: Callable[[], Any], queue: mp.Queue) -> None:
    try:
        queue.put({"ok": True, "data": jsonable(fn())})
    except Exception as exc:
        queue.put({"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"})


def run_source(name: str, fn: Callable[[], Any], timeout_s: int | None = None) -> SourceResult:
    started = time.time()
    timeout_s = timeout_s or SOURCE_TIMEOUTS.get(name, 20)
    ctx = mp.get_context("spawn")
    queue: mp.Queue = ctx.Queue(maxsize=1)
    proc = ctx.Process(target=_source_worker, args=(fn, queue), daemon=True)
    proc.start()
    proc.join(timeout_s)
    elapsed_ms = int((time.time() - started) * 1000)
    if proc.is_alive():
        proc.terminate()
        proc.join(2)
        return SourceResult(
            name,
            False,
            None,
            error=f"TimeoutError: 数据源超过 {timeout_s}s 未返回，已跳过",
            elapsed_ms=elapsed_ms,
        )
    try:
        payload = queue.get_nowait()
    except Exception:
        if proc.exitcode == 0:
            return SourceResult(name, True, None, elapsed_ms=elapsed_ms)
        return SourceResult(name, False, None, error=f"ProcessError: exitcode={proc.exitcode}", elapsed_ms=elapsed_ms)
    if payload.get("ok"):
        return SourceResult(name, True, payload.get("data"), elapsed_ms=elapsed_ms)
    return SourceResult(name, False, None, error=payload.get("error"), elapsed_ms=elapsed_ms)


def jsonable(value: Any) -> Any:
    if pd is not None and hasattr(value, "to_dict"):
        return value.to_dict(orient="records")
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "-"):
            return default
        return float(value)
    except Exception:
        return default


def now_cn() -> datetime:
    return datetime.now(CN_TZ)


def now_cn_naive() -> datetime:
    return now_cn().replace(tzinfo=None)


def today_cn() -> date:
    return now_cn().date()


def closed_daily_cutoff(now: datetime | None = None) -> date:
    current = now or now_cn()
    cutoff = current.date()
    if current.hour < 15 or (current.hour == 15 and current.minute < 10):
        cutoff -= timedelta(days=1)
    return cutoff


def trend_label(change_pct: float | None) -> str:
    value = safe_float(change_pct, 0)
    if value >= 3:
        return "明显上行"
    if value > 0:
        return "小幅上行"
    if value <= -3:
        return "明显回落"
    if value < 0:
        return "小幅回落"
    return "持平/暂无变化"


def call_with_alarm(fn: Callable[[], Any], timeout_s: int, label: str) -> Any:
    if not hasattr(signal, "SIGALRM"):
        return fn()

    def _handler(signum: int, frame: Any) -> None:
        raise TimeoutError(f"{label} 超过 {timeout_s}s 未返回")

    previous = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _handler)
    signal.alarm(timeout_s)
    try:
        return fn()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def get_prefix(code: str) -> str:
    if code.startswith(("6", "9")):
        return "sh"
    if code.startswith(("8", "920")):
        return "bj"
    return "sz"


def tencent_quote(codes: list[str]) -> dict[str, dict[str, Any]]:
    if not codes:
        return {}
    prefixed = [f"{get_prefix(code)}{code}" for code in codes]
    url = "http://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://finance.qq.com/"})
    data = urllib.request.urlopen(req, timeout=15).read().decode("gbk", errors="ignore")
    result: dict[str, dict[str, Any]] = {}
    for line in data.strip().split(";"):
        if "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53 or not vals[1]:
            continue
        code = key[2:]
        result[code] = {
            "code": code,
            "name": vals[1],
            "price": safe_float(vals[3]),
            "change_pct": safe_float(vals[32]),
            "amount_yi": round(safe_float(vals[37]) / 10000, 2),
            "turnover_pct": safe_float(vals[38]),
            "pe_ttm": safe_float(vals[39]),
            "mcap_yi": safe_float(vals[44]),
            "float_mcap_yi": safe_float(vals[45]),
            "pb": safe_float(vals[46]),
            "vol_ratio": safe_float(vals[49]),
        }
    return result


def fetch_tencent_daily_close(code: str, cutoff: date) -> dict[str, Any] | None:
    prefixed = f"{get_prefix(code)}{code}"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefixed},day,,,8,qfq"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://gu.qq.com/"})
    payload = json.loads(urllib.request.urlopen(req, timeout=8).read().decode("utf-8", errors="ignore"))
    node = (payload.get("data") or {}).get(prefixed) or {}
    rows = node.get("qfqday") or []
    closed_rows = [row for row in rows if row and str(row[0]) <= cutoff.isoformat()]
    if len(closed_rows) < 2:
        return None
    latest = closed_rows[-1]
    previous = closed_rows[-2]
    close_price = safe_float(latest[2])
    previous_close = safe_float(previous[2])
    if not close_price or not previous_close:
        return None
    return {
        "price": close_price,
        "change_pct": round((close_price / previous_close - 1) * 100, 2),
        "quote_date": str(latest[0])[:10],
        "quote_source": "腾讯日线收盘",
    }


def collect_tencent_daily_close_overrides(codes: list[str], max_seconds: int = 12) -> dict[str, dict[str, Any]]:
    if not codes:
        return {}
    cutoff = closed_daily_cutoff()
    overrides: dict[str, dict[str, Any]] = {}
    executor = ThreadPoolExecutor(max_workers=min(8, len(codes)))
    futures = {executor.submit(fetch_tencent_daily_close, code, cutoff): code for code in codes}
    try:
        for future in as_completed(futures, timeout=max_seconds):
            code = futures[future]
            try:
                value = future.result()
                if value:
                    overrides[code] = value
            except Exception:
                continue
    except FuturesTimeout:
        pass
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return overrides


def collect_akshare_daily_close_overrides(codes: list[str], max_seconds: int = 12) -> dict[str, dict[str, Any]]:
    if ak is None or not codes:
        return {}
    cutoff = closed_daily_cutoff()
    start = (cutoff - timedelta(days=20)).strftime("%Y%m%d")
    end = cutoff.strftime("%Y%m%d")
    deadline = time.monotonic() + max_seconds
    overrides: dict[str, dict[str, Any]] = {}
    for code in codes:
        if time.monotonic() >= deadline:
            break
        try:
            df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start, end_date=end, adjust="")
            rows = jsonable(df) or []
            closed_rows = []
            for row in rows:
                row_date = str(row.get("日期") or row.get("date") or "")[:10]
                if row_date and row_date <= cutoff.isoformat():
                    closed_rows.append(row)
            if not closed_rows:
                continue
            latest = closed_rows[-1]
            previous = closed_rows[-2] if len(closed_rows) >= 2 else None
            close_price = safe_float(latest.get("收盘"))
            change_pct = latest.get("涨跌幅")
            if change_pct in (None, "", "-") and previous:
                previous_close = safe_float(previous.get("收盘"))
                if previous_close:
                    change_pct = round((close_price / previous_close - 1) * 100, 2)
            overrides[code] = {
                "price": close_price,
                "change_pct": safe_float(change_pct),
                "amount_yi": round(safe_float(latest.get("成交额")) / 1e8, 2),
                "turnover_pct": safe_float(latest.get("换手率")),
                "quote_date": str(latest.get("日期") or "")[:10],
                "quote_source": "akshare日线收盘",
            }
        except Exception:
            continue
    return overrides


def collect_daily_close_overrides(codes: list[str], max_seconds: int = 12) -> dict[str, dict[str, Any]]:
    if not codes:
        return {}
    started = time.monotonic()
    overrides = collect_tencent_daily_close_overrides(codes, max_seconds=max(2, int(max_seconds * 0.7)))
    missing = [code for code in codes if code not in overrides]
    remaining = max_seconds - int(time.monotonic() - started)
    if missing and remaining > 2:
        overrides.update(collect_akshare_daily_close_overrides(missing, max_seconds=remaining))
    return overrides


def apply_daily_close_overrides(quotes: dict[str, dict[str, Any]], max_seconds: int = 12) -> dict[str, dict[str, Any]]:
    if not quotes:
        return quotes
    overrides = collect_daily_close_overrides(sorted(quotes), max_seconds=max_seconds)
    for code, quote in quotes.items():
        override = overrides.get(code)
        if override:
            quote.update({k: v for k, v in override.items() if v not in (None, "")})
        else:
            quote.setdefault("quote_source", "腾讯实时行情")
    return quotes


def collect_watchlist_quotes() -> dict[str, list[dict[str, Any]]]:
    all_codes: list[str] = []
    for codes in WATCHLIST.values():
        all_codes.extend(codes)
    quotes = apply_daily_close_overrides(tencent_quote(sorted(set(all_codes))), max_seconds=10)
    grouped = {}
    for theme, codes in WATCHLIST.items():
        grouped[theme] = [quotes[code] for code in codes if code in quotes]
        grouped[theme].sort(key=lambda item: item.get("amount_yi", 0), reverse=True)
    return grouped


def collect_ths_hot() -> dict[str, Any]:
    today = today_cn().strftime("%Y-%m-%d")
    url = f"http://zx.10jqka.com.cn/event/api/getharden/date/{today}/orderby/date/orderway/desc/charset/GBK/"
    r = requests.get(url, headers={"User-Agent": UA}, timeout=12)
    r.raise_for_status()
    payload = r.json()
    if payload.get("errocode", 0) != 0:
        raise RuntimeError(payload.get("errormsg") or "ths hot API error")
    rows = payload.get("data") or []
    top = []
    tags: list[str] = []
    for row in rows:
        reason = row.get("reason") or ""
        tags.extend([tag.strip() for tag in str(reason).split("+") if tag.strip()])
        top.append(
            {
                "code": row.get("code"),
                "name": row.get("name"),
                "change_pct": safe_float(row.get("zhangfu")),
                "turnover_pct": safe_float(row.get("huanshou")),
                "reason": reason,
            }
        )
    top.sort(key=lambda item: item.get("change_pct", 0), reverse=True)
    return {"date": today, "count": len(rows), "top": top[:30], "tag_top": Counter(tags).most_common(20)}


def collect_northbound() -> dict[str, Any]:
    headers = {"User-Agent": UA, "Host": "data.hexin.cn", "Referer": "https://data.hexin.cn/"}
    r = requests.get("https://data.hexin.cn/market/hsgtApi/method/dayChart/", headers=headers, timeout=12)
    r.raise_for_status()
    payload = r.json()
    times = payload.get("time") or []
    hgt = payload.get("hgt") or []
    sgt = payload.get("sgt") or []
    last_hgt = next((x for x in reversed(hgt) if x not in (None, "")), None)
    last_sgt = next((x for x in reversed(sgt) if x not in (None, "")), None)
    return {
        "points": len(times),
        "last_time": times[-1] if times else None,
        "hgt_yi": safe_float(last_hgt, 0),
        "sgt_yi": safe_float(last_sgt, 0),
        "total_yi": round(safe_float(last_hgt, 0) + safe_float(last_sgt, 0), 2),
    }


def collect_limit_up() -> dict[str, Any]:
    if ak is None:
        raise RuntimeError("akshare is not installed")
    d = today_cn().strftime("%Y%m%d")
    df = ak.stock_zt_pool_em(date=d)
    rows = jsonable(df) or []
    industry_counter: Counter[str] = Counter()
    cleaned = []
    one_word_boards = []
    for row in rows:
        name = row.get("名称")
        if not name or safe_float(row.get("最新价")) <= 0:
            continue
        industry = row.get("所属行业") or "未分类"
        first_time = str(row.get("首次封板时间") or "")
        last_time = str(row.get("最后封板时间") or "")
        break_count = int(safe_float(row.get("炸板次数"), 0))
        is_one_word = first_time == "092500" and last_time == "092500" and break_count == 0
        industry_counter[industry] += 1
        item = {
            "code": row.get("代码"),
            "name": name,
            "change_pct": safe_float(row.get("涨跌幅")),
            "latest": safe_float(row.get("最新价")),
            "amount_yi": round(safe_float(row.get("成交额")) / 1e8, 2),
            "board_count": row.get("连板数"),
            "industry": industry,
            "first_time": first_time,
            "last_time": last_time,
            "break_count": break_count,
            "is_one_word_board": is_one_word,
        }
        cleaned.append(item)
        if is_one_word:
            one_word_boards.append(item)
    cleaned.sort(key=lambda item: item.get("amount_yi", 0), reverse=True)
    top_limitup_industries = []
    for industry, count in industry_counter.most_common(3):
        stocks = [item for item in cleaned if item.get("industry") == industry]
        stocks.sort(
            key=lambda item: (
                1 if item.get("is_one_word_board") else 0,
                safe_float(item.get("board_count"), 0),
                item.get("amount_yi", 0),
            ),
            reverse=True,
        )
        top_limitup_industries.append(
            {
                "name": industry,
                "count": count,
                "stocks": [
                    {
                        "code": item.get("code"),
                        "name": item.get("name"),
                        "board_count": item.get("board_count"),
                        "amount_yi": item.get("amount_yi"),
                        "first_time": item.get("first_time"),
                        "is_one_word_board": item.get("is_one_word_board"),
                    }
                    for item in stocks[:20]
                ],
            }
        )
    return {
        "date": d,
        "count": len(cleaned),
        "industry_top": industry_counter.most_common(15),
        "top_limitup_industries": top_limitup_industries,
        "one_word_count": len(one_word_boards),
        "one_word_boards": one_word_boards[:40],
        "top": cleaned[:40],
    }


def text_from_record(record: dict[str, Any]) -> str:
    return " ".join(str(v) for v in record.values() if v is not None)


def is_theme_hit(text: str) -> bool:
    text_upper = text.upper()
    return any(keyword.upper() in text_upper for keyword in THEME_KEYWORDS)


def is_keyword_hit(text: str, keywords: list[str]) -> bool:
    upper = str(text or "").upper()
    return any(str(keyword).upper() in upper for keyword in keywords)


def first_value(record: dict[str, Any], candidates: list[str]) -> Any:
    for candidate in candidates:
        for key, value in record.items():
            if candidate.lower() in str(key).lower() and value not in (None, ""):
                return value
    return None


def parse_datetime_value(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("T", " ").replace("Z", "")
    text = re.sub(r"\+\d{2}:\d{2}$", "", text)
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"]:
        try:
            return datetime.strptime(text[: len(now_cn_naive().strftime(fmt))], fmt)
        except Exception:
            pass
    match = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", text)
    if match:
        year, month, day = (int(x) for x in match.groups())
        return datetime(year, month, day)
    return None


def is_recent_time(value: Any, hours: int = 48) -> bool:
    dt = parse_datetime_value(value)
    if dt is None:
        return False
    return dt >= now_cn_naive() - timedelta(hours=hours)


def normalize_news_item(source: str, row: dict[str, Any]) -> dict[str, Any]:
    title = first_value(row, ["标题", "title", "新闻标题"]) or ""
    content = first_value(row, ["内容", "摘要", "新闻内容", "content", "summary"]) or ""
    time_value = first_value(row, ["发布时间", "发布日期", "时间", "date", "time"])
    link = first_value(row, ["链接", "新闻链接", "url", "link"])
    text = " ".join(str(v) for v in [title, content] if v)
    if not text:
        text = text_from_record(row)
    return {
        "source": source,
        "title": str(title or text)[:180],
        "content": str(content or "")[:500],
        "text": str(text or "")[:700],
        "time": str(time_value or ""),
        "link": str(link or "") or None,
        "raw": row,
    }


def news_sort_key(item: dict[str, Any]) -> int:
    dt = parse_datetime_value(item.get("time") or item.get("date"))
    return int(dt.timestamp()) if dt else 0


def is_foreign_org_hit(text: str) -> bool:
    return is_keyword_hit(text, FOREIGN_ORG_KEYWORDS)


def is_focus_event_hit(group: str, text: str) -> bool:
    anchors = FOCUS_EVENT_ANCHORS.get(group, [])
    keywords = FOCUS_EVENT_GROUPS.get(group, [])
    if not is_keyword_hit(text, anchors):
        return False
    return is_keyword_hit(text, keywords)


def collect_news() -> dict[str, Any]:
    if ak is None:
        raise RuntimeError("akshare is not installed")
    items = []
    focus: dict[str, list[dict[str, Any]]] = {topic: [] for topic in FOCUS_TOPICS}
    try:
        df = ak.stock_info_global_em()
        for row in (jsonable(df) or [])[:160]:
            item = normalize_news_item("东财快讯", row)
            if is_theme_hit(item["text"]) or is_foreign_org_hit(item["text"]) or any(is_keyword_hit(item["text"], keywords) for keywords in FOCUS_EVENT_GROUPS.values()):
                items.append(item)
                for topic, keywords in FOCUS_TOPICS.items():
                    if is_keyword_hit(item["text"], keywords):
                        focus[topic].append(item)
    except Exception as exc:
        items.append({"source": "东财快讯", "error": f"{type(exc).__name__}: {str(exc)[:180]}"})
    return {
        "count": len([item for item in items if "text" in item]),
        "items": items[:80],
        "focus": {topic: values[:15] for topic, values in focus.items()},
    }


def collect_cls_news() -> dict[str, Any]:
    if ak is None:
        raise RuntimeError("akshare is not installed")
    items = []
    focus: dict[str, list[dict[str, Any]]] = {topic: [] for topic in FOCUS_TOPICS}
    for source_name, loader in [
        ("财联社重点", lambda: ak.stock_info_global_cls(symbol="重点")),
        ("财联社全部", lambda: ak.stock_info_global_cls(symbol="全部")),
    ]:
        try:
            df = loader()
            for row in (jsonable(df) or [])[:120]:
                item = normalize_news_item(source_name, row)
                if is_theme_hit(item["text"]) or is_foreign_org_hit(item["text"]) or any(is_keyword_hit(item["text"], keywords) for keywords in FOCUS_EVENT_GROUPS.values()):
                    items.append(item)
                    for topic, keywords in FOCUS_TOPICS.items():
                        if is_keyword_hit(item["text"], keywords):
                            focus[topic].append(item)
        except Exception as exc:
            items.append({"source": source_name, "error": f"{type(exc).__name__}: {str(exc)[:180]}"})
    return {
        "count": len([item for item in items if "text" in item]),
        "items": items[:80],
        "focus": {topic: values[:15] for topic, values in focus.items()},
    }


def collect_metal_news() -> dict[str, Any]:
    if ak is None:
        raise RuntimeError("akshare is not installed")
    rows = []
    try:
        df = ak.futures_news_shmet(symbol="全部")
        rows = jsonable(df) or []
    except TypeError:
        df = ak.futures_news_shmet()
        rows = jsonable(df) or []
    items = []
    for row in rows[:180]:
        item = normalize_news_item("上海金属网", row)
        if is_theme_hit(item["text"]):
            items.append(item)
    return {"count": len(items), "items": items[:80]}


def cninfo_market_for_code(code: str) -> str:
    if code.startswith("6"):
        return "沪市"
    if code.startswith(("8", "920")):
        return "北交所"
    return "深市"


def collect_focus_announcements() -> dict[str, Any]:
    if ak is None:
        raise RuntimeError("akshare is not installed")
    items = []
    start = (today_cn() - timedelta(days=2)).strftime("%Y%m%d")
    end = today_cn().strftime("%Y%m%d")
    priority_keywords = ["业绩预告", "半年", "半年度", "日常经营", "风险提示", "其他融资", "锂矿", "复产", "储能", "电池"]
    for code, name in FOCUS_STOCKS.items():
        try:
            df = ak.stock_zh_a_disclosure_report_cninfo(
                symbol=code,
                market=cninfo_market_for_code(code),
                start_date=start,
                end_date=end,
            )
            for row in (jsonable(df) or [])[:80]:
                item = normalize_news_item(f"巨潮公告/{name}", row)
                item["stock_code"] = code
                item["stock_name"] = name
                if not is_recent_time(item.get("time"), hours=48):
                    continue
                if is_keyword_hit(item["text"], priority_keywords + FOCUS_EVENT_GROUPS.get(name, [])):
                    items.append(item)
        except Exception as exc:
            items.append({"source": f"巨潮公告/{name}", "error": f"{type(exc).__name__}: {str(exc)[:180]}"})
    items.sort(key=news_sort_key, reverse=True)
    return {"count": len([item for item in items if "text" in item]), "items": items[:60]}


def classify_sentiment(text: str) -> str:
    pos = sum(1 for word in POSITIVE_WORDS if word in text)
    neg = sum(1 for word in NEGATIVE_WORDS if word in text)
    if pos > neg:
        return "偏多"
    if neg > pos:
        return "偏空"
    return "中性"


def concise_report_summary(title: str, summary: str | None = None) -> str:
    """Use provider summary when available; otherwise derive a short title-based point."""
    text = re.sub(r"\s+", " ", str(summary or "")).strip()
    if text:
        return text[:220]
    title = re.sub(r"\s+", " ", str(title or "")).strip()
    if not title:
        return ""
    for sep in ["：", ":", "——", "--", "—"]:
        if sep in title:
            title = title.split(sep, 1)[1].strip() or title
            break
    return f"标题要点：{title[:180]}"


def report_link(row: dict[str, Any], pdf_url: str | None) -> str | None:
    return (
        row.get("url")
        or row.get("link")
        or row.get("reportUrl")
        or row.get("attachUrl")
        or row.get("infoUrl")
        or pdf_url
    )


def normalize_report_item(row: dict[str, Any], kind: str | None = None, analyst: str | None = None) -> dict[str, Any]:
    title = row.get("title") or ""
    summary = row.get("summary") or row.get("zy") or ""
    text = f"{title} {summary} {text_from_record(row)}"
    pdf_url = f"https://pdf.dfcfw.com/pdf/H3_{row.get('infoCode')}_1.pdf" if row.get("infoCode") else None
    return {
        "kind": kind or ("PDF研报" if pdf_url else "研报链接"),
        "date": (row.get("publishDate") or "")[:10],
        "org": row.get("orgSName"),
        "analyst": analyst,
        "title": title,
        "summary": concise_report_summary(title, summary),
        "industry": row.get("indvInduName"),
        "rating": row.get("emRatingName"),
        "sentiment": classify_sentiment(text),
        "info_code": row.get("infoCode"),
        "pdf_url": pdf_url,
        "url": report_link(row, pdf_url),
    }


def report_key(item: dict[str, Any]) -> str:
    return str(item.get("info_code") or f"{item.get('date')}|{item.get('org')}|{item.get('title')}")


def dedup_reports(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for item in sorted(items, key=lambda x: str(x.get("date") or ""), reverse=True):
        key = report_key(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:limit]


def is_cicc_daily_report(row: dict[str, Any]) -> bool:
    text = text_from_record(row)
    org = str(row.get("orgSName") or "")
    return any(keyword.upper() in f"{org} {text}".upper() for keyword in ["中金", "CICC"])


def match_tracked_analysts(row: dict[str, Any]) -> list[dict[str, Any]]:
    text = text_from_record(row)
    org = str(row.get("orgSName") or "")
    matches = []
    for target in TRACKED_ANALYSTS:
        broker_aliases = BROKER_ALIAS_MAP.get(target["broker"], [target["broker"]])
        broker_hit = any(alias in org or alias in text for alias in broker_aliases)
        analyst_hit = any(alias in text for alias in target["aliases"])
        if broker_hit and analyst_hit:
            matches.append(target)
    return matches


def collect_reports() -> dict[str, Any]:
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Referer": "https://data.eastmoney.com/"})
    begin = (today_cn() - timedelta(days=2)).strftime("%Y-%m-%d")
    end = (today_cn() + timedelta(days=1)).strftime("%Y-%m-%d")
    params = {
        "industryCode": "*",
        "pageSize": "100",
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "beginTime": begin,
        "endTime": end,
        "pageNo": "1",
        "fields": "",
        "qType": "0",
        "orgCode": "",
        "code": "",
        "rcode": "",
    }
    rows = []
    for page in range(1, 4):
        page_params = {**params, "pageNo": str(page), "p": str(page), "pageNum": str(page), "pageNumber": str(page)}
        r = session.get("https://reportapi.eastmoney.com/report/list", params=page_params, timeout=15)
        r.raise_for_status()
        payload = r.json()
        batch = payload.get("data") or []
        rows.extend(batch)
        total_page = int(safe_float(payload.get("TotalPage") or payload.get("totalPage") or 1, 1))
        if not batch or page >= total_page:
            break
    theme_hits = []
    cicc_hits = []
    analyst_hits = []
    sentiment_counter: Counter[str] = Counter()
    for row in rows:
        title = row.get("title") or ""
        summary = row.get("summary") or row.get("zy") or ""
        text = f"{title} {summary}"
        if is_theme_hit(text):
            item = normalize_report_item(row)
            sentiment_counter[item["sentiment"]] += 1
            theme_hits.append(item)
        if is_cicc_daily_report(row):
            cicc_hits.append(normalize_report_item(row, kind="中金每日研报"))
        for target in match_tracked_analysts(row):
            analyst_name = "/".join(target["aliases"])
            item = normalize_report_item(row, kind="指定分析师研报", analyst=analyst_name)
            item["target_sector"] = target["sector"]
            item["target_broker"] = target["broker"]
            analyst_hits.append(item)
    theme_hits = dedup_reports(theme_hits, 50)
    cicc_hits = dedup_reports(cicc_hits, 20)
    analyst_hits = dedup_reports(analyst_hits, 30)
    return {
        "count": len(theme_hits),
        "sentiment": dict(sentiment_counter),
        "items": theme_hits,
        "cicc_reports": cicc_hits,
        "analyst_reports": analyst_hits,
        "analyst_watchlist": TRACKED_ANALYSTS,
        "window": {"begin": begin, "end": end},
    }


def pick_realtime_contract(rows: list[dict[str, Any]], material: dict[str, Any]) -> dict[str, Any] | None:
    if not rows:
        return None
    preferred = [
        row
        for row in rows
        if str(row.get("symbol") or "").endswith("0")
        or "连续" in str(row.get("name") or row.get("名称") or "")
        or "主力" in str(row.get("name") or row.get("名称") or "")
    ]
    return preferred[0] if preferred else rows[0]


def collect_material_inventory(symbol: str) -> dict[str, Any] | None:
    if ak is None:
        return None
    try:
        df = ak.futures_inventory_em(symbol=symbol)
        rows = jsonable(df) or []
        if not rows:
            return None
        latest = rows[-1]
        columns = list(latest.keys())
        date_col = detect_columns(columns, ["日期", "date", "时间"])
        inv_col = detect_columns(columns, ["库存", "仓单", "数量"])
        change_col = detect_columns(columns, ["增减", "变化", "change"])
        return {
            "source": f"akshare.futures_inventory_em({symbol})",
            "date": latest.get(date_col) if date_col else None,
            "value": latest.get(inv_col) if inv_col else None,
            "change": latest.get(change_col) if change_col else None,
            "raw": latest,
        }
    except Exception as exc:
        return {"source": f"akshare.futures_inventory_em({symbol})", "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def collect_material_radar() -> dict[str, Any]:
    if ak is None:
        raise RuntimeError("akshare is not installed")
    all_codes = sorted({code for item in MATERIAL_CONFIG for code in item.get("related_codes", [])})
    quote_error = None
    try:
        quote_map = call_with_alarm(
            lambda: apply_daily_close_overrides(tencent_quote(all_codes), max_seconds=18),
            25,
            "材料相关A股行情",
        )
    except Exception as exc:
        quote_error = f"{type(exc).__name__}: {str(exc)[:160]}"
        quote_map = {}
    items = []
    for config in MATERIAL_CONFIG:
        price_enabled = config["name"] == "碳酸锂"
        price = None
        price_error = None
        status = "no_realtime_source"
        if price_enabled and config.get("futures_symbol"):
            try:
                df = call_with_alarm(lambda: ak.futures_zh_realtime(symbol=config["futures_symbol"]), 8, f"{config['name']}期货")
                rows = jsonable(df) or []
                contract = pick_realtime_contract(rows, config)
                if contract:
                    change_pct = round(safe_float(contract.get("changepercent")) * 100, 2)
                    price = {
                        "symbol": contract.get("symbol"),
                        "price": safe_float(contract.get("trade")),
                        "unit": config.get("unit"),
                        "change_pct": change_pct,
                        "trend": trend_label(change_pct),
                        "time": contract.get("ticktime"),
                        "date": contract.get("tradedate"),
                        "source": f"akshare.futures_zh_realtime({config['futures_symbol']})",
                    }
                    status = "ok"
            except Exception as exc:
                price_error = f"{type(exc).__name__}: {str(exc)[:160]}"
                status = "fail"
        inventory = None
        if price_enabled and config.get("inventory_symbol"):
            try:
                inventory = call_with_alarm(lambda: collect_material_inventory(config["inventory_symbol"]), 8, f"{config['name']}库存")
            except Exception as exc:
                inventory = {"source": f"akshare.futures_inventory_em({config['inventory_symbol']})", "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
        related = [quote_map[code] for code in config.get("related_codes", []) if code in quote_map]
        items.append(
            {
                "name": config["name"],
                "category": config["category"],
                "keywords": config["keywords"],
                "display_type": "full_price_inventory" if price_enabled else "news_and_stocks_only",
                "status": status,
                "price": price,
                "price_error": price_error,
                "inventory": inventory,
                "base_tightness": config["tightness"],
                "expansion": config["expansion"],
                "related_stocks": related,
                "quote_error": quote_error,
                "coverage": "有期货/库存直连" if price_enabled and (price or inventory) else ("碳酸锂价格/库存暂不可用" if price_enabled else "仅展示相关 A 股和消息"),
            }
        )
    return {"items": items, "count": len(items)}


def collect_commodity_prices() -> dict[str, Any]:
    return collect_material_radar()


def detect_columns(columns: list[str], candidates: list[str]) -> str | None:
    for candidate in candidates:
        for column in columns:
            if candidate in column:
                return column
    return None


def collect_cffex_positions() -> dict[str, Any]:
    if ak is None:
        raise RuntimeError("akshare is not installed")
    target_vars = ["IF", "IC", "IH", "IM"]
    target_parties = ["中信", "国泰君安", "华泰", "海通", "广发", "银河", "申万", "招商"]
    diagnostics = []
    rows: list[dict[str, Any]] = []
    query_date = ""
    for offset in range(0, 15):
        query_date = (today_cn() - timedelta(days=offset)).strftime("%Y%m%d")
        day_rows: list[dict[str, Any]] = []
        day_notes = []
        for var in target_vars:
            try:
                payload = ak.get_cffex_rank_table(date=query_date, vars_list=[var])
                if isinstance(payload, dict):
                    var_rows = []
                    for contract, frame in payload.items():
                        for row in jsonable(frame) or []:
                            row["contract"] = contract
                            row["queried_var"] = var
                            var_rows.append(row)
                else:
                    var_rows = jsonable(payload) or []
                    for row in var_rows:
                        row["queried_var"] = var
                if var_rows:
                    day_rows.extend(var_rows)
                    day_notes.append(f"{var}:{len(var_rows)}")
                else:
                    day_notes.append(f"{var}:空")
            except Exception as exc:
                day_notes.append(f"{var}:{type(exc).__name__}:{str(exc)[:80]}")
        diagnostics.append(f"{query_date} " + " / ".join(day_notes))
        if day_rows:
            rows = day_rows
            break

    summaries = []
    for row in rows:
        text = text_from_record(row)
        if not any(var in text for var in target_vars):
            continue
        if not any(party in text for party in target_parties):
            continue
        summaries.append(row)
    normalized = []
    party_summary: dict[tuple[str, str], dict[str, Any]] = {}

    def clean_party(value: Any) -> str:
        return re.sub(r"\(.*?\)", "", str(value or "")).strip()

    def add_party(symbol: str, party: Any, side: str, value: Any, chg: Any) -> None:
        party_name = clean_party(party)
        if not party_name or not any(target in party_name for target in target_parties):
            return
        key = (symbol or "未知", party_name)
        item = party_summary.setdefault(
            key,
            {
                "symbol": symbol or "未知",
                "party": party_name,
                "long_value": 0,
                "long_chg": 0,
                "short_value": 0,
                "short_chg": 0,
            },
        )
        item[f"{side}_value"] += int(safe_float(value, 0))
        item[f"{side}_chg"] += int(safe_float(chg, 0))

    for row in summaries[:80]:
        cols = list(row.keys())
        long_party = detect_columns(cols, ["long_party_name", "多单", "买持"])
        short_party = detect_columns(cols, ["short_party_name", "空单", "卖持"])
        long_value = detect_columns(cols, ["long_open_interest", "多单持仓", "买持仓"])
        short_value = detect_columns(cols, ["short_open_interest", "空单持仓", "卖持仓"])
        long_chg = detect_columns(cols, ["long_open_interest_chg", "多单持仓变化", "买持仓变化"])
        short_chg = detect_columns(cols, ["short_open_interest_chg", "空单持仓变化", "卖持仓变化"])
        symbol = row.get("variety") or row.get("symbol") or row.get("合约") or row.get("品种") or row.get("queried_var")
        add_party(str(symbol), row.get(long_party) if long_party else None, "long", row.get(long_value), row.get(long_chg))
        add_party(str(symbol), row.get(short_party) if short_party else None, "short", row.get(short_value), row.get(short_chg))
        normalized.append(
            {
                "symbol": symbol,
                "contract": row.get("contract"),
                "long_party": row.get(long_party) if long_party else None,
                "long_value": row.get(long_value) if long_value else None,
                "long_chg": row.get(long_chg) if long_chg else None,
                "short_party": row.get(short_party) if short_party else None,
                "short_value": row.get(short_value) if short_value else None,
                "short_chg": row.get(short_chg) if short_chg else None,
                "raw": row,
            }
        )
    summary_rows = []
    for item in party_summary.values():
        item["net_value"] = item["long_value"] - item["short_value"]
        item["net_chg"] = item["long_chg"] - item["short_chg"]
        summary_rows.append(item)
    summary_rows.sort(key=lambda x: (0 if "中信" in x["party"] else 1, x["symbol"], -abs(x["net_value"])))
    aggregate = {
        "中信": {"long_value": 0, "long_chg": 0, "short_value": 0, "short_chg": 0},
        "其它机构": {"long_value": 0, "long_chg": 0, "short_value": 0, "short_chg": 0},
        "重点机构合计": {"long_value": 0, "long_chg": 0, "short_value": 0, "short_chg": 0},
    }
    for item in summary_rows:
        target = "中信" if "中信" in item["party"] else "其它机构"
        for field in ["long_value", "long_chg", "short_value", "short_chg"]:
            aggregate[target][field] += int(item.get(field) or 0)
            aggregate["重点机构合计"][field] += int(item.get(field) or 0)
    for item in aggregate.values():
        item["net_value"] = item["long_value"] - item["short_value"]
        item["net_chg"] = item["long_chg"] - item["short_chg"]
    aggregate_rows = []
    for name in ["中信", "其它机构", "重点机构合计"]:
        row = {"group": name, **aggregate[name]}
        row["direction"] = "净多" if row["net_value"] > 0 else ("净空" if row["net_value"] < 0 else "持平")
        aggregate_rows.append(row)
    empty_reason = None
    if not rows:
        empty_reason = "最近15个自然日未取得中金所席位表，常见原因是周末/节假日、交易所未公布或 akshare 接口空返回。"
    elif not normalized:
        empty_reason = "已取得中金所席位表，但未命中中信/重点机构席位或接口列名发生变化。"
    return {
        "date": query_date,
        "count": len(normalized),
        "raw_count": len(rows),
        "empty_reason": empty_reason,
        "diagnostics": diagnostics[:20],
        "aggregate": aggregate,
        "aggregate_rows": aggregate_rows,
        "party_summary": summary_rows,
        "items": normalized,
    }


def source_map(results: list[SourceResult]) -> dict[str, SourceResult]:
    return {result.name: result for result in results}


def build_focus_items(sources: dict[str, SourceResult]) -> list[str]:
    focus: dict[str, list[str]] = {topic: [] for topic in FOCUS_TOPICS}

    def add(topic: str, text: str) -> None:
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        if text and text not in focus[topic]:
            focus[topic].append(text[:260])

    news = sources.get("产业新闻")
    if news and news.ok:
        for topic, values in (news.data.get("focus") or {}).items():
            for item in values[:6]:
                add(topic, f"{item.get('source')}：{item.get('text')}")

    reports = sources.get("机构研报")
    if reports and reports.ok:
        for item in (reports.data.get("items") or [])[:30]:
            text = f"{item.get('title')} {item.get('summary')}"
            upper = text.upper()
            for topic, keywords in FOCUS_TOPICS.items():
                if any(keyword.upper() in upper for keyword in keywords):
                    add(topic, f"研报 {item.get('date')} {item.get('org') or ''}：{item.get('title')} {item.get('pdf_url') or ''}")

    ths = sources.get("同花顺热点")
    if ths and ths.ok:
        for item in (ths.data.get("top") or [])[:80]:
            text = f"{item.get('name')}({item.get('code')}) {item.get('reason')}"
            upper = text.upper()
            for topic, keywords in FOCUS_TOPICS.items():
                if any(keyword.upper() in upper for keyword in keywords):
                    add(topic, f"强势股 {text}")

    commodities = sources.get("商品价格")
    if commodities and commodities.ok:
        for item in commodities.data.get("items", []):
            for note in item.get("notes", [])[:5]:
                text = f"{note.get('title')} {note.get('summary')}"
                upper = text.upper()
                for topic, keywords in FOCUS_TOPICS.items():
                    if any(keyword.upper() in upper for keyword in keywords):
                        add(topic, f"价格线索 {note.get('date')} {note.get('org') or ''}：{note.get('title')} {note.get('pdf_url') or ''}")

    watch = sources.get("产业链行情")
    if watch and watch.ok:
        mapping = {
            "宁德相关": ["储能锂矿"],
            "美股科技": ["英伟达/AI算力"],
            "半导体上游材料": ["半导体材料"],
        }
        for topic, themes in mapping.items():
            for theme in themes:
                quotes = watch.data.get(theme) or []
                if quotes:
                    leaders = "、".join(f"{x['name']} {x['change_pct']}%" for x in quotes[:4])
                    add(topic, f"产业链行情 {theme}：{leaders}")

    items: list[str] = []
    for topic, values in focus.items():
        items.append(f"{topic}：")
        if values:
            items.extend(f"  {value}" for value in values[:6])
        else:
            items.append("  暂无命中")
    return items


def material_hits(material: dict[str, Any], sources: dict[str, SourceResult], limit: int = 8) -> list[dict[str, Any]]:
    keywords = [str(k).upper() for k in material.get("keywords", [])]
    hits: list[dict[str, Any]] = []

    def add(source: str, text: str, link: str | None = None, date_value: str | None = None) -> None:
        if not text:
            return
        upper = text.upper()
        if not any(keyword in upper for keyword in keywords):
            return
        signal = [word for word in MATERIAL_SIGNAL_WORDS if word.upper() in upper]
        key = f"{source}|{text[:80]}"
        if any(item.get("key") == key for item in hits):
            return
        hits.append(
            {
                "key": key,
                "material": material.get("name"),
                "source": source,
                "date": date_value,
                "text": re.sub(r"\s+", " ", text).strip()[:260],
                "link": link,
                "signal": "、".join(signal[:3]) if signal else "相关",
                "priority": 0 if signal else 1,
            }
        )

    news = sources.get("产业新闻")
    if news and news.ok:
        for item in news.data.get("items", []):
            add(item.get("source") or "产业新闻", item.get("text") or "", None, None)

    cls_news = sources.get("财联社快讯")
    if cls_news and cls_news.ok:
        for item in cls_news.data.get("items", []):
            add(item.get("source") or "财联社快讯", item.get("text") or "", item.get("link"), item.get("time"))

    metal_news = sources.get("金属快讯")
    if metal_news and metal_news.ok:
        for item in metal_news.data.get("items", []):
            add(item.get("source") or "金属快讯", item.get("text") or "", item.get("link"), item.get("time"))

    announcements = sources.get("重点公告")
    if announcements and announcements.ok:
        for item in announcements.data.get("items", []):
            add(item.get("source") or "重点公告", item.get("text") or "", item.get("link"), item.get("time"))

    reports = sources.get("机构研报")
    if reports and reports.ok:
        for item in reports.data.get("items", []):
            text = f"{item.get('title') or ''} {item.get('summary') or ''}"
            add(f"研报/{item.get('org') or ''}".strip("/"), text, item.get("pdf_url"), item.get("date"))

    ths = sources.get("同花顺热点")
    if ths and ths.ok:
        for item in ths.data.get("top", []):
            text = f"{item.get('name')}({item.get('code')}) {item.get('reason')}"
            add("同花顺题材", text, None, ths.data.get("date"))

    def sort_key(item: dict[str, Any]) -> tuple[int, int]:
        digits = re.sub(r"\D", "", str(item.get("date") or ""))
        return (item["priority"], -int(digits or "0"))

    hits.sort(key=sort_key)
    return hits[:limit]


def infer_foreign_org(text: str) -> str:
    for keyword in FOREIGN_ORG_KEYWORDS:
        if keyword.upper() in str(text or "").upper():
            return keyword
    return "海外机构"


def collect_overseas_opinions(sources: dict[str, SourceResult]) -> list[dict[str, Any]]:
    candidates = []
    for source_name in ["财联社快讯", "产业新闻"]:
        source = sources.get(source_name)
        if not source or not source.ok:
            continue
        for item in source.data.get("items", []):
            text = item.get("text") or ""
            if not is_foreign_org_hit(text):
                continue
            if item.get("time") and not is_recent_time(item.get("time"), hours=72):
                continue
            candidates.append(
                {
                    "kind": "海外观点线索",
                    "date": str(item.get("time") or "")[:10],
                    "time": item.get("time"),
                    "org": infer_foreign_org(text),
                    "source": item.get("source") or source_name,
                    "title": item.get("title") or text[:120],
                    "summary": (item.get("content") or text)[:260],
                    "industry": "海外机构观点",
                    "rating": None,
                    "sentiment": classify_sentiment(text),
                    "url": item.get("link"),
                    "pdf_url": None,
                }
            )
    seen = set()
    deduped = []
    for item in sorted(candidates, key=lambda x: news_sort_key(x), reverse=True):
        key = f"{item.get('org')}|{item.get('title')}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:12]


def collect_focus_events(sources: dict[str, SourceResult]) -> list[dict[str, Any]]:
    events = []

    def add_event(group: str, item: dict[str, Any], fallback_source: str, kind: str) -> None:
        text = item.get("text") or " ".join(str(item.get(k) or "") for k in ["title", "content", "summary"])
        if not text:
            return
        time_value = item.get("time") or item.get("date")
        if not time_value or not is_recent_time(time_value, hours=48):
            return
        events.append(
            {
                "group": group,
                "kind": kind,
                "source": item.get("source") or fallback_source,
                "time": str(time_value or ""),
                "title": item.get("title") or text[:120],
                "content": item.get("content") or item.get("summary") or text[:260],
                "text": text[:500],
                "link": item.get("link") or item.get("url") or item.get("pdf_url"),
            }
        )

    for source_name, kind in [
        ("财联社快讯", "消息"),
        ("产业新闻", "消息"),
        ("重点公告", "公告"),
        ("金属快讯", "材料消息"),
    ]:
        source = sources.get(source_name)
        if not source or not source.ok:
            continue
        for item in source.data.get("items", []):
            text = item.get("text") or ""
            for group, keywords in FOCUS_EVENT_GROUPS.items():
                candidate_text = f"{text} {item.get('source') or ''} {item.get('stock_name') or ''}"
                if is_focus_event_hit(group, candidate_text):
                    add_event(group, item, source_name, kind)

    reports = sources.get("机构研报")
    if reports and reports.ok:
        for item in reports.data.get("items", []):
            text = f"{item.get('title') or ''} {item.get('summary') or ''}"
            for group, keywords in FOCUS_EVENT_GROUPS.items():
                if is_focus_event_hit(group, text):
                    add_event(group, {**item, "text": text, "time": item.get("date"), "link": item.get("url") or item.get("pdf_url"), "source": f"研报/{item.get('org') or ''}"}, "机构研报", "研报线索")

    seen = set()
    deduped = []
    for item in sorted(events, key=news_sort_key, reverse=True):
        key = f"{item.get('group')}|{item.get('title')}|{item.get('source')}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def signal_tightness(base: str, hits: list[dict[str, Any]], price: dict[str, Any] | None) -> str:
    text = " ".join(hit.get("text", "") for hit in hits)
    if any(word in text for word in ["断供", "紧缺", "库存低", "库存低位", "出口管制", "限制出口"]):
        return "紧缺/供给扰动"
    if any(word in text for word in ["涨价", "价格上行", "供需缺口"]):
        return "价格偏强/偏紧"
    if price and safe_float(price.get("change_pct")) >= 3:
        return "价格明显上行"
    return base


def build_fermentation_module(sources: dict[str, SourceResult]) -> dict[str, Any]:
    ths = sources.get("同花顺热点")
    limit_up = sources.get("涨停池")
    tag_top = ths.data.get("tag_top", [])[:10] if ths and ths.ok else []
    industry_top = limit_up.data.get("industry_top", [])[:8] if limit_up and limit_up.ok else []
    top_limitup_industries = limit_up.data.get("top_limitup_industries", []) if limit_up and limit_up.ok else []
    one_word = limit_up.data.get("one_word_boards", [])[:20] if limit_up and limit_up.ok else []
    metrics = [
        {"label": "强势股", "value": ths.data.get("count", 0) if ths and ths.ok else "NA"},
        {"label": "涨停股", "value": limit_up.data.get("count", 0) if limit_up and limit_up.ok else "NA"},
        {"label": "一字板", "value": limit_up.data.get("one_word_count", 0) if limit_up and limit_up.ok else "NA"},
    ]
    return {
        "type": "fermentation",
        "title": "最强发酵方向",
        "summary": "同花顺题材词频 + 涨停池行业集中度 + 一字板明细。",
        "metrics": metrics,
        "tags": [{"name": name, "count": count} for name, count in tag_top],
        "industries": [{"name": name, "count": count} for name, count in industry_top],
        "top_limitup_industries": top_limitup_industries,
        "one_word_boards": one_word,
        "items": [
            f"高频题材：{'、'.join(name + '(' + str(count) + ')' for name, count in tag_top[:6]) or '暂无'}",
            f"前三涨停集中板块：{'、'.join(x.get('name', '') + '(' + str(x.get('count', 0)) + ')' for x in top_limitup_industries[:3]) or '暂无'}",
            f"一字板：{'、'.join(x.get('name') + '(' + x.get('code') + ')' for x in one_word[:8]) or '暂无'}",
        ],
    }


def build_material_radar_module(sources: dict[str, SourceResult]) -> dict[str, Any]:
    material_source = sources.get("材料雷达") or sources.get("商品价格")
    rows = material_source.data.get("items", []) if material_source and material_source.ok else []
    materials = []
    for row in rows:
        hits = material_hits(row, sources, limit=6)
        price = row.get("price")
        inventory = row.get("inventory")
        related = row.get("related_stocks") or []
        materials.append(
            {
                "name": row.get("name"),
                "category": row.get("category"),
                "display_type": row.get("display_type"),
                "price": price,
                "inventory": inventory,
                "tightness": signal_tightness(row.get("base_tightness", ""), hits, price),
                "expansion": row.get("expansion"),
                "coverage": row.get("coverage"),
                "news": hits[:3],
                "related_stocks": related[:12],
            }
        )
    order = {"紧缺/供给扰动": 0, "价格偏强/偏紧": 1, "价格明显上行": 2}
    materials.sort(key=lambda item: (0 if item.get("name") == "碳酸锂" else 1, order.get(item.get("tightness"), 3)))
    return {
        "type": "material_radar",
        "title": "热点上游材料雷达",
        "summary": "碳酸锂置顶展示价格/库存；其它材料按三列卡片展示相关 A 股、紧缺线索和最新消息。",
        "materials": materials,
        "items": [f"覆盖材料 {len(materials)} 个；只有碳酸锂展示价格/库存，其它材料不填虚假报价。"],
    }


def build_material_news_module(sources: dict[str, SourceResult]) -> dict[str, Any]:
    material_source = sources.get("材料雷达") or sources.get("商品价格")
    rows = material_source.data.get("items", []) if material_source and material_source.ok else MATERIAL_CONFIG
    news_items = []
    for row in rows:
        for hit in material_hits(row, sources, limit=6):
            if hit.get("signal") != "相关" or len(news_items) < 12:
                news_items.append(hit)
    def sort_key(item: dict[str, Any]) -> tuple[int, int]:
        digits = re.sub(r"\D", "", str(item.get("date") or ""))
        return (0 if item.get("signal") != "相关" else 1, -int(digits or "0"))

    news_items.sort(key=sort_key)
    return {
        "type": "material_news",
        "title": "材料突发消息",
        "summary": "重点捕捉断供、涨价、出口限制、停产、检修和库存低位。",
        "news": news_items[:24],
        "items": [item.get("text", "") for item in news_items[:8]] or ["暂无材料突发线索。"],
    }


def build_futures_module(sources: dict[str, SourceResult]) -> dict[str, Any]:
    futures = sources.get("期指席位")
    rows = []
    if futures and futures.ok:
        for row in futures.data.get("aggregate_rows", []):
            rows.append(
                {
                    "group": row.get("group"),
                    "long_value": row.get("long_value", 0),
                    "long_chg": row.get("long_chg", 0),
                    "short_value": row.get("short_value", 0),
                    "short_chg": row.get("short_chg", 0),
                    "net_value": row.get("net_value", 0),
                    "net_chg": row.get("net_chg", 0),
                    "direction": row.get("direction"),
                }
            )
    diagnostics = []
    empty_reason = None
    if futures and futures.ok:
        diagnostics = futures.data.get("diagnostics", []) or []
        empty_reason = futures.data.get("empty_reason")
    return {
        "type": "futures_summary",
        "title": "期指重点席位多空",
        "summary": f"中金所 IF/IC/IH/IM 重点席位汇总，日期 {futures.data.get('date') if futures and futures.ok else '暂无'}。",
        "table": rows,
        "diagnostics": diagnostics,
        "empty_reason": empty_reason,
        "items": [
            f"{row['group']}：多{row['long_value']} / 空{row['short_value']} / 净{row['net_value']}"
            for row in rows
        ] or [empty_reason or "暂无期指席位数据。"],
    }


def build_reports_module(sources: dict[str, SourceResult]) -> dict[str, Any]:
    reports = sources.get("机构研报")
    items = []
    cicc = []
    analyst_hits = []
    analyst_watchlist = TRACKED_ANALYSTS
    if reports and reports.ok:
        items = reports.data.get("items", [])[:12]
        cicc = reports.data.get("cicc_reports", [])[:10]
        analyst_hits = reports.data.get("analyst_reports", [])[:12]
        analyst_watchlist = reports.data.get("analyst_watchlist", TRACKED_ANALYSTS)
    hit_labels = {
        f"{item.get('target_broker') or item.get('org')}:{item.get('analyst')}"
        for item in analyst_hits
        if item.get("analyst")
    }
    missing = []
    for target in analyst_watchlist:
        aliases = "/".join(target.get("aliases", []))
        key = f"{target.get('broker')}:{aliases}"
        if key not in hit_labels:
            missing.append(f"{target.get('sector')} {target.get('broker')} {aliases}")
    analyst_group = analyst_hits[:]
    if missing:
        analyst_group.append(
            {
                "kind": "跟踪提示",
                "date": today_cn().isoformat(),
                "org": "指定分析师跟踪",
                "title": f"近三天无精确命中：{'、'.join(missing[:16])}",
                "summary": "按分析师姓名精确匹配；不使用券商行业兜底，避免混入噪音。",
                "sentiment": "中性",
            }
        )
    overseas = collect_overseas_opinions(sources)
    return {
        "type": "reports",
        "title": "主题研报精华",
        "summary": "近三天研报/链接 + 海外机构观点线索 + 中金每日研报 + 指定分析师精确跟踪。",
        "groups": [
            {"name": "中金每日研报", "items": cicc},
            {"name": "指定分析师跟踪", "items": analyst_group},
            {"name": "近三天研报/链接", "items": items},
            {"name": "海外机构观点线索", "items": overseas},
        ],
        "reports": items,
        "overseas_opinions": overseas,
        "cicc_reports": cicc,
        "analyst_reports": analyst_hits,
        "items": [f"{x.get('date')} / {x.get('org')} / {x.get('sentiment')} / {x.get('rating')} / {x.get('industry')}：{x.get('title')}" for x in cicc + analyst_hits + items + overseas]
        or ["暂无主题研报命中。"],
    }


def build_focus_module(sources: dict[str, SourceResult]) -> dict[str, Any]:
    events = collect_focus_events(sources)
    groups = []
    for name in FOCUS_EVENT_GROUPS:
        group_items = [item for item in events if item.get("group") == name][:8]
        groups.append({"name": name, "items": group_items})
    raw_items = []
    for group in groups:
        raw_items.append(f"{group['name']}：")
        raw_items.extend(
            f"  {item.get('time') or ''} {item.get('source') or ''}：{item.get('title') or item.get('text') or ''}"
            for item in group["items"][:5]
        )
        if not group["items"]:
            raw_items.append("  暂无近48小时命中")
    return {
        "type": "focus_groups",
        "title": "重点公司/产业消息",
        "summary": "近48小时公告与消息；覆盖重点公司/产业、美国宏观与美联储、美股科技和韩股科技消息。",
        "groups": groups,
        "items": raw_items,
    }


def build_equity_map_module(sources: dict[str, SourceResult]) -> dict[str, Any]:
    watch = sources.get("产业链行情")
    groups = []
    if watch and watch.ok:
        for theme, quotes in watch.data.items():
            groups.append({"name": theme, "stocks": quotes[:8]})
    return {
        "type": "equity_map",
        "title": "产业链 A股映射",
        "summary": "按热点方向展示相关 A 股的涨跌幅、成交额、市值和量比。",
        "groups": groups,
        "items": [f"{g['name']}：{'、'.join(x.get('name') + ' ' + str(x.get('change_pct')) + '%' for x in g['stocks'][:3])}" for g in groups]
        or ["暂无产业链行情。"],
    }


def build_status_module(results: list[SourceResult]) -> dict[str, Any]:
    statuses = [{"name": r.name, "ok": r.ok, "error": r.error, "elapsed_ms": r.elapsed_ms} for r in results]
    return {
        "type": "status",
        "title": "数据源状态与口径",
        "summary": "失败源会保留在报告中；材料无直连价格时使用新闻/研报/题材线索，不填虚假报价。",
        "statuses": statuses,
        "items": [
            f"{'OK' if item['ok'] else 'FAIL'} {item['name']} ({item['elapsed_ms']}ms)"
            + (f"：{item['error']}" if item.get("error") else "")
            for item in statuses
        ],
    }


def build_raw_digest(results: list[SourceResult]) -> str:
    sources = source_map(results)
    lines: list[str] = []
    ths = sources.get("同花顺热点")
    if ths and ths.ok:
        data = ths.data
        tags = "、".join(f"{tag}({n})" for tag, n in data.get("tag_top", [])[:8])
        lines.append(f"同花顺热点：强势股 {data.get('count')} 只，题材词频：{tags or '无'}。")
    limit_up = sources.get("涨停池")
    if limit_up and limit_up.ok:
        data = limit_up.data
        industries = "、".join(f"{name}({n})" for name, n in data.get("industry_top", [])[:8])
        top_industries = "；".join(
            f"{item.get('name')}({item.get('count')}): "
            + "、".join(f"{stock.get('name')}({stock.get('code')})" + ("一字" if stock.get("is_one_word_board") else "") for stock in item.get("stocks", [])[:8])
            for item in data.get("top_limitup_industries", [])[:3]
        )
        one_word = "、".join(f"{x['name']}({x['code']})" for x in data.get("one_word_boards", [])[:8])
        lines.append(
            f"涨停池：涨停 {data.get('count')} 只，一字板 {data.get('one_word_count', 0)} 只，"
            f"行业集中：{industries or '无'}。前三板块个股：{top_industries or '无'}。一字板样例：{one_word or '无'}。"
        )
    north = sources.get("北向资金")
    if north and north.ok:
        data = north.data
        lines.append(
            f"北向资金：沪股通 {data.get('hgt_yi')} 亿，深股通 {data.get('sgt_yi')} 亿，合计 {data.get('total_yi')} 亿。"
        )
    reports = sources.get("机构研报")
    if reports and reports.ok:
        data = reports.data
        lines.append(f"机构研报：主题命中 {data.get('count')} 篇，多空统计 {data.get('sentiment')}。")
    futures = sources.get("期指席位")
    if futures and futures.ok:
        data = futures.data
        aggregate = data.get("aggregate") or {}
        zhongxin = [
            x
            for x in data.get("party_summary", [])
            if "中信" in x.get("party", "")
        ][:4]
        zhongxin_text = "；".join(
            f"{x['symbol']} 多{x['long_value']}/空{x['short_value']}/净{x['net_value']}"
            for x in zhongxin
        )
        zx = aggregate.get("中信", {})
        inst = aggregate.get("重点机构合计", {})
        lines.append(
            f"期指席位：{data.get('date')} 命中重点席位 {data.get('count')} 条。"
            f"中信合计 多{zx.get('long_value', 0)}/空{zx.get('short_value', 0)}/净{zx.get('net_value', 0)}；"
            f"重点机构合计 多{inst.get('long_value', 0)}/空{inst.get('short_value', 0)}/净{inst.get('net_value', 0)}。"
            f"中信分品种：{zhongxin_text or '未命中'}。"
            + (f"诊断：{data.get('empty_reason')}。" if data.get("empty_reason") else "")
        )
    commodities = sources.get("材料雷达") or sources.get("商品价格")
    if commodities and commodities.ok:
        parts = []
        for item in commodities.data.get("items", [])[:8]:
            price = item.get("price") or {}
            if price:
                parts.append(
                    f"{item['name']} {price.get('price')} {price.get('unit') or ''} "
                    f"({price.get('change_pct')}%, {price.get('trend')})"
                )
            else:
                parts.append(f"{item['name']}：{item.get('coverage')}")
        lines.append("材料雷达：" + "；".join(parts))
    news = sources.get("产业新闻")
    if news and news.ok:
        data = news.data
        sample = "；".join(item.get("text", "")[:80] for item in data.get("items", [])[:5] if item.get("text"))
        lines.append(f"产业新闻：主题命中 {data.get('count')} 条。样例：{sample}")
    cls_news = sources.get("财联社快讯")
    if cls_news and cls_news.ok:
        data = cls_news.data
        sample = "；".join(item.get("text", "")[:80] for item in data.get("items", [])[:5] if item.get("text"))
        lines.append(f"财联社快讯：主题命中 {data.get('count')} 条。样例：{sample}")
    metal_news = sources.get("金属快讯")
    if metal_news and metal_news.ok:
        data = metal_news.data
        sample = "；".join(item.get("text", "")[:80] for item in data.get("items", [])[:5] if item.get("text"))
        lines.append(f"金属快讯：材料主题命中 {data.get('count')} 条。样例：{sample}")
    announcements = sources.get("重点公告")
    if announcements and announcements.ok:
        data = announcements.data
        sample = "；".join(item.get("text", "")[:80] for item in data.get("items", [])[:5] if item.get("text"))
        lines.append(f"重点公告：近48小时命中 {data.get('count')} 条。样例：{sample}")
    quotes = sources.get("产业链行情")
    if quotes and quotes.ok:
        parts = []
        for theme, items in quotes.data.items():
            leaders = "、".join(f"{x['name']} {x['change_pct']}%" for x in items[:3])
            parts.append(f"{theme}: {leaders}")
        lines.append("产业链行情：" + "；".join(parts))
    failed = [f"{r.name}: {r.error}" for r in results if not r.ok]
    if failed:
        lines.append("失败数据源：" + "；".join(failed))
    return "\n".join(lines)


def build_brief_sections(results: list[SourceResult], ai_summary: str | None, ai_error: str | None) -> list[dict[str, Any]]:
    sources = source_map(results)
    return [
        build_fermentation_module(sources),
        build_material_radar_module(sources),
        build_material_news_module(sources),
        build_futures_module(sources),
        build_reports_module(sources),
        build_focus_module(sources),
        build_equity_map_module(sources),
        build_status_module(results),
    ]


def deepseek_summary(
    results: list[SourceResult],
    raw_digest: str,
    api_key: str | None = None,
    model: str | None = None,
) -> tuple[str | None, str | None]:
    api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return None, "未设置 DEEPSEEK_API_KEY"
    model = model or os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是A股投研情报助手。只基于用户提供的数据做摘要，不编造未给出的事实。"
                    "输出中文，结构包括：核心结论、最强发酵方向、资金/多空、相关A股、风险提示。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请把下面的结构化采集结果整理为盘后投研摘要。"
                    "如果数据源失败，请明确标注口径限制。\n\n"
                    f"原始摘要：\n{raw_digest}\n\n"
                    f"结构化JSON：\n{json.dumps([r.to_dict() for r in results], ensure_ascii=False)[:45000]}"
                ),
            },
        ],
        "temperature": 0.2,
        "max_tokens": 1800,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        r = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"].strip(), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {str(exc)[:300]}"


def render_markdown(report: dict[str, Any]) -> str:
    source_status = report["source_status"]
    lines = [
        f"# A股每日情报雷达 - {report['date']}",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- DeepSeek：{'已生成摘要' if report.get('ai_summary') else '未生成摘要'}",
        "",
        "## AI 投研摘要",
        "",
        report.get("ai_summary") or f"AI 摘要未生成：{report.get('ai_error') or '未知原因'}",
        "",
        "## 原始聚合摘要",
        "",
        report["raw_digest"] or "暂无可用数据。",
        "",
        "## 数据源状态",
        "",
    ]
    for item in source_status:
        marker = "OK" if item["ok"] else "FAIL"
        suffix = f" - {item['error']}" if item.get("error") else ""
        lines.append(f"- {marker} {item['name']} ({item['elapsed_ms']}ms){suffix}")
    lines.extend(["", "## 结构化数据", "", "```json", json.dumps(report["sources"], ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines)


def write_report_files(report: dict[str, Any]) -> None:
    dated_json = REPORT_DIR / f"{report['date']}.json"
    dated_md = REPORT_DIR / f"{report['date']}.md"
    for path in [dated_json, LATEST_JSON]:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for path in [dated_md, LATEST_MD]:
        path.write_text(report["markdown"], encoding="utf-8")


def emergency_report(error: str, tb: str) -> dict[str, Any]:
    ensure_env()
    generated_at = now_cn().strftime("%Y-%m-%d %H:%M:%S")
    result = SourceResult("运行异常", False, {"traceback": tb}, error=error, elapsed_ms=0)
    report = {
        "date": today_cn().isoformat(),
        "generated_at": generated_at,
        "ai_summary": None,
        "ai_error": "生成流程异常，已输出降级报告",
        "raw_digest": f"生成流程异常：{error}\n\n{tb}",
        "source_status": [
            {"name": result.name, "ok": result.ok, "error": result.error, "elapsed_ms": result.elapsed_ms}
        ],
        "brief_sections": [
            {
                "type": "status",
                "title": "数据源状态与口径",
                "summary": "生成流程异常，已输出降级报告；请查看原始聚合摘要中的 traceback。",
                "statuses": [{"name": result.name, "ok": result.ok, "error": result.error, "elapsed_ms": result.elapsed_ms}],
                "items": [f"FAIL 运行异常：{error}"],
            }
        ],
        "sources": {result.name: {"ok": result.ok, "data": result.data, "error": result.error}},
    }
    report["markdown"] = render_markdown(report)
    write_report_files(report)
    return report


def generate_report(
    api_key: str | None = None,
    model: str | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    ensure_env()
    source_defs = [
        ("同花顺热点", collect_ths_hot),
        ("北向资金", collect_northbound),
        ("涨停池", collect_limit_up),
        ("材料雷达", collect_material_radar),
        ("财联社快讯", collect_cls_news),
        ("金属快讯", collect_metal_news),
        ("重点公告", collect_focus_announcements),
        ("产业新闻", collect_news),
        ("机构研报", collect_reports),
        ("期指席位", collect_cffex_positions),
        ("产业链行情", collect_watchlist_quotes),
    ]
    results = []
    total_steps = len(source_defs) + 2
    for index, (name, fn) in enumerate(source_defs, start=1):
        if progress_callback:
            progress_callback({"stage": "collecting", "source": name, "done": index - 1, "total": total_steps})
        result = run_source(name, fn)
        results.append(result)
        if progress_callback:
            progress_callback(
                {
                    "stage": "collected",
                    "source": name,
                    "ok": result.ok,
                    "done": index,
                    "total": total_steps,
                    "error": result.error,
                }
            )
    results = [SourceResult(r.name, r.ok, jsonable(r.data), r.error, r.elapsed_ms) for r in results]
    raw_digest = build_raw_digest(results)
    if progress_callback:
        progress_callback({"stage": "summarizing", "source": "DeepSeek摘要", "done": len(source_defs), "total": total_steps})
    ai_summary, ai_error = deepseek_summary(results, raw_digest, api_key=api_key, model=model)
    if progress_callback:
        progress_callback(
            {
                "stage": "summarized",
                "source": "DeepSeek摘要",
                "ok": bool(ai_summary),
                "done": len(source_defs) + 1,
                "total": total_steps,
                "error": ai_error,
            }
        )
    generated_at = now_cn().strftime("%Y-%m-%d %H:%M:%S")
    report = {
        "date": today_cn().isoformat(),
        "generated_at": generated_at,
        "ai_summary": ai_summary,
        "ai_error": ai_error,
        "raw_digest": raw_digest,
        "source_status": [
            {"name": r.name, "ok": r.ok, "error": r.error, "elapsed_ms": r.elapsed_ms} for r in results
        ],
        "brief_sections": build_brief_sections(results, ai_summary, ai_error),
        "sources": {r.name: {"ok": r.ok, "data": r.data, "error": r.error} for r in results},
    }
    if progress_callback:
        progress_callback({"stage": "writing", "source": "写入报告", "done": len(source_defs) + 1, "total": total_steps})
    report["markdown"] = render_markdown(report)
    write_report_files(report)
    if progress_callback:
        progress_callback({"stage": "done", "source": "完成", "done": total_steps, "total": total_steps})
    return report


def load_latest() -> dict[str, Any] | None:
    if not LATEST_JSON.exists():
        return None
    return json.loads(LATEST_JSON.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate daily A-share intelligence report")
    parser.add_argument("--latest", action="store_true", help="print latest report JSON instead of generating")
    args = parser.parse_args()
    if args.latest:
        print(json.dumps(load_latest(), ensure_ascii=False, indent=2))
        return
    try:
        report = generate_report()
    except Exception as exc:
        tb = traceback.format_exc()
        print(tb)
        report = emergency_report(f"{type(exc).__name__}: {str(exc)[:300]}", tb)
    print(report["markdown"])


if __name__ == "__main__":
    main()
