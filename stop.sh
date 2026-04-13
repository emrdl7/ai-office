#!/bin/bash
# serve.sh 루프 프로세스부터 종료 (좀비 방지)
pkill -f 'serve\.sh' 2>/dev/null
pkill -f 'uvicorn' 2>/dev/null
pkill -f 'vite' 2>/dev/null
sleep 2
# 포트 점유 프로세스 강제 종료
lsof -ti:8000 2>/dev/null | xargs kill -9 2>/dev/null
lsof -ti:3100 2>/dev/null | xargs kill -9 2>/dev/null
sleep 1
# 검증
REMAIN_8000=$(lsof -ti:8000 2>/dev/null)
REMAIN_3100=$(lsof -ti:3100 2>/dev/null)
if [ -n "$REMAIN_8000" ] || [ -n "$REMAIN_3100" ]; then
  echo "⚠️ 일부 프로세스 남음 — 수동 확인 필요: 8000=$REMAIN_8000 3100=$REMAIN_3100"
  exit 1
fi
echo "서버 종료 완료"
