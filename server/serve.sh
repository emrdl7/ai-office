#!/bin/bash
# 백엔드 자동 재시작
cd "$(dirname "$0")"
while true; do
  uv run uvicorn main:app --port 8000 2>&1
  echo "[$(date)] 백엔드 종료됨. 3초 후 재시작..."
  sleep 3
done
