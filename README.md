# Adailynews

A daily news for me. This repository now includes a mobile-friendly A-share intelligence PWA and daily GitHub Actions report workflow, built on top of the a-stock-data toolkit.

# a-stock-data

A 股全栈数据工具包 — 6 层架构 · 15 个端点 · 7 个数据源实测

一个自包含的 Skill 文件，把分散在 7 个数据源里的 A 股原始数据整合成 AI 编程助手直接能用的工具集。你不用再背 mootdx 的 K 线参数、东财的 PDF Referer 头、iwencai 的 X-Claw 鉴权——全部封装好了。

> 兼容 [Claude Code](https://github.com/anthropics/claude-code) · [Codex](https://github.com/openai/codex) · [OpenClaw](https://github.com/anthropics/openclaw)
>
> Skill 文件本质是结构化 Markdown + 内嵌 Python，任何支持上下文注入的 AI 编程助手都能用。

---

## Donate

如果这个工具帮到了你的投研工作流，欢迎请作者喝杯咖啡 ☕

<p align="center">
  <img src="./assets/wechat-sponsor.jpg" width="240" alt="微信赞赏码">
</p>
<p align="center">
  <a href="https://ifdian.net/a/simonlin">爱发电</a> ·
  <a href="https://buymeacoffee.com/simonlin1212">Buy Me a Coffee</a>
</p>

> 想要什么数据端点？欢迎开 [Issue](https://github.com/simonlin1212/a-stock-data/issues) 提需求，赞助者的 Issue 优先处理。

---

## 架构

```
A 股全栈数据 · 六层架构
│
├── 行情层    mootdx + 腾讯财经       K线 + 五档盘口 + PE/PB/市值/换手率
├── 研报层    东财 + akshare + iwencai 研报列表 / PDF下载 / 一致预期 / NL搜索
├── 信号层    同花顺热点 + 北向资金    当日强势股 + 题材归因 + 北向分钟流向
├── 新闻层    akshare × 3              个股新闻 / 财联社快讯 / 全球资讯
├── 基础数据  mootdx finance / F10     37字段季报 + 9类公司资料
└── 公告层    巨潮 cninfo + mootdx     沪深北全量公告
```

---

## 快速开始

**3 步，2 分钟。**

```bash
# 1. 创建 skill 目录
mkdir -p ~/.claude/skills/a-stock-data

# 2. 把 SKILL.md 放进去
curl -o ~/.claude/skills/a-stock-data/SKILL.md \
  https://raw.githubusercontent.com/simonlin1212/a-stock-data/main/SKILL.md

# 3. 安装依赖
pip install mootdx akshare requests pandas
```

启动 Claude Code，说一句「帮我看看 688017 的估值」，自动激活。

> **Codex / OpenClaw 用户：** 把 SKILL.md 的内容贴入你的系统 prompt 或项目上下文文件即可，内嵌的 Python 代码可直接执行。

---

## 15 个端点能力清单

### 行情层（实时，不封 IP）

| 端点 | 数据 |
|------|------|
| mootdx K 线 | 日/周/月/1m/5m/15m/30m/60m |
| mootdx 盘口 | 五档买卖盘 + 实时报价 46 字段 |
| mootdx 逐笔 | 每笔成交明细（时间/价格/量/买卖方向） |
| 腾讯财经 | PE(TTM) / PB / 总市值 / 流通市值 / 换手率 / 涨跌停价 |

### 研报层

| 端点 | 数据 |
|------|------|
| 东财 reportapi | 研报列表 + 评级 + 三年 EPS 预测 |
| 东财 PDF 下载 | 完整研报 PDF（已处理 Referer 鉴权） |
| akshare 一致预期 | 同花顺源机构一致预期 EPS |
| iwencai NL 搜索 | 自然语言跨主题研报检索 |

### 信号层

| 端点 | 数据 |
|------|------|
| 同花顺热点 | 当日强势股 + 题材归因 reason tags（编辑部人工标注） |
| 同花顺北向（实时） | 沪股通 / 深股通分钟级流向（262 个时间点） |
| 同花顺北向（历史） | 北向资金日级历史 |

### 新闻层

| 端点 | 数据 |
|------|------|
| 个股新闻 | 东财个股新闻流 |
| 财联社快讯 | 分钟级电报 |
| 全球资讯 | 东财全球财经资讯 |

### 基础数据 + 公告

| 端点 | 数据 |
|------|------|
| 季报快照 | 37 字段（EPS / ROE / 净利润 / 主营收入...） |
| F10 公司资料 | 9 大类文本（公司概况 / 股东研究 / 行业分析...） |
| 巨潮公告 | 沪深北交所全量公告 |

### 鉴权要求

6 个数据源**完全免费无 Key**，仅 iwencai 语义搜索需要 API Key（[申请地址](https://www.iwencai.com/skillhub)）。

---

## 使用示例

跟你的 AI 助手说这些话就能激活：

| 场景 | 说什么 |
|------|--------|
| 个股估值 | 「帮我估一下 688017，给我 PE / PEG / 消化时间」 |
| 题材归因 | 「今天哪些股票走强，主要是什么题材」 |
| 研报检索 | 「人形机器人产业链最近的研报，特别是丝杠和减速器」 |
| 北向资金 | 「今天北向资金流入流出怎么样」 |
| 新闻公告 | 「拉一下 300476 最近的新闻和公告」 |
| 批量对比 | 「帮我对比这 5 只半导体股的估值」 |

### 内置 4 套调研流程

| 流程 | 做什么 | 耗时 |
|------|--------|------|
| 单票估值 | 实时价 → 一致预期 EPS → 前向 PE / PEG / PE 消化年数 | 30 秒 |
| 批量对比 | 多只股票横向估值排列 | 1 分钟 |
| 主题研报 | iwencai 多关键词 NL 搜索 + 东财 PDF 交叉补充 | 2 分钟 |
| 新标的调研 | 机构覆盖检查 → 估值 → 壁垒判断 | 1 分钟 |

---

## 数据源优先级

| 优先级 | 数据源 | 协议 | 封 IP 风险 |
|--------|--------|------|-----------|
| 1 | mootdx | TCP (7709) | 极低 |
| 2 | 腾讯财经 | HTTP | 低 |
| 3 | akshare | Python | 中（东财源） |
| 4 | iwencai | OpenAPI | 低（需 Key） |
| 5 | 东财 PDF | HTTP | 低 |
| 6 | 同花顺热点 | HTTP | 极低（零鉴权） |
| 7 | 同花顺北向 | HTTP | 极低（零鉴权） |

---

## FAQ

**Q: mootdx 和腾讯有什么区别？**
互补。mootdx = 交易层（价格 + 盘口 + K 线），腾讯 = 估值层（PE / PB / 市值 / 换手率 / 涨跌停价）。两者都不封 IP。

**Q: 腾讯 API 字段 43 是 PB 吗？**
不是。43 = 振幅%，46 = PB。网上大量教程写错了，这里是实测校准结果。

**Q: akshare 报超时？**
东财源有反爬，加 `time.sleep(1~3)` 重试。行情请走 mootdx，不受影响。

**Q: iwencai 返回 401？**
检查：(1) API Key 有效性 (2) 是否携带了 X-Claw-* Headers。SkillHub 2.0 后强制要求。

**Q: 同花顺热点 reason 字段为空？**
盘后数据还没更新，15:30 之后再调。个别 ST 股没有人工标注，`dropna` 过滤即可。

**Q: 不用 Claude Code，能用吗？**
能。SKILL.md 本质是 Markdown + 内嵌 Python 代码。Codex、OpenClaw 或任何 AI 编程助手都能读取。你也可以直接把 Python 代码段复制出来在自己的脚本里跑。

---

## 更新日志

见 [CHANGELOG.md](./CHANGELOG.md)。

---

## Disclaimer

本项目仅提供数据获取工具，不构成任何投资建议。股市有风险，投资需谨慎。

---

## License

[Apache License 2.0](./LICENSE) — 自由使用，注明出处即可。

**作者：** Simon 林 · 抖音「Simon林」 · 公众号「硅基世纪」

---

<details>
<summary><b>🇬🇧 English</b></summary>

# a-stock-data

Full-stack data toolkit for China A-Share market — 6-layer architecture · 15 endpoints · 7 data sources, battle-tested

A self-contained Skill file that consolidates raw A-share data from 7 sources into a ready-to-use toolkit for AI coding assistants. No need to memorize mootdx candlestick parameters, Eastmoney PDF Referer headers, or iwencai X-Claw authentication — it's all handled.

> Compatible with [Claude Code](https://github.com/anthropics/claude-code) · [Codex](https://github.com/openai/codex) · [OpenClaw](https://github.com/anthropics/openclaw)
>
> The Skill file is structured Markdown + embedded Python. Any AI coding assistant with context injection can use it.

---

## Architecture

```
China A-Share Full-Stack Data · 6-Layer Architecture
│
├── Market Data    mootdx + Tencent Finance     Candlesticks + Level-2 Order Book + PE/PB/Market Cap/Turnover
├── Research       Eastmoney + akshare + iwencai Report list / PDF download / Consensus EPS / NL search
├── Signals        THS Hot Stocks + Northbound   Today's movers + Sector attribution + Minute-level fund flow
├── News           akshare × 3                   Stock news / CLS flash / Global finance
├── Fundamentals   mootdx finance / F10          37-field quarterly report + 9 categories of company data
└── Filings        cninfo + mootdx               Full filings across SSE / SZSE / BSE
```

---

## Quick Start

**3 steps, 2 minutes.**

```bash
# 1. Create skill directory
mkdir -p ~/.claude/skills/a-stock-data

# 2. Download SKILL.md
curl -o ~/.claude/skills/a-stock-data/SKILL.md \
  https://raw.githubusercontent.com/simonlin1212/a-stock-data/main/SKILL.md

# 3. Install dependencies
pip install mootdx akshare requests pandas
```

Launch Claude Code and say "Check the valuation of 688017" — the skill activates automatically.

> **Codex / OpenClaw users:** Paste the contents of SKILL.md into your system prompt or project context file. The embedded Python code is ready to execute.

---

## 15 Endpoints

### Market Data (real-time, no IP ban)

| Endpoint | Data |
|----------|------|
| mootdx Candlesticks | Daily / Weekly / Monthly / 1m / 5m / 15m / 30m / 60m |
| mootdx Order Book | Level-2 bid/ask + real-time quote (46 fields) |
| mootdx Tick-by-tick | Every trade (time / price / volume / direction) |
| Tencent Finance | PE(TTM) / PB / Market Cap / Float Cap / Turnover / Price Limits |

### Research Reports

| Endpoint | Data |
|----------|------|
| Eastmoney reportapi | Report list + ratings + 3-year EPS forecasts |
| Eastmoney PDF | Full research report PDF (Referer auth handled) |
| akshare Consensus | Institutional consensus EPS (THS source) |
| iwencai NL Search | Natural language cross-topic report search |

### Signals

| Endpoint | Data |
|----------|------|
| THS Hot Stocks | Today's strong stocks + sector attribution tags (editorial annotations) |
| THS Northbound (real-time) | Shanghai/Shenzhen Connect minute-level flow (262 data points) |
| THS Northbound (historical) | Daily historical northbound fund flow |

### News

| Endpoint | Data |
|----------|------|
| Stock News | Eastmoney per-stock news feed |
| CLS Flash | Minute-level telegrams |
| Global News | Eastmoney global finance news |

### Fundamentals + Filings

| Endpoint | Data |
|----------|------|
| Quarterly Snapshot | 37 fields (EPS / ROE / Net Profit / Revenue...) |
| F10 Company Data | 9 categories (Overview / Shareholders / Industry...) |
| cninfo Filings | Full filings across all exchanges |

### Authentication

6 data sources are **completely free, no API key needed**. Only iwencai semantic search requires an API key ([apply here](https://www.iwencai.com/skillhub)).

---

## Usage Examples

Just tell your AI assistant:

| Scenario | Prompt |
|----------|--------|
| Valuation | "Estimate 688017 — give me PE / PEG / payback period" |
| Sector Attribution | "Which stocks are strong today and what sectors are driving them" |
| Research Reports | "Latest reports on humanoid robot supply chain, especially ball screws and reducers" |
| Northbound Flow | "How's northbound capital flow looking today" |
| News & Filings | "Pull recent news and filings for 300476" |
| Batch Compare | "Compare valuations of these 5 semiconductor stocks" |

### 4 Built-in Research Workflows

| Workflow | What it does | Time |
|----------|-------------|------|
| Single Stock Valuation | Live price → Consensus EPS → Forward PE / PEG / PE payback years | 30 sec |
| Batch Comparison | Side-by-side valuation ranking | 1 min |
| Thematic Research | iwencai multi-keyword NL search + Eastmoney PDF cross-reference | 2 min |
| New Target Research | Institutional coverage check → Valuation → Moat assessment | 1 min |

---

## Data Source Priority

| Priority | Source | Protocol | IP Ban Risk |
|----------|--------|----------|-------------|
| 1 | mootdx | TCP (7709) | Very low |
| 2 | Tencent Finance | HTTP | Low |
| 3 | akshare | Python | Medium (Eastmoney source) |
| 4 | iwencai | OpenAPI | Low (key required) |
| 5 | Eastmoney PDF | HTTP | Low |
| 6 | THS Hot Stocks | HTTP | Very low (zero auth) |
| 7 | THS Northbound | HTTP | Very low (zero auth) |

---

## Disclaimer

This project provides data access tools only and does not constitute investment advice. Investing involves risk.

---

## License

[Apache License 2.0](./LICENSE)

**Author:** Simon Lin · TikTok [@simonlin121212](https://www.tiktok.com/@simonlin121212) · Douyin "Simon林" · WeChat Official Account "硅基世纪"

</details>
