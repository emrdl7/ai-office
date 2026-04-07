## 개발자 기본 전문 지식

### 코드 품질 원칙
- 시맨틱 HTML: 용도에 맞는 태그 사용 (div 남용 금지, nav/main/section/article 활용)
- CSS 방법론: BEM 또는 CSS Modules로 스코프 격리, !important 사용 금지
- JavaScript: 이벤트 위임 활용, DOM 직접 조작 최소화, 메모리 누수 주의
- 에러 핸들링: 사용자 입력/API 호출 경계에서 반드시 에러 처리

### 성능 최적화
- Core Web Vitals 목표: LCP < 2.5s, FID < 100ms, CLS < 0.1
- 이미지: WebP/AVIF 포맷 우선, lazy loading 적용, srcset으로 반응형
- 번들 최적화: 코드 스플리팅, tree shaking, 미사용 의존성 제거
- 폰트: font-display: swap, preload로 FOIT 방지

### 보안 기본 원칙
- XSS 방지: 사용자 입력은 항상 이스케이프, innerHTML 사용 금지
- CSRF 방지: 폼 전송 시 토큰 검증
- Content Security Policy(CSP) 헤더 설정 권장
- 민감 데이터는 클라이언트에 저장하지 않을 것

### 크로스 브라우저 & 반응형
- 지원 브라우저: Chrome/Edge(최신 2), Safari(최신 2), Firefox(최신 2)
- 모바일 우선(Mobile First) 접근으로 CSS 작성
- 미디어 쿼리 브레이크포인트는 디자인 시스템과 일치시킬 것
- vh/vw 단위 사용 시 iOS Safari 주소창 이슈 대응 (dvh 사용)

### 코드 산출물 기준
- 복사-붙여넣기로 바로 실행 가능한 완전한 코드 작성
- 주석은 "왜"를 설명, "무엇"은 코드가 설명
- 플레이스홀더/TODO 금지 — 미구현 부분은 명시적으로 빈 상태로 표현
- 파일 하나에 모든 코드를 넣지 말고 논리적 단위로 분리
