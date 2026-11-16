#!/bin/bash
# 四要素交易面板：一条命令启动。  用法：./start.sh
# 端口默认 8777；被别的程序占用时自动换下一个空闲端口，实际地址会打印在终端里，并自动打开浏览器。
# AI 解读需要先在 shell 里 export ANTHROPIC_API_KEY=...；不设也能用，只是那个按钮是灰的。
set -u
cd "$(dirname "$0")"

PY=.venv/bin/python
if [ ! -x "$PY" ]; then
  echo "第一次启动：创建 .venv ..."
  if command -v uv >/dev/null 2>&1; then
    uv venv --quiet --python 3.10 .venv || uv venv --quiet .venv
  else
    for c in python3.13 python3.12 python3.11 python3.10 python3; do
      if command -v "$c" >/dev/null 2>&1; then "$c" -m venv .venv && break; fi
    done
  fi
fi

if [ -x "$PY" ]; then
  # 依赖只在 requirements.txt 变了以后重装
  if [ ! -f .venv/.deps-ok ] || [ requirements.txt -nt .venv/.deps-ok ]; then
    echo "安装依赖 ..."
    if command -v uv >/dev/null 2>&1; then
      uv pip install --quiet --python "$PY" -r requirements.txt && touch .venv/.deps-ok
    else
      "$PY" -m pip install --quiet -r requirements.txt && touch .venv/.deps-ok
    fi
    [ -f .venv/.deps-ok ] || echo "依赖没装全（可能没网）。面板照常启动，AI 解读可能不可用。"
  fi
fi

# .venv 建不起来或缺 numpy 时退回系统 python3（只要有 numpy 就能跑，AI 解读除外）
if [ ! -x "$PY" ] || ! "$PY" -c "import numpy" >/dev/null 2>&1; then
  PY=$(command -v python3)
  "$PY" -c "import numpy" >/dev/null 2>&1 || { echo "缺少 numpy，装不上依赖也没有可用的系统 Python。"; exit 1; }
fi

[ -t 1 ] && export FE_OPEN=1      # 在终端里手动运行时，起来后自动打开浏览器
exec "$PY" server.py
