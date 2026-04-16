#!/bin/bash
# 백엔드 자동 재시작 — exponential backoff (최대 5회 연속 실패 시 60초 대기)
cd "$(dirname "$0")"
fail_count=0
max_fails=5

while true; do
  uv run uvicorn main:app --host 0.0.0.0 --port 8000 2>&1
  exit_code=$?

  if [ $exit_code -eq 0 ]; then
    fail_count=0
    sleep 1
  else
    fail_count=$((fail_count + 1))
    if [ $fail_count -ge $max_fails ]; then
      echo "[$(date)] 백엔드 ${max_fails}회 연속 실패 (exit=${exit_code}). 60초 대기 후 재시도..."
      sleep 60
      fail_count=0
    else
      delay=$((fail_count * 3))
      echo "[$(date)] 백엔드 종료 (exit=${exit_code}, ${fail_count}/${max_fails}회). ${delay}초 후 재시작..."
      sleep $delay
    fi
  fi
done
