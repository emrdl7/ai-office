#!/bin/bash
cd "$(dirname "$0")"

# 기존 프로세스 정리
lsof -ti:8000 | xargs kill -9 2>/dev/null
lsof -ti:3100 | xargs kill -9 2>/dev/null
sleep 1

# 백엔드 (자동 재시작)
nohup ./server/serve.sh > /tmp/ai-office-backend.log 2>&1 &
echo "백엔드: http://localhost:8000 (PID: $!)"

# 프론트엔드 (자동 재시작)
nohup ./dashboard/serve.sh > /tmp/ai-office-frontend.log 2>&1 &
echo "프론트: http://localhost:3100 (PID: $!)"

echo "로그: tail -f /tmp/ai-office-backend.log /tmp/ai-office-frontend.log"
