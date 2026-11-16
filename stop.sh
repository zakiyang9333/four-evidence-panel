#!/bin/bash
# 停掉面板。只停这个目录的面板，别的程序不动。
# 装了自动启动的话，这里只是先停下来，下次登录还会自动启动；彻底取消用 scripts/uninstall_agents.sh。
set -u
cd "$(dirname "$0")"
PORT="${FE_PORT:-$(python3 -c "import json;print(json.load(open('config.json')).get('port',8777))" 2>/dev/null || echo 8777)}"
LABEL="${FE_AGENT_PREFIX:-com.zaki.four-evidence}.panel"
if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  launchctl bootout "gui/$(id -u)/$LABEL" && echo "已停止面板（自动启动的那个；下次登录会再自动启动）。"
  for _ in $(seq 1 20); do lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 || break; sleep 0.25; done
fi
PID="$(lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1)"
if [ -z "$PID" ]; then echo "面板现在没有在运行（端口 $PORT 空着）。"; exit 0; fi
CWD="$(lsof -a -p "$PID" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')"
if [ "$CWD" = "$(pwd -P)" ] && ps -o command= -p "$PID" | grep -q 'server\.py'; then
  kill "$PID" && echo "已停止面板（端口 ${PORT}）。"
  for _ in $(seq 1 20); do lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 || break; sleep 0.25; done
else
  echo "端口 $PORT 上是别的程序，不是这个面板，没有动它。"
  exit 1
fi
