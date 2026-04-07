#!/bin/bash
# 프론트엔드 자동 재시작 — 죽으면 3초 후 다시 살림
cd "$(dirname "$0")"
while true; do
  npm run dev 2>&1
  echo "[$(date)] 프론트 종료됨. 3초 후 재시작..."
  sleep 3
done
