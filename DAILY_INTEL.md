# A股情报雷达运行说明

本项目同时提供本地 PWA 和 GitHub Pages 两种运行方式。两者使用同一套报告结构与前端渲染逻辑，但生成方式不同。

## 在线版

访问地址：

```text
https://yuuu96.github.io/Adailynews/
```

GitHub Pages 托管的是静态页面，不需要个人电脑或本地进程在线。报告由 GitHub Actions 在云端生成并部署。

### 自动更新时间

| 日期 | 北京时间 | UTC cron |
| --- | --- | --- |
| 周一至周五 | 08:56 | `56 0 * * 1-5` |
| 周一至周五 | 18:58 | `58 10 * * 1-5` |
| 周六 | 不更新 | 无 |
| 周日 | 18:58 | 包含在 `58 10 * * 0-5` |

工作流将周日晚间与工作日晚间合并为 `58 10 * * 0-5`。GitHub Actions 不保证秒级准时，繁忙时可能延迟数分钟。

页面顶部的“刷新报告”只会绕过浏览器缓存，重新读取云端最近一次生成的 `latest.json`。它不会启动 Python 采集任务，也不会重新部署网站。

需要立即生成时，进入 GitHub 仓库的 `Actions` 页面，选择 `Daily A-share Intelligence`，点击 `Run workflow`。手动运行不受星期和时间限制。

## 本地版

安装依赖后启动：

```bash
cd /path/to/Adailynews
python3 -m venv .venv
source .venv/bin/activate
pip install requests pandas akshare mootdx
python3 intel_web.py
```

本机打开：

```text
http://127.0.0.1:8765
```

同一 Wi-Fi 下允许手机访问：

```bash
python3 intel_web.py --host 0.0.0.0 --port 8765
```

然后在手机浏览器打开 `http://电脑局域网IP:8765`。该地址只在电脑运行服务且设备处于同一可访问网络时有效。

本地页面提供：

- “一键生成”：启动完整数据采集任务
- “刷新最新”：读取本地最近一次报告
- 采集阶段、进度、等待时间和预计剩余时间
- 可选 DeepSeek API Key 输入

## DeepSeek

AI 摘要不是生成报告的必要条件。没有 Key 时，原始聚合、规则摘要、交易准备卡和九个模块仍会生成。

本地环境变量：

```bash
export DEEPSEEK_API_KEY="你的 key"
export DEEPSEEK_MODEL="deepseek-v4-pro"
python3 intel_web.py
```

也可以在本地页面输入 Key。勾选“仅保存在本机浏览器”后，Key 会保存到当前浏览器的 `localStorage`，不会写入项目文件。

云端自动摘要应在 GitHub 仓库中配置 Secret：

```text
Settings -> Secrets and variables -> Actions -> DEEPSEEK_API_KEY
```

不要将真实 API Key 写入代码、配置文件或提交历史。

## 报告输出

本地生成结果保存在：

```text
reports/daily/YYYY-MM-DD.md
reports/daily/YYYY-MM-DD.json
reports/daily/latest.md
reports/daily/latest.json
```

板块连续性历史保存在：

```text
reports/sector_radar/history.jsonl
```

GitHub Actions 会持久化板块历史，再由 `build_static_site.py` 将最新报告构建到 `site/` 并部署到 Pages。

## 本地接口

- `GET /`：移动端页面
- `POST /api/run`：启动生成任务
- `GET /api/job/{job_id}`：读取生成进度和结果
- `GET /api/latest`：读取最新本地报告

## 自定义配置

统一配置文件为：

```text
config/intel_config.json
```

它控制产业链观察股票、重点消息关键词、事件分组、指定分析师和交易准备卡数量。配置字段缺失时，生成器会回退到代码中的默认值。

## GitHub Pages 首次部署

1. 在仓库 `Settings -> Pages` 中选择 `GitHub Actions` 作为 Source。
2. 如需 AI 摘要，在 Actions Secrets 中添加 `DEEPSEEK_API_KEY`。
3. 手动运行一次 `Daily A-share Intelligence`。
4. 等待 `Generate report`、`Build static site` 和 `Deploy to GitHub Pages` 全部完成。
5. 打开 `https://yuuu96.github.io/Adailynews/`。

若工作流失败，应先查看失败步骤日志。任一数据源采集失败通常只会形成状态警告，不应终止整份报告；构建或 JSON 序列化错误则会使工作流失败。
