#!/bin/bash
# 接好 API（只需要做一次，换密钥时再做一次）：先把密钥复制到剪贴板，再运行本脚本。
#   1. 从剪贴板读密钥（不显示在屏幕上，不写进任何文件），读完清空剪贴板；
#   2. 直接问一次 Claude API 这个密钥认不认（查模型列表，不花钱）；
#   3. 把密钥存进 macOS 钥匙串（服务名 four-evidence-anthropic-key）；
#   4. 装好自动启动和每天的数据刷新（scripts/install_agents.sh），用新密钥重启面板。
# 之后重启电脑、重新登录，面板都会自己起来，并从钥匙串取密钥，不用再复制。
# 停止面板：./stop.sh      彻底取消自动启动：scripts/uninstall_agents.sh      日志：logs/
set -u
cd "$(dirname "$0")"
PORT="${FE_PORT:-$(python3 -c "import json;print(json.load(open('config.json')).get('port',8777))" 2>/dev/null || echo 8777)}"
SERVICE="${FE_KEYCHAIN_SERVICE:-four-evidence-anthropic-key}"
PREFIX="${FE_AGENT_PREFIX:-com.zaki.four-evidence}"

# 端口被别的程序（不是这个面板）占着：换下一个空闲端口，记进 config.json，自动启动就固定用它
port_owner_is_us() {
  local pid; pid="$(lsof -nP -t -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | head -1)"
  [ -z "$pid" ] && return 0
  [ "$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')" = "$(pwd -P)" ] && ps -o command= -p "$pid" | grep -q 'server\.py'
}
if [ -z "${FE_PORT:-}" ] && ! port_owner_is_us "$PORT"; then
  OLD="$PORT"
  for P in $(seq "$PORT" $((PORT + 30))); do
    lsof -nP -t -iTCP:"$P" -sTCP:LISTEN >/dev/null 2>&1 || { PORT="$P"; break; }
  done
  python3 -c "import json;p='config.json';c=json.load(open(p,encoding='utf-8'));c['port']=$PORT;json.dump(c,open(p,'w',encoding='utf-8'),ensure_ascii=False,indent=2)"
  echo "✓ 端口 ${OLD} 被别的程序占用，面板改用 ${PORT}（已记进 config.json）。"
fi

if [ "${FE_KEY_FROM_STDIN:-}" = "1" ]; then KEY="$(cat)"; else KEY="$(pbpaste 2>/dev/null)"; fi
KEY="$(printf '%s' "$KEY" | tr -d '[:space:]')"
FROM=clipboard
case "$KEY" in sk-ant-*) ;; *)
  # 剪贴板里没有密钥：先用钥匙串里已存的（最近一次存的就是它）；钥匙串也没有，
  # 再看这个目录的面板是否正带着密钥在跑，沿用它那个（只在本机进程之间传，不显示）
  KEY="$(/usr/bin/security find-generic-password -a "$USER" -s "$SERVICE" -w 2>/dev/null)"
  case "$KEY" in sk-ant-*) FROM=keychain ;; *)
    PID="$(lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1)"
    if [ -n "$PID" ] && [ "$(lsof -a -p "$PID" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')" = "$(pwd -P)" ]; then
      KEY="$(ps -wwE -p "$PID" -o command= 2>/dev/null | tr ' ' '\n' | sed -n 's/^ANTHROPIC_API_KEY=//p' | head -1)"
    else
      KEY=""
    fi
    case "$KEY" in sk-ant-*) FROM=running ;; esac ;;
  esac
  case "$KEY" in
    sk-ant-*) if [ "$FROM" = keychain ]; then echo "✓ 剪贴板里没有密钥，改用钥匙串里已存的密钥。"
              else echo "✓ 剪贴板里没有密钥，改用正在运行的面板里那个密钥。"; fi ;;
    *) if [ "${#KEY}" -eq 0 ]; then echo "✗ 剪贴板是空的，正在运行的面板里也没有密钥。"
       else echo "✗ 剪贴板里的内容不像 API 密钥（密钥以 sk-ant- 开头）。"; fi
       echo "  控制台不会再显示已经建好的密钥，请在 https://platform.claude.com 的 API Keys 页面新建一个，点复制，再运行一次。什么都没有改动。"
       exit 1 ;;
  esac ;;
