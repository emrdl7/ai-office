# AI Office — 서버

FastAPI + SQLite WAL 메시지 버스 기반 오케스트레이션 서버.

## 실행

```bash
cd server
uv sync
source .venv/bin/activate
./serve.sh
```

기본 포트 3101. 대시보드(Vite dev)는 3100에서 proxy.

## 인증 정책

서버는 두 개의 독립 토큰을 지원한다. 배포 방식에 따라 선택 적용.

### `WS_AUTH_TOKEN` (WebSocket 전용)
- WebSocket 엔드포인트 `/ws/logs` 보호.
- 환경변수 미설정 시 서버 시작 시 자동 생성. 대시보드가 `/api/ws-token`으로 조회.

### `REST_AUTH_TOKEN` (REST API 전체, 선택)
- 모든 `/api/*` 경로를 `Authorization: Bearer <token>` 또는 `?token=<token>`으로 보호.
- `/health`만 면제 (라이브니스 프로브용).
- `/api/ws-token`도 보호 — WS 토큰 탈취 방지.
- 환경변수 비워두면 미들웨어가 우회됨 (로컬 단독 실행 기본값).

### 배포 모드별 권장 설정

| 모드 | REST_AUTH_TOKEN | CORS | 비고 |
|------|-----------------|------|------|
| 로컬 개발 (127.0.0.1만) | 미설정 | `localhost:3100` (현재) | 현재 기본 동작 |
| 내부망 공유 | 설정 권장 | 필요 도메인 추가 | 팀원 간 공유 시 |
| 원격/프록시 뒤 | **반드시 설정** | HTTPS 도메인 고정 | 인터넷 노출 시 |

### 호출 예시
```bash
export REST_AUTH_TOKEN=$(openssl rand -base64 32)

# Bearer
curl -H "Authorization: Bearer $REST_AUTH_TOKEN" https://host/api/agents

# Query (파일 다운로드 URL 등)
curl "https://host/api/artifacts/file.md?token=$REST_AUTH_TOKEN"
```

## 메시지 버스 유지보수

`data/bus.db`의 `messages` 테이블은 영구 누적된다. 장기 운영 시 주기적으로
아카이브 필요:

```python
from bus.message_bus import MessageBus
bus = MessageBus('data/bus.db')
moved = bus.archive_old_messages(days=30)  # done + 30일 경과분 이관
print(f'{moved} messages archived')
```

현재 자동 스케줄은 미연결. cron 또는 서버 시작 시 1회 호출 검토 (TODOS P2).
