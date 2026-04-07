# AI Office 셋업 가이드

다른 PC에서 AI Office를 설치하고 실행하는 방법입니다.

---

## 요구사항

| 항목 | 버전 | 설치 방법 |
|------|------|----------|
| Node.js | 22+ | `brew install node` 또는 nvm |
| Python | 3.12+ | `brew install python@3.12` |
| uv | 최신 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Claude Code | 최신 | `npm install -g @anthropic-ai/claude-code` |
| OpenCode | 최신 | `curl -fsSL https://opencode.ai/install \| sh` |

---

## 1단계: 저장소 클론

```bash
git clone <저장소URL> ai-office
cd ai-office
```

---

## 2단계: 환경변수 설정

```bash
cp server/.env.example server/.env
```

`server/.env` 파일을 열고 API 키를 입력합니다:

```env
# 필수 — Groq API 키 (무료)
# https://console.groq.com/keys 에서 발급
GROQ_API_KEY=gsk_여기에_키_입력

# 선택 — CLI 경로가 기본값과 다를 경우
# CLAUDE_CLI=/path/to/claude
# OPENCODE_CLI=/path/to/opencode
```

---

## 3단계: 백엔드 설치

```bash
cd server
uv sync
cd ..
```

---

## 4단계: 프론트엔드 설치 + 빌드

```bash
cd dashboard
npm install
npm run build
cd ..
```

---

## 5단계: 실행

```bash
# 전체 시작 (백엔드 + 프론트엔드)
bash start.sh

# 접속
# 개발: http://localhost:3100 (Vite HMR)
# 프로덕션: http://localhost:8000 (빌드된 정적 파일)
```

---

## 6단계: 외부 접속 (선택)

```bash
# ngrok 설치
brew install ngrok

# 토큰 등록 (https://dashboard.ngrok.com 에서 발급)
ngrok config add-authtoken YOUR_TOKEN

# 터널 열기
ngrok http 8000
```

---

## 종료

```bash
bash stop.sh
```

---

## 구조

```
ai-office/
├── agents/          # 에이전트 프롬프트 (성격, 역할)
│   ├── teamlead.md  # 팀장 (Claude CLI)
│   ├── planner.md   # 기획자 (OpenCode)
│   ├── designer.md  # 디자이너 (Groq)
│   ├── developer.md # 개발자 (OpenCode)
│   └── qa.md        # QA (Groq)
│
├── server/          # 백엔드 (FastAPI + Python)
│   ├── main.py      # 진입점
│   ├── orchestration/
│   │   ├── office.py    # 핵심 — 팀장 주도 오케스트레이션
│   │   ├── intent.py    # 의도 분류 (대화/요청/프로젝트)
│   │   ├── agent.py     # 에이전트 기반 클래스
│   │   └── meeting.py   # 회의 시스템
│   ├── runners/
│   │   ├── claude_runner.py   # Claude CLI 호출
│   │   ├── opencode_runner.py # OpenCode CLI 호출
│   │   └── groq_runner.py     # Groq API 호출
│   └── .env.example  # 환경변수 템플릿
│
├── dashboard/       # 프론트엔드 (React + Vite + Tailwind)
│   └── src/
│       ├── App.tsx
│       └── components/
│           ├── ChatRoom.tsx    # 채팅방
│           ├── Sidebar.tsx     # 팀원 목록
│           └── ArtifactModal.tsx # 산출물 모달
│
├── start.sh         # 전체 시작
├── stop.sh          # 전체 종료
└── SETUP.md         # 이 파일
```

---

## 에이전트 러너 구성

| 에이전트 | 러너 | 비용 | 비고 |
|---------|------|------|------|
| 팀장 | Claude CLI | Claude Code 구독 | 의도 분류, 최종 검수, 회의 답변 |
| 기획자 | OpenCode | OpenCode 구독 | 태스크 분배, 취합, 압축 |
| 디자이너 | Groq API | 무료 | Llama 3.3 70B |
| 개발자 | OpenCode | OpenCode 구독 | 코드 생성, 기술 분석 |
| QA | Groq API | 무료 | 검수 (JSON 응답) |

---

## 트러블슈팅

### 서버가 안 뜰 때
```bash
# 포트 점유 확인
lsof -ti:8000 | xargs kill -9
lsof -ti:3100 | xargs kill -9
bash start.sh
```

### Claude CLI를 못 찾을 때
```bash
# 경로 확인
which claude
# .env에 경로 지정
echo 'CLAUDE_CLI=/path/to/claude' >> server/.env
```

### OpenCode를 못 찾을 때
```bash
which opencode
echo 'OPENCODE_CLI=/path/to/opencode' >> server/.env
```

### Groq API 에러
- https://console.groq.com/keys 에서 키 재발급
- 무료 한도: 분당 30회, 일 14,400회
