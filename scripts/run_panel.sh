#!/bin/bash
# 登录后由 launchd 启动面板（com.zaki.four-evidence.panel）。也可以手动运行。
# 密钥从 macOS 钥匙串读（服务名 four-evidence-anthropic-key），只放进这个进程的环境变量，不落文件、不进日志。
# 钥匙串里没有密钥时面板照常运行，只是 AI 解读不可用。
cd "$(dirname "$0")/.."
SERVICE="${FE_KEYCHAIN_SERVICE:-four-evidence-anthropic-key}"
KEY="$(/usr/bin/security find-generic-password -a "$USER" -s "$SERVICE" -w 2>/dev/null)"
if [ -n "$KEY" ]; then
  export ANTHROPIC_API_KEY="$KEY"
  echo "$(date '+%F %T') 启动面板（钥匙串里有密钥）"
else
  unset ANTHROPIC_API_KEY
  echo "$(date '+%F %T') 启动面板（钥匙串里没有密钥，AI 解读不可用；运行 start_with_key.sh 存一次）"
fi
unset KEY
exec ./start.sh
