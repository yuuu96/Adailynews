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
import time
import traceback
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

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
    "石油",
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
    "材料雷达": 24,
    "金属快讯": 15,
    "产业新闻": 25,
    "机构研报": 25,
    "期指席位": 30,
    "产业链行情": 15,
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
    "英伟达相关": ["英伟达", "NVIDIA", "GB200", "GB300", "Rubin", "Blackwell", "NVL", "CUDA"],
    "半导体上游材料": ["半导体", "光刻胶", "电子特气", "氦气", "氦", "硅片", "CMP", "ABF", "InP", "GaAs", "前驱体"],
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
        "related_codes": ["002466", "002460", "300750", "002756"],
    },
    {
        "name": "VC电解液",
        "category": "锂电添加剂",
        "keywords": ["VC", "电解液", "添加剂", "碳酸亚乙烯酯"],
        "tightness": "跟随电解液需求和装置开工变化",
        "expansion": "中等：化工合成壁垒不极高，但客户认证和环保约束重要",
        "related_codes": ["002709", "300037", "300073", "002407"],
    },
    {
        "name": "六氟磷酸锂",
        "category": "锂电电解质",
        "keywords": ["六氟磷酸锂", "LiPF6", "电解质", "六氟"],
        "tightness": "周期弹性高，需跟踪价格和库存拐点",
        "expansion": "中等偏难：氟化工、安全环保和客户认证影响扩产",
        "related_codes": ["002709", "002407", "002326", "300037"],
    },
    {
        "name": "氦气",
        "category": "电子特气/稀有气体",
        "keywords": ["氦气", "氦", "Helium"],
        "tightness": "偏紧：海外气源、LNG副产和运输约束明显",
        "expansion": "难：资源禀赋决定供给，新增产能周期长",
        "related_codes": ["603318", "002549", "688146", "688267"],
    },
    {
        "name": "六氟化钨",
        "category": "半导体前驱体",
        "keywords": ["六氟化钨", "WF6", "钨前驱体", "钨"],
        "tightness": "需跟踪先进制程和存储扩产需求",
        "expansion": "难：高纯工艺、客户认证和安全环保门槛高",
        "related_codes": ["688146", "688268", "002409", "600360"],
    },
    {
        "name": "磷化铟",
        "category": "化合物半导体",
        "keywords": ["磷化铟", "InP", "铟磷"],
        "tightness": "偏紧：受光通信和射频需求拉动",
        "expansion": "难：晶体生长、衬底良率和认证周期长",
        "related_codes": ["600703", "300394", "300308", "300502"],
    },
    {
        "name": "铋",
        "category": "小金属",
        "keywords": ["铋", "金属铋", "秘"],
        "tightness": "需跟踪小金属价格和出口变化",
        "expansion": "中等偏难：多为伴生资源，供给弹性有限",
        "related_codes": ["600497", "000960", "600531"],
    },
    {
        "name": "锑",
        "category": "小金属/阻燃",
        "keywords": ["锑", "锑矿", "三氧化二锑"],
        "tightness": "偏紧：矿端集中，政策和出口扰动敏感",
        "expansion": "难：资源约束强，新矿开发周期长",
        "related_codes": ["600301", "002155", "000960"],
    },
    {
        "name": "氮化镓",
        "category": "第三代半导体",
        "keywords": ["氮化镓", "GaN", "第三代半导体"],
        "tightness": "结构性偏紧：高端衬底和外延产能更关键",
        "expansion": "难：外延、器件工艺和可靠性认证周期长",
        "related_codes": ["600703", "688234", "300373", "300102"],
    },
    {
        "name": "铟",
        "category": "小金属/化合物半导体",
        "keywords": ["铟", "金属铟", "ITO"],
        "tightness": "偏紧：伴生资源，光电和半导体需求扰动大",
        "expansion": "难：伴生属性强，新增供给弹性有限",
        "related_codes": ["000060", "000878", "600362"],
    },
    {
        "name": "氧化锆",
        "category": "陶瓷/小金属",
        "keywords": ["氧化锆", "锆", "锆英砂"],
        "tightness": "需跟踪锆系价格和陶瓷/新能源需求",
        "expansion": "中等：矿端和高纯加工能力共同约束",
        "related_codes": ["002167", "002149", "300224"],
    },
    {
        "name": "石油",
        "category": "能源化工",
        "keywords": ["石油", "原油", "油价", "OPEC"],
        "futures_symbol": "原油",
        "inventory_symbol": "原油",
        "unit": "元/桶",
        "tightness": "受地缘、OPEC供给和库存周期驱动",
        "expansion": "难：上游资本开支和地缘因素影响大",
        "related_codes": ["600028", "601857", "600938", "600256"],
    },
    {
        "name": "光刻胶",
        "category": "半导体材料",
        "keywords": ["光刻胶", "日本光刻胶", "KrF", "ArF", "EUV"],
        "tightness": "高端品类偏紧，海外供应扰动敏感",
        "expansion": "难：配方、验证、客户导入和稳定性门槛高",
        "related_codes": ["603650", "300054", "688199", "300576"],
    },
    {
        "name": "石英砂",
        "category": "光伏/半导体耗材",
        "keywords": ["石英砂", "高纯石英", "石英坩埚"],
        "tightness": "高纯品类易阶段性紧缺",
        "expansion": "难：矿源品质和提纯工艺决定供给",
        "related_codes": ["603688", "300395", "600293"],
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


def collect_watchlist_quotes() -> dict[str, list[dict[str, Any]]]:
    all_codes: list[str] = []
    for codes in WATCHLIST.values():
        all_codes.extend(codes)
    quotes = tencent_quote(sorted(set(all_codes)))
    grouped = {}
    for theme, codes in WATCHLIST.items():
        grouped[theme] = [quotes[code] for code in codes if code in quotes]
        grouped[theme].sort(key=lambda item: item.get("amount_yi", 0), reverse=True)
    return grouped


def collect_ths_hot() -> dict[str, Any]:
    today = date.today().strftime("%Y-%m-%d")
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
    d = date.today().strftime("%Y%m%d")
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
    return {
        "date": d,
        "count": len(cleaned),
        "industry_top": industry_counter.most_common(15),
        "one_word_count": len(one_word_boards),
        "one_word_boards": one_word_boards[:40],
        "top": cleaned[:40],
    }


def text_from_record(record: dict[str, Any]) -> str:
    return " ".join(str(v) for v in record.values() if v is not None)


def is_theme_hit(text: str) -> bool:
    text_upper = text.upper()
    return any(keyword.upper() in text_upper for keyword in THEME_KEYWORDS)


def collect_news() -> dict[str, Any]:
    if ak is None:
        raise RuntimeError("akshare is not installed")
    items = []
    focus: dict[str, list[dict[str, Any]]] = {topic: [] for topic in FOCUS_TOPICS}
    source_defs = [
        ("财联社重点", lambda: ak.stock_info_global_cls(symbol="重点")),
        ("财联社全部", lambda: ak.stock_info_global_cls(symbol="全部")),
        ("东财快讯", ak.stock_info_global_em),
    ]
    for source_name, loader in source_defs:
        try:
            df = loader()
            for row in (jsonable(df) or [])[:120]:
                text = text_from_record(row)
                if is_theme_hit(text):
                    item = {"source": source_name, "text": text[:500], "raw": row}
                    items.append(item)
                    upper = text.upper()
                    for topic, keywords in FOCUS_TOPICS.items():
                        if any(keyword.upper() in upper for keyword in keywords):
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
        text = text_from_record(row)
        if is_theme_hit(text):
            items.append({"source": "上海金属网", "text": text[:500], "raw": row})
    return {"count": len(items), "items": items[:80]}


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


def collect_reports() -> dict[str, Any]:
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Referer": "https://data.eastmoney.com/"})
    begin = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
    end = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
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
    r = session.get("https://reportapi.eastmoney.com/report/list", params=params, timeout=20)
    r.raise_for_status()
    rows = r.json().get("data") or []
    hits = []
    sentiment_counter: Counter[str] = Counter()
    for row in rows:
        title = row.get("title") or ""
        summary = row.get("summary") or row.get("zy") or ""
        text = f"{title} {summary}"
        if not is_theme_hit(text):
            continue
        sentiment = classify_sentiment(text)
        sentiment_counter[sentiment] += 1
        hits.append(
            {
                "date": (row.get("publishDate") or "")[:10],
                "org": row.get("orgSName"),
                "title": title,
                "summary": concise_report_summary(title, summary),
                "industry": row.get("indvInduName"),
                "rating": row.get("emRatingName"),
                "sentiment": sentiment,
                "info_code": row.get("infoCode"),
                "pdf_url": f"https://pdf.dfcfw.com/pdf/H3_{row.get('infoCode')}_1.pdf" if row.get("infoCode") else None,
            }
        )
    return {"count": len(hits), "sentiment": dict(sentiment_counter), "items": hits[:50]}


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
    quote_map = tencent_quote(all_codes)
    items = []
    for config in MATERIAL_CONFIG:
        price = None
        price_error = None
        status = "no_realtime_source"
        if config.get("futures_symbol"):
            try:
                df = ak.futures_zh_realtime(symbol=config["futures_symbol"])
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
        if config.get("inventory_symbol"):
            inventory = collect_material_inventory(config["inventory_symbol"])
        related = [quote_map[code] for code in config.get("related_codes", []) if code in quote_map]
        items.append(
            {
                "name": config["name"],
                "category": config["category"],
                "keywords": config["keywords"],
                "status": status,
                "price": price,
                "price_error": price_error,
                "inventory": inventory,
                "base_tightness": config["tightness"],
                "expansion": config["expansion"],
                "related_stocks": related,
                "coverage": "有期货/库存直连" if price or inventory else "暂无稳定直连价格，使用新闻/研报/题材线索",
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
    last_error = None
    for offset in range(0, 8):
        query_date = (date.today() - timedelta(days=offset)).strftime("%Y%m%d")
        try:
            payload = ak.get_cffex_rank_table(date=query_date, vars_list=target_vars)
            if isinstance(payload, dict):
                rows = []
                for contract, frame in payload.items():
                    for row in jsonable(frame) or []:
                        row["contract"] = contract
                        rows.append(row)
            else:
                rows = jsonable(payload) or []
            if rows:
                break
        except Exception as exc:
            last_error = exc
            rows = []
    else:
        raise RuntimeError(f"no CFFEX data: {last_error}")

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
        symbol = row.get("variety") or row.get("symbol") or row.get("合约") or row.get("品种")
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
    return {
        "date": query_date,
        "count": len(normalized),
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
            "英伟达相关": ["英伟达/AI算力"],
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

    metal_news = sources.get("金属快讯")
    if metal_news and metal_news.ok:
        for item in metal_news.data.get("items", []):
            add(item.get("source") or "金属快讯", item.get("text") or "", None, None)

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
        "one_word_boards": one_word,
        "items": [
            f"高频题材：{'、'.join(name + '(' + str(count) + ')' for name, count in tag_top[:6]) or '暂无'}",
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
                "price": price,
                "inventory": inventory,
                "tightness": signal_tightness(row.get("base_tightness", ""), hits, price),
                "expansion": row.get("expansion"),
                "coverage": row.get("coverage"),
                "news": hits[:3],
                "related_stocks": related[:5],
            }
        )
    order = {"紧缺/供给扰动": 0, "价格偏强/偏紧": 1, "价格明显上行": 2}
    materials.sort(key=lambda item: order.get(item.get("tightness"), 3))
    return {
        "type": "material_radar",
        "title": "热点上游材料雷达",
        "summary": "价格走势、库存/仓单、紧缺程度、扩产难度、最新线索和相关 A 股。",
        "materials": materials,
        "items": [f"覆盖材料 {len(materials)} 个；无直连价格的材料以新闻/研报/题材线索展示。"],
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
    return {
        "type": "futures_summary",
        "title": "期指重点席位多空",
        "summary": f"中金所 IF/IC/IH/IM 重点席位汇总，日期 {futures.data.get('date') if futures and futures.ok else '暂无'}。",
        "table": rows,
        "items": [
            f"{row['group']}：多{row['long_value']} / 空{row['short_value']} / 净{row['net_value']}"
            for row in rows
        ] or ["暂无期指席位数据。"],
    }


def build_reports_module(sources: dict[str, SourceResult]) -> dict[str, Any]:
    reports = sources.get("机构研报")
    items = []
    if reports and reports.ok:
        items = reports.data.get("items", [])[:12]
    return {
        "type": "reports",
        "title": "主题研报精华",
        "summary": "保留日期、机构、观点、评级、行业、标题、简要和 PDF 链接。",
        "reports": items,
        "items": [f"{x.get('date')} / {x.get('org')} / {x.get('sentiment')} / {x.get('rating')} / {x.get('industry')}：{x.get('title')}" for x in items]
        or ["暂无主题研报命中。"],
    }


def build_focus_module(sources: dict[str, SourceResult]) -> dict[str, Any]:
    groups = []
    raw_items = build_focus_items(sources)
    current = None
    for item in raw_items:
        if item.endswith("：") and not item.startswith("  "):
            current = {"name": item[:-1], "items": []}
            groups.append(current)
        elif current is not None:
            current["items"].append(item.strip())
    return {
        "type": "focus_groups",
        "title": "重点公司/产业消息",
        "summary": "宁德、英伟达、半导体上游材料三条固定关注线。",
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
        one_word = "、".join(f"{x['name']}({x['code']})" for x in data.get("one_word_boards", [])[:8])
        lines.append(
            f"涨停池：涨停 {data.get('count')} 只，一字板 {data.get('one_word_count', 0)} 只，"
            f"行业集中：{industries or '无'}。一字板样例：{one_word or '无'}。"
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
    metal_news = sources.get("金属快讯")
    if metal_news and metal_news.ok:
        data = metal_news.data
        sample = "；".join(item.get("text", "")[:80] for item in data.get("items", [])[:5] if item.get("text"))
        lines.append(f"金属快讯：材料主题命中 {data.get('count')} 条。样例：{sample}")
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
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result = SourceResult("运行异常", False, {"traceback": tb}, error=error, elapsed_ms=0)
    report = {
        "date": date.today().isoformat(),
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
        ("金属快讯", collect_metal_news),
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
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report = {
        "date": date.today().isoformat(),
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
