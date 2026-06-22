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
]

SOURCE_TIMEOUTS = {
    "同花顺热点": 15,
    "北向资金": 15,
    "涨停池": 25,
    "产业新闻": 25,
    "机构研报": 25,
    "期指席位": 30,
    "产业链行情": 15,
}

SOURCE_DEFS: list[tuple[str, Callable[[], Any]]] = []

WATCHLIST = {
    "英伟达/AI算力": ["300502", "300308", "300394", "300476", "002463", "688256", "688041"],
    "半导体材料": ["688300", "300054", "688126", "603650", "002409", "688146", "600703"],
    "储能锂矿": ["300750", "002466", "002460", "002738", "002756", "300274", "002812"],
    "电网电力": ["601179", "600550", "600973", "002498", "002560", "600236", "000899"],
}

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
    for row in rows:
        name = row.get("名称")
        if not name or safe_float(row.get("最新价")) <= 0:
            continue
        industry = row.get("所属行业") or "未分类"
        industry_counter[industry] += 1
        cleaned.append(
            {
                "code": row.get("代码"),
                "name": name,
                "change_pct": safe_float(row.get("涨跌幅")),
                "latest": safe_float(row.get("最新价")),
                "amount_yi": round(safe_float(row.get("成交额")) / 1e8, 2),
                "board_count": row.get("连板数"),
                "industry": industry,
                "first_time": row.get("首次封板时间"),
                "break_count": row.get("炸板次数"),
            }
        )
    cleaned.sort(key=lambda item: item.get("amount_yi", 0), reverse=True)
    return {"date": d, "count": len(cleaned), "industry_top": industry_counter.most_common(15), "top": cleaned[:40]}


def text_from_record(record: dict[str, Any]) -> str:
    return " ".join(str(v) for v in record.values() if v is not None)


def is_theme_hit(text: str) -> bool:
    text_upper = text.upper()
    return any(keyword.upper() in text_upper for keyword in THEME_KEYWORDS)


def collect_news() -> dict[str, Any]:
    if ak is None:
        raise RuntimeError("akshare is not installed")
    items = []
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
                    items.append({"source": source_name, "text": text[:500], "raw": row})
        except Exception as exc:
            items.append({"source": source_name, "error": f"{type(exc).__name__}: {str(exc)[:180]}"})
    return {"count": len([item for item in items if "text" in item]), "items": items[:80]}


def classify_sentiment(text: str) -> str:
    pos = sum(1 for word in POSITIVE_WORDS if word in text)
    neg = sum(1 for word in NEGATIVE_WORDS if word in text)
    if pos > neg:
        return "偏多"
    if neg > pos:
        return "偏空"
    return "中性"


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
                "industry": row.get("indvInduName"),
                "rating": row.get("emRatingName"),
                "sentiment": sentiment,
            }
        )
    return {"count": len(hits), "sentiment": dict(sentiment_counter), "items": hits[:50]}


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
    return {"date": query_date, "count": len(normalized), "party_summary": summary_rows, "items": normalized}


