#!/bin/bash
# serve.sh 루프 프로세스부터 종료 (좀비 방지)
pkill -f 'serve\.sh' 2>/dev/null
sleep 1
# 포트 점유 프로세스 종료
lsof -ti:8000 | xargs kill -9 2>/dev/null
lsof -ti:3100 | xargs kill -9 2>/dev/null
echo "서버 종료 완료"