esac
if printf '%s' "$KEY" | LC_ALL=C grep -q '[^A-Za-z0-9_-]'; then
  echo "✗ 剪贴板里的密钥夹着不该有的字符（可能多复制了别的内容）。请重新复制，再运行一次。什么都没有改动。"
  exit 1
fi
if [ "$FROM" = clipboard ]; then
  [ "${FE_KEY_FROM_STDIN:-}" = "1" ] || printf '' | pbcopy
  echo "✓ 读到密钥：类型 $(printf '%s' "$KEY" | cut -d- -f1-3)，长度 ${#KEY}。剪贴板已清空。"
else
  echo "✓ 密钥类型 $(printf '%s' "$KEY" | cut -d- -f1-3)，长度 ${#KEY}。"
fi

# 直接问 API（密钥走标准输入交给 curl，不出现在命令行里）
CODE="$(printf 'header = "x-api-key: %s"\nheader = "anthropic-version: 2023-06-01"\n' "$KEY" \
  | curl -s -m 25 -o /dev/null -w '%{http_code}' -K - https://api.anthropic.com/v1/models 2>/dev/null)"
case "$CODE" in
  200) echo "✓ 密钥检查：有效。" ;;
  401) echo "✗ 密钥检查：Claude API 不认这个密钥（401）。它可能已被删除，或者不是控制台 API Keys 页面生成的那种密钥。"
       echo "  密钥照样存进钥匙串、面板照常启动，但“AI 分析当前图表”会报密钥无效。" ;;
  403) echo "✓ 密钥检查：API 认得这个密钥（它不能查模型列表，返回 403；sk-ant-usr 类型的密钥就是这样，解读请求能正常用）。" ;;
  000|"") echo "？密钥检查：连不上 api.anthropic.com（网络或代理的问题），没法确认密钥是否有效。" ;;
  *) echo "？密钥检查：API 返回 ${CODE}，没法确认密钥是否有效。" ;;
esac

# 存进钥匙串：命令走 security 的标准输入，密钥不出现在进程列表里；同名旧密钥会被覆盖（-U）
if printf 'add-generic-password -U -a %s -s %s -l %s -w %s\n' "$USER" "$SERVICE" "$SERVICE" "$KEY" | /usr/bin/security -i >/dev/null 2>&1 \
   && /usr/bin/security find-generic-password -a "$USER" -s "$SERVICE" >/dev/null 2>&1; then
  echo "✓ 密钥已存进钥匙串（${SERVICE}）。"
else
  echo "✗ 存钥匙串失败。面板这次不会带上密钥；请再运行一次本脚本，或把这句话告诉 Claude。"
fi
unset KEY

# 装好/更新自动启动和定时刷新，并（重新）启动面板，让它从钥匙串取新密钥
FE_PORT="$PORT" FE_AGENT_PREFIX="$PREFIX" FE_KEYCHAIN_SERVICE="$SERVICE" scripts/install_agents.sh | sed 's/^/  /'

for _ in $(seq 1 240); do curl -s -m 2 -o /dev/null "http://localhost:$PORT/api/meta" && break; sleep 0.5; done
curl -s -m 5 "http://localhost:$PORT/api/meta" | python3 -c "
import json, sys
try:
    a = json.load(sys.stdin)['ai']
    print('✓ 面板已在后台运行。AI 解读：' + ('可用，模型 ' + a['model'] if a['enabled'] else '不可用。' + a['reason']))
except Exception:
    print('✗ 面板没有启动成功，看 logs/panel.log 最后几行。')
"
echo "  打开 http://localhost:$PORT    独立窗口：$(pwd)/open_window.sh    停止：$(pwd)/stop.sh"
