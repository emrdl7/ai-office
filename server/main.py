# FastAPI 오케스트레이션 서버 진입점
# WebSocket 엔드포인트는 01-06-PLAN에서 추가됨
from fastapi import FastAPI

app = FastAPI(title='AI Office')

@app.get('/health')
async def health():
    return {'status': 'ok'}
