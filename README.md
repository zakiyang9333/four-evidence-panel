# 四要素观察面板 · 安装说明

一个本地运行的股票观察面板：用“抄底核心四要素”规则看 SPCX、NVDA、QQQ 的日线状态。只看收盘后的日线，不接券商、不下单。

**未验证，仅观察。回测证据不足，不是买入建议。**

## 需要

- 一台 Mac（自动启动、钥匙串、独立窗口都用到 macOS 的功能）
- 能访问 Yahoo Finance 和 GitHub 的网络
- 可选：Claude API 密钥，用来让 Claude 润色解说。没有也能用，解说会用免费的模板版

## 安装（第一次，约 3 分钟）

1. 装 uv（用来准备 Python 环境）。有 Homebrew 的话：

   ```bash
   brew install uv
   ```

   没有 Homebrew：

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. 下载并启动：

   ```bash
   git clone https://github.com/zakiyang9333/four-evidence-panel.git ~/four-evidence-panel
   cd ~/four-evidence-panel && ./start.sh
   ```

3. 浏览器打开 <http://localhost:8777>。在终端按 Ctrl+C 停止。

## 想让它开机自动运行、每天自动更新数据（可选）

先到 <https://platform.claude.com> 的 API Keys 页面复制一个密钥，然后运行：

```bash
~/four-evidence-panel/start_with_key.sh
```

它会把密钥存进 macOS 钥匙串，装好开机自动启动和每天美股收盘后的数据刷新。没有密钥的话，剪贴板空着运行也行，只是“让 Claude 润色”不可用。

停止：`~/four-evidence-panel/stop.sh`　彻底取消自动启动：`~/four-evidence-panel/scripts/uninstall_agents.sh`

## 更多

功能说明、数据规则和测试见 `README_APP.md`。
