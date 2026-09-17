#!/bin/bash
# 一键启动《瑜伽师地论》学习网页静态服务
# 用法: ./serve-study.sh  (Ctrl+C 停止)

set -e
cd "$(dirname "$0")"

PORT=8000
IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)

if lsof -i :$PORT -sTCP:LISTEN >/dev/null 2>&1; then
  echo "端口 $PORT 已被占用，服务可能已在运行："
  echo "  http://localhost:$PORT/study/"
  [ -n "$IP" ] && echo "  http://$IP:$PORT/study/"
  exit 0
fi

echo "服务已启动，按 Ctrl+C 停止"
echo "  本机访问:   http://localhost:$PORT/study/"
[ -n "$IP" ] && echo "  局域网访问: http://$IP:$PORT/study/"
echo ""

exec python3 -m http.server $PORT --bind 0.0.0.0
