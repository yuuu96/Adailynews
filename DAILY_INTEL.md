# A 股情报雷达试验版

本试验版提供一个本地移动端 PWA 页面，用于一键生成 A 股盘后情报日报。

## 运行

```bash
cd /Users/chenyutong/Downloads/a-stock-data-main
python3 intel_web.py
```

打开：

```text
http://127.0.0.1:8765
```

这个地址只允许本机访问。

同一 Wi-Fi 下用手机访问时：

```bash
python3 intel_web.py --host 0.0.0.0 --port 8765
```

然后在手机浏览器打开 `http://你的Mac局域网IP:8765`。

如果要“任何地方的移动端都能访问”，需要把服务部署到云服务器、Cloudflare/GitHub Actions 等云端环境；本地试验版在 Mac 关机、睡眠或不在同一网络时无法访问。

## DeepSeek

如果需要 AI 投研摘要，先设置：

```bash
export DEEPSEEK_API_KEY="你的 key"
```

默认模型是 `deepseek-v4-pro`，也可以覆盖：

```bash
export DEEPSEEK_MODEL="deepseek-v4-pro"
```

没有设置 key 时，系统仍会生成原始聚合报告，并在页面里标注 AI 摘要未生成。

也可以直接在网页顶部输入 DeepSeek API Key。页面只会把 key 传给本次 `/api/run` 任务；勾选“仅保存在本机浏览器”时，key 会保存在当前浏览器的 `localStorage`，不会写入项目文件。

## 进度

点击“一键生成”后，页面会显示：

- 当前采集阶段或数据源
- 进度条
- 已等待时间
- 根据当前进度估算的剩余时间

## 输出

报告会保存到：

```text
reports/daily/YYYY-MM-DD.md
reports/daily/YYYY-MM-DD.json
reports/daily/latest.md
reports/daily/latest.json
```

## 接口

- `GET /`：移动端页面
- `POST /api/run`：一键生成
- `GET /api/latest`：读取最新报告

## 云端免费版

仓库内置了 GitHub Pages + GitHub Actions 的免费部署骨架：

```text
.github/workflows/daily-intel.yml
build_static_site.py
web/static.html
```

### 定时

GitHub Actions 的 cron 只能使用 UTC。为了固定 **纽约时间 11:00**，工作流设置了两个 UTC 触发点：

```text
15:00 UTC  # 纽约夏令时 EDT 的 11:00
16:00 UTC  # 纽约冬令时 EST 的 11:00
```

工作流内部会再次检查 `America/New_York` 当前时间，只有纽约时间正好 11:00 才真正生成报告。

### DeepSeek API

推荐把 key 放进 GitHub Secrets：

```text
DEEPSEEK_API_KEY
```

这样每天定时生成时会自动带 AI 摘要。

静态页面也保留了一个可选 API 输入框，可以对当前页面已有数据重新摘要。这个 key 只保存在当前浏览器；如果浏览器跨域限制阻止调用 DeepSeek，请使用 GitHub Secret 方式。

### 部署步骤

1. 把仓库推到 GitHub。
2. 在仓库 `Settings -> Secrets and variables -> Actions` 添加 `DEEPSEEK_API_KEY`。
3. 在 `Settings -> Pages` 选择 `GitHub Actions` 作为部署来源。
4. 手动运行一次 `Daily A-share Intelligence` 工作流。
5. 打开 GitHub Pages 链接，在手机上访问。