def source_map(results: list[SourceResult]) -> dict[str, SourceResult]:
    return {result.name: result for result in results}


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
        lines.append(f"涨停池：涨停 {data.get('count')} 只，行业集中：{industries or '无'}。")
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
        zhongxin = [
            x
            for x in data.get("party_summary", [])
            if "中信" in x.get("party", "")
        ][:4]
        zhongxin_text = "；".join(
            f"{x['symbol']} 多{x['long_value']}/空{x['short_value']}/净{x['net_value']}"
            for x in zhongxin
        )
        lines.append(f"期指席位：{data.get('date')} 命中重点席位 {data.get('count')} 条。中信：{zhongxin_text or '未命中'}。")
    news = sources.get("产业新闻")
    if news and news.ok:
        data = news.data
        sample = "；".join(item.get("text", "")[:80] for item in data.get("items", [])[:5] if item.get("text"))
        lines.append(f"产业新闻：主题命中 {data.get('count')} 条。样例：{sample}")
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
    sections: list[dict[str, Any]] = []
    if ai_summary:
        bullets = [line.strip(" -") for line in ai_summary.splitlines() if line.strip()]
        sections.append({"title": "AI核心摘要", "items": bullets[:8]})
        return sections

    key_items = []
    ths = sources.get("同花顺热点")
    if ths and ths.ok:
        tags = "、".join(f"{tag}({n})" for tag, n in ths.data.get("tag_top", [])[:6])
        key_items.append(f"同花顺强势股 {ths.data.get('count')} 只；高频题材：{tags or '暂无'}")
    limit_up = sources.get("涨停池")
    if limit_up and limit_up.ok:
        industries = "、".join(f"{name}({n})" for name, n in limit_up.data.get("industry_top", [])[:6])
        key_items.append(f"涨停 {limit_up.data.get('count')} 只；集中行业：{industries or '暂无'}")
    north = sources.get("北向资金")
    if north and north.ok:
        data = north.data
        key_items.append(f"北向合计 {data.get('total_yi')} 亿，沪股通 {data.get('hgt_yi')} 亿，深股通 {data.get('sgt_yi')} 亿")
    reports = sources.get("机构研报")
    if reports and reports.ok:
        key_items.append(f"主题研报命中 {reports.data.get('count')} 篇；观点分布 {reports.data.get('sentiment')}")
    futures = sources.get("期指席位")
    if futures and futures.ok:
        key_items.append(f"期指重点席位命中 {futures.data.get('count')} 条，日期 {futures.data.get('date')}")
    if ai_error:
        key_items.append(f"AI摘要未生成：{ai_error}")
    sections.append({"title": "今日简报", "items": key_items or ["暂无可用摘要，请查看数据源状态。"]})

    reports = sources.get("机构研报")
    if reports and reports.ok:
        report_items = []
        for item in (reports.data.get("items") or [])[:10]:
            meta = " / ".join(
                part
                for part in [
                    item.get("date"),
                    item.get("org"),
                    item.get("sentiment"),
                    item.get("rating"),
                    item.get("industry"),
                ]
                if part
            )
            report_items.append(f"{meta}：{item.get('title')}")
        sections.append({"title": "主题研报精华", "items": report_items or ["暂无主题研报命中。"]})

    futures = sources.get("期指席位")
    if futures and futures.ok:
        futures_items = []
        summary = futures.data.get("party_summary") or []
        preferred = [x for x in summary if "中信" in x.get("party", "")]
        others = [x for x in summary if "中信" not in x.get("party", "")]
        for item in (preferred + others)[:12]:
            net = int(item.get("net_value") or 0)
            net_chg = int(item.get("net_chg") or 0)
            direction = "净多" if net > 0 else ("净空" if net < 0 else "持平")
            futures_items.append(
                f"{item.get('party')} {item.get('symbol')}："
                f"多单 {item.get('long_value')}({item.get('long_chg'):+}) / "
                f"空单 {item.get('short_value')}({item.get('short_chg'):+}) / "
                f"{direction} {abs(net)}({net_chg:+})"
            )
        sections.append({"title": "期指重点席位多空", "items": futures_items or ["暂无重点席位明细。"]})

    watch = sources.get("产业链行情")
    if watch and watch.ok:
        items = []
        for theme, quotes in watch.data.items():
            leaders = "、".join(f"{x['name']} {x['change_pct']}%" for x in quotes[:3])
            items.append(f"{theme}：{leaders or '暂无行情'}")
        sections.append({"title": "产业链观察", "items": items})

    failed = [f"{r.name}: {r.error}" for r in results if not r.ok]
    if failed:
        sections.append({"title": "口径限制", "items": failed[:6]})
    return sections


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
    dated_json = REPORT_DIR / f"{report['date']}.json"
    dated_md = REPORT_DIR / f"{report['date']}.md"
    for path in [dated_json, LATEST_JSON]:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for path in [dated_md, LATEST_MD]:
        path.write_text(report["markdown"], encoding="utf-8")
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
    report = generate_report()
    print(report["markdown"])


if __name__ == "__main__":
    main()
