#!/bin/bash
# 在独立窗口里打开面板（不用浏览器）。第一次运行会装 pywebview。
cd "$(dirname "$0")"
PY=.venv/bin/python
if ! "$PY" -c "import webview" >/dev/null 2>&1; then
  echo "第一次打开窗口：安装 pywebview ..."
  if command -v uv >/dev/null 2>&1; then uv pip install --quiet --python "$PY" -r requirements-window.txt
  else "$PY" -m pip install --quiet -r requirements-window.txt; fi
fi
exec "$PY" window.py
