#!/bin/bash
lsof -ti:8000 | xargs kill -9 2>/dev/null
lsof -ti:3100 | xargs kill -9 2>/dev/null
echo "서버 종료 완료"
