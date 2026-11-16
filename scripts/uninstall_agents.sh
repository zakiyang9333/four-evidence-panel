#!/bin/bash
# 卸载本面板的两个 launchd 任务（停止自动启动和定时刷新）。数据、钥匙串里的密钥都不动。
# 顺便删掉钥匙串里的密钥：scripts/uninstall_agents.sh --forget-key
UIDN="$(id -u)"
for L in com.zaki.four-evidence.panel com.zaki.four-evidence.refresh; do
  launchctl bootout "gui/$UIDN/$L" 2>/dev/null && echo "已停止 $L"
  [ -f "$HOME/Library/LaunchAgents/$L.plist" ] && mv "$HOME/Library/LaunchAgents/$L.plist" "$HOME/.Trash/$L.plist.$(date +%s)" && echo "已把 $L.plist 移到废纸篓"
done
if [ "${1:-}" = "--forget-key" ]; then
  /usr/bin/security delete-generic-password -a "$USER" -s four-evidence-anthropic-key >/dev/null 2>&1 && echo "已从钥匙串删除密钥"
fi
