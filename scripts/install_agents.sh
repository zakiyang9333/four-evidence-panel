#!/bin/bash
# 安装两个 launchd 任务（只动本面板自己的两个 plist，别的不碰）：
#   com.zaki.four-evidence.panel    登录后自动启动面板，挂了自动拉起
#   com.zaki.four-evidence.refresh  周二到周六台北 06:30、08:30、10:30 刷新日线（美股收盘后）
# 用法：scripts/install_agents.sh [--no-panel]     卸载：scripts/uninstall_agents.sh
# --no-panel 只装刷新任务（例如面板正被别的方式占用着端口时）。
set -u
cd "$(dirname "$0")/.."
DIR="$(pwd -P)"
LA="$HOME/Library/LaunchAgents"
UIDN="$(id -u)"
PORT="${FE_PORT:-$(python3 -c "import json;print(json.load(open('config.json')).get('port',8777))" 2>/dev/null || echo 8777)}"
PREFIX="${FE_AGENT_PREFIX:-com.zaki.four-evidence}"      # 测试时换一个前缀，不碰正式的任务
SUFFIX="${PREFIX#com.zaki.four-evidence}"
mkdir -p "$LA" logs
chmod +x scripts/*.sh start.sh start_with_key.sh stop.sh open_window.sh 2>/dev/null

# 代理：照抄当前终端里的设置（这台 Mac 访问外网走本机代理），没有就不写
ENVXML="<key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>"
for v in HTTPS_PROXY HTTP_PROXY NO_PROXY https_proxy http_proxy no_proxy; do
  val="$(printenv "$v")"
  case "$val" in ""|*@*|*"<"*|*"&"*) ;; *) ENVXML="$ENVXML<key>$v</key><string>$val</string>" ;; esac
done
[ -n "${FE_KEYCHAIN_SERVICE:-}" ] && ENVXML="$ENVXML<key>FE_KEYCHAIN_SERVICE</key><string>$FE_KEYCHAIN_SERVICE</string>"
[ -n "$SUFFIX" ] && ENVXML="$ENVXML<key>FE_AGENT_PREFIX</key><string>$PREFIX</string>"

write_plist() {   # label  program  extra-xml
  cat > "$LA/$1.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$1</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$2</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>EnvironmentVariables</key><dict>$ENVXML<key>FE_PORT</key><string>$PORT</string></dict>
  <key>StandardOutPath</key><string>$DIR/logs/$4.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/$4.log</string>
  $3
</dict></plist>
EOF
}
reload() {
  launchctl bootout "gui/$UIDN/$1" 2>/dev/null
  launchctl bootstrap "gui/$UIDN" "$LA/$1.plist" && echo "✓ 已安装 $1"
}

CAL=""
for d in 2 3 4 5 6; do for h in 6 8 10; do
  CAL="$CAL<dict><key>Weekday</key><integer>$d</integer><key>Hour</key><integer>$h</integer><key>Minute</key><integer>30</integer></dict>"
done; done
if [ "${FE_NO_REFRESH_AGENT:-}" != "1" ]; then
  write_plist "$PREFIX.refresh" "$DIR/scripts/run_refresh.sh" "<key>StartCalendarInterval</key><array>$CAL</array>" "refresh$SUFFIX"
  reload "$PREFIX.refresh"
fi

if [ "${1:-}" != "--no-panel" ]; then
  # 端口被手动启动的面板占着时先停掉它（只停这个目录的 server.py）
  FE_PORT="$PORT" FE_AGENT_PREFIX="$PREFIX" ./stop.sh >/dev/null 2>&1
  write_plist "$PREFIX.panel" "$DIR/scripts/run_panel.sh" \
    "<key>RunAtLoad</key><true/><key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict><key>ThrottleInterval</key><integer>30</integer><key>ProcessType</key><string>Interactive</string><key>LimitLoadToSessionType</key><string>Aqua</string>" "panel$SUFFIX"
  reload "$PREFIX.panel"
fi
