#!/bin/bash
# 每天美股收盘后由 launchd 运行（com.zaki.four-evidence.refresh）：只往 data/*.csv 追加新日线，结果写 data/last_refresh.json。
# 来源还没出数据时这次就什么都不写，下一个时间点再试。
cd "$(dirname "$0")/.."
PY=.venv/bin/python
[ -x "$PY" ] || PY=$(command -v python3)
echo "$(date '+%F %T') 定时刷新开始"
FE_REFRESH_TRIGGER=schedule "$PY" prep_data.py
echo "$(date '+%F %T') 定时刷新结束（退出码 $?）"
