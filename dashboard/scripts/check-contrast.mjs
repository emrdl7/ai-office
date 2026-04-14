#!/usr/bin/env node
/**
 * WCAG 2.1 AA 명도 대비 자동 검증 스크립트
 *
 * tokens.css에 정의된 색상 쌍의 대비 비율을 계산하여
 * WCAG 2.1 AA 기준 충족 여부를 검사합니다.
 *
 *   일반 텍스트: 4.5:1 이상
 *   큰 텍스트 (18pt+ / bold 14pt+): 3.0:1 이상
 *
 * 사용: node scripts/check-contrast.mjs
 */

/** hex → { r, g, b } */
function hexToRgb(hex) {
  const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex.trim())
  if (!m) throw new Error(`잘못된 색상값: ${hex}`)
  return { r: parseInt(m[1], 16), g: parseInt(m[2], 16), b: parseInt(m[3], 16) }
}

/** 상대 휘도 (IEC 61966-2-1) */
function luminance({ r, g, b }) {
  return [r, g, b]
    .map(c => {
      const s = c / 255
      return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4)
    })
    .reduce((sum, lin, i) => sum + [0.2126, 0.7152, 0.0722][i] * lin, 0)
}

/** 대비 비율 */
function contrastRatio(hex1, hex2) {
  const l1 = luminance(hexToRgb(hex1))
  const l2 = luminance(hexToRgb(hex2))
  const [bright, dark] = l1 > l2 ? [l1, l2] : [l2, l1]
  return (bright + 0.05) / (dark + 0.05)
}

/**
 * 검사 목록: [레이블, 전경색, 배경색, 큰텍스트여부]
 *
 * tokens.css의 토큰 값과 동기화해서 유지하세요.
 * 새 색상 토큰을 추가할 때 여기에도 쌍을 추가해야 합니다.
 */
const CHECKS = [
  // ─── 라이트 모드 ───────────────────────────────────────
  ['[Light] 기본 텍스트  | --text-primary on --bg-primary',    '#111827', '#f3f4f6', false],
  ['[Light] 보조 텍스트  | --text-secondary on --bg-primary',  '#4b5563', '#f3f4f6', false],
  ['[Light] 링크 텍스트  | --text-link on --bg-primary',       '#1d4ed8', '#f3f4f6', false],
  ['[Light] 버튼 텍스트  | --action-text on --action-bg',      '#ffffff', '#2563eb', false],

  // ─── 다크 모드 ────────────────────────────────────────
  ['[Dark]  기본 텍스트  | --text-primary on --bg-primary',    '#f3f4f6', '#030712', false],
  ['[Dark]  보조 텍스트  | --text-secondary on --bg-primary',  '#9ca3af', '#030712', false],
  ['[Dark]  링크 텍스트  | --text-link on --bg-surface',       '#60a5fa', '#111827', false],
  ['[Dark]  멘션 텍스트  | --text-mention on --bubble-agent',  '#60a5fa', '#1f2937', false],
  ['[Dark]  버튼 텍스트  | --action-text on --action-bg',      '#ffffff', '#2563eb', false],
]

// ─── 검사 실행 ─────────────────────────────────────────────

const RESET  = '\x1b[0m'
const GREEN  = '\x1b[32m'
const RED    = '\x1b[31m'
const YELLOW = '\x1b[33m'
const BOLD   = '\x1b[1m'
const DIM    = '\x1b[2m'

console.log(`\n${BOLD}WCAG 2.1 AA 명도 대비 검사${RESET}\n`)

let passed = 0
let failed = 0

for (const [label, fg, bg, isLarge] of CHECKS) {
  const ratio     = contrastRatio(fg, bg)
  const threshold = isLarge ? 3.0 : 4.5
  const ok        = ratio >= threshold
  const icon      = ok ? `${GREEN}✅${RESET}` : `${RED}❌${RESET}`
  const ratioStr  = ratio.toFixed(2).padStart(5)
  const level     = isLarge ? 'AA 큰 텍스트 (3.0:1)' : 'AA 일반 텍스트 (4.5:1)'

  console.log(`${icon}  ${label}`)
  console.log(`${DIM}     대비: ${RESET}${ok ? GREEN : RED}${ratioStr}:1${RESET}${DIM}  기준: ${level}${RESET}`)

  ok ? passed++ : failed++
}

console.log('')
console.log(`${'─'.repeat(60)}`)

if (failed > 0) {
  console.log(
    `${RED}${BOLD}실패: ${failed}개 항목이 WCAG 2.1 AA 기준 미달${RESET}  ` +
    `${GREEN}(통과: ${passed}개)${RESET}`
  )
  console.log(`\n${YELLOW}💡 수정 방법:${RESET}`)
  console.log(`   tokens.css의 해당 색상값을 더 높은 대비의 색조로 변경하세요.`)
  console.log(`   참고: https://webaim.org/resources/contrastchecker/\n`)
  process.exit(1)
} else {
  console.log(`${GREEN}${BOLD}통과: 모든 ${passed}개 항목이 WCAG 2.1 AA 기준 충족 ✓${RESET}\n`)
  process.exit(0)
}
