#!/bin/bash
# 用无头 Chrome 跑界面自检，输出一行 JSON。
# 用法：tests/run_selftest.sh [端口，默认 8777] [附加的查询串，例如 pfhelper=9001]
PORT="${1:-8777}"
EXTRA="${2:-}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
[ -x "$CHROME" ] || { echo '{"skip":"没有找到 Google Chrome"}'; exit 0; }
PROFILE="$(mktemp -d)"
"$CHROME" --headless=new --disable-gpu --no-first-run --user-data-dir="$PROFILE" --window-size=1600,960 \
  --virtual-time-budget=400000 --dump-dom "http://localhost:$PORT/?t=SPCX&selftest=1${EXTRA:+&$EXTRA}" 2>/dev/null \
  | python3 -c "import sys,re,html; m=re.search(r'<pre id=\"selftest\">(.*?)</pre>', sys.stdin.read(), re.S); print(html.unescape(m.group(1)) if m else '{\"error\":\"自检没有跑完\"}')"
rm -rf "$PROFILE"
