#!/bin/bash
# 用无头 Chrome 给正在运行的面板截三张验收图，放到 screenshots/。先 ./start.sh 把面板跑起来。
# 用法：tests/take_screenshots.sh [端口，默认 8777]
set -u
cd "$(dirname "$0")/.."
PORT="${1:-8777}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE="$(mktemp -d)"
shot() {  # 文件名  查询串  宽  高
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --no-first-run --user-data-dir="$PROFILE" \
    --window-size="$3,$4" --virtual-time-budget=9000 --screenshot="screenshots/$1" "http://localhost:$PORT/?$2" >/dev/null 2>&1
  [ -s "screenshots/$1" ] && echo "已保存 screenshots/$1" || echo "截图失败 $1"
}
mkdir -p screenshots
shot 01_main_chart_SPCX_2026-11-13.png      "t=SPCX&side=0"                1600 960
shot 02_evidence_4of4_NVDA_2025-05-13.png   "t=NVDA&asof=2025-05-13&side=0" 1600 960
shot 03_ai_sidebar_QQQ_2009-03-18.png       "t=QQQ&asof=2009-03-18&side=1"  1600 960
shot portfolio.png                          "view=portfolio"                1500 2300
shot 04_portfolio_overlay_SPCX.png          "t=SPCX&pf=1&side=0"            1600 960
rm -rf "$PROFILE"
