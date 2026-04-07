## 웹사이트 프로젝트 추가 전문 지식 (개발자)

### HTML 구조 패턴
- 시맨틱 구조: header > nav, main > section/article, footer
- meta 태그: viewport, description, og:title, og:image, og:description
- 구조화된 데이터: JSON-LD로 Organization, WebSite, BreadcrumbList 마크업
- lang 속성: html 태그에 반드시 지정 (ko, en 등)

### CSS 아키텍처
- 커스텀 프로퍼티(CSS Variables)로 디자인 토큰 관리
- 레이어 순서: reset → tokens → base → layout → components → utilities
- 그리드: CSS Grid + Flexbox 조합, float 레이아웃 사용 금지
- 미디어 쿼리: Mobile First (min-width), 디자인 시스템 브레이크포인트 사용

### JavaScript 패턴
- 모바일 메뉴: 햄버거 토글 + 포커스 트랩 + ESC 닫기 + 오버레이
- 스크롤 이벤트: IntersectionObserver 사용 (scroll 이벤트 직접 감지 지양)
- 폼 유효성: HTML5 constraint validation API 우선, 커스텀 메시지
- 부드러운 스크롤: scroll-behavior: smooth 또는 scrollIntoView

### SEO 기술 요소
- title 태그: 페이지별 고유, 60자 이내
- canonical URL 설정
- robots.txt + sitemap.xml 생성
- 이미지 alt 텍스트: 키워드 포함, 자연스러운 설명

### 배포 & 호스팅
- 정적 사이트: Vercel, Netlify, GitHub Pages
- HTTPS 필수, HTTP → HTTPS 리다이렉트
- 캐싱: 정적 자산에 Cache-Control 헤더, 파일명 해시
