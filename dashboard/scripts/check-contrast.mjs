#!/usr/bin/env node
/**
 * WCAG 2.1 AA 명도 대비 자동 검증 스크립트
 *
 * 1) tokens.css를 파싱해 정의된 색상 토큰을 추출합니다.
 * 2) CHECKS 목록에 선언된 색상 쌍의 대비 비율을 계산합니다.
 *    - CHECKS는 hex 값 대신 토큰 이름을 참조하므로 tokens.css와 자동으로 동기화됩니다.
 * 3) tokens.css에 추가됐지만 CHECKS에 포함되지 않은 색상 토큰이 있으면 빌드를 실패시킵니다.
 *
 *   일반 텍스트: 4.5:1 이상
 *   큰 텍스트 (18pt+ / bold 14pt+): 3.0:1 이상
 *
 * 사용: node scripts/check-contrast.mjs
 */

import { readFileSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))

// ─── 색상 계산 유틸리티 ────────────────────────────────────────

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

// ─── tokens.css 파싱 ──────────────────────────────────────────

/**
 * tokens.css에서 색상 토큰(--color-*)을 추출합니다.
 * Returns: { light: Map<name, hex>, dark: Map<name, hex> }
 */
function parseColorTokens(cssPath) {
  const css = readFileSync(cssPath, 'utf8')
  const HEX_RE = /(--color-[\w-]+)\s*:\s*(#[0-9a-fA-F]{3,8})/g

  // :root 블록 (라이트 모드)
  const rootBlock = css.match(/:root\s*\{([^}]+)\}/s)?.[1] ?? ''
  // .dark 블록
  const darkBlock = css.match(/\.dark\s*\{([^}]+)\}/s)?.[1] ?? ''

  function extractTokens(block) {
    const map = new Map()
    let m
    HEX_RE.lastIndex = 0
    while ((m = HEX_RE.exec(block)) !== null) {
      map.set(m[1], m[2].toLowerCase())
    }
    return map
  }

  return {
    light: extractTokens(rootBlock),
    dark: extractTokens(darkBlock),
  }
}

// ─── 검사 목록: [레이블, 모드, 전경 토큰, 배경 토큰, 큰텍스트여부] ─────
//
// hex 값이 아닌 토큰 이름을 참조합니다.
// tokens.css의 값이 바뀌면 이 CHECKS가 자동으로 최신 값을 반영합니다.
// 새 색상 토큰을 tokens.css에 추가하면 반드시 여기에도 쌍을 추가해야 합니다.
// (추가하지 않으면 빌드가 실패합니다.)
//
const CHECKS = [
  // ─── 라이트 모드 ───────────────────────────────────────
  ['[Light] 기본 텍스트  | --text-primary on --bg-primary',    'light', '--color-text-primary',   '--color-bg-primary',      false],
  ['[Light] 기본 텍스트  | --text-primary on --bg-surface',    'light', '--color-text-primary',   '--color-bg-surface',      false],
  ['[Light] 보조 텍스트  | --text-secondary on --bg-primary',  'light', '--color-text-secondary', '--color-bg-primary',      false],
  ['[Light] 링크 텍스트  | --text-link on --bg-primary',       'light', '--color-text-link',      '--color-bg-primary',      false],
  ['[Light] 버튼 텍스트  | --action-text on --action-bg',      'light', '--color-action-text',    '--color-action-bg',       false],
  ['[Light] 버튼 호버    | --action-text on --action-hover',   'light', '--color-action-text',    '--color-action-hover',    false],
  ['[Light] 역텍스트     | --text-inverse on --bg-sidebar',    'light', '--color-text-inverse',   '--color-bg-sidebar',      false],
  ['[Light] 멘션 텍스트  | --text-mention on --bubble-agent',  'light', '--color-text-mention',   '--color-bg-bubble-agent', false],

  // ─── 다크 모드 ────────────────────────────────────────
  ['[Dark]  기본 텍스트  | --text-primary on --bg-primary',    'dark',  '--color-text-primary',   '--color-bg-primary',      false],
  ['[Dark]  기본 텍스트  | --text-primary on --bg-surface',    'dark',  '--color-text-primary',   '--color-bg-surface',      false],
  ['[Dark]  보조 텍스트  | --text-secondary on --bg-primary',  'dark',  '--color-text-secondary', '--color-bg-primary',      false],
  ['[Dark]  링크 텍스트  | --text-link on --bg-surface',       'dark',  '--color-text-link',      '--color-bg-surface',      false],
  ['[Dark]  멘션 텍스트  | --text-mention on --bubble-agent',  'dark',  '--color-text-mention',   '--color-bg-bubble-agent', false],
  ['[Dark]  버튼 텍스트  | --action-text on --action-bg',      'dark',  '--color-action-text',    '--color-action-bg',       false],
  ['[Dark]  역텍스트     | --text-inverse on --bg-sidebar',   'dark',  '--color-text-inverse',   '--color-bg-sidebar',      false],
  // [Dark] action-hover: dark 팔레트에서 라이트 모드 값을 상속하므로 라이트 항목으로 커버됨
]

// ─── 미검사 토큰 탐지 ──────────────────────────────────────────

/**
 * CHECKS에서 사용된 토큰 이름 집합을 구합니다.
 * { light: Set<tokenName>, dark: Set<tokenName> }
 */
function getCheckedTokenNames() {
  const light = new Set()
  const dark  = new Set()
  for (const [, mode, fg, bg] of CHECKS) {
    const set = mode === 'dark' ? dark : light
    set.add(fg)
    set.add(bg)
  }
  return { light, dark }
}

/**
 * tokens.css에 정의됐지만 CHECKS에 포함되지 않은 색상 토큰을 반환합니다.
 */
function findUncheckedTokens(tokens, checkedNames) {
  const unchecked = []
  for (const [mode, map, names] of [
    ['라이트', tokens.light, checkedNames.light],
    ['다크',   tokens.dark,  checkedNames.dark],
  ]) {
    for (const [name, hex] of map) {
      if (!names.has(name)) {
        unchecked.push({ mode, name, hex })
      }
    }
  }
  return unchecked
}

// ─── 검사 실행 ─────────────────────────────────────────────────

const RESET  = '\x1b[0m'
const GREEN  = '\x1b[32m'
const RED    = '\x1b[31m'
const YELLOW = '\x1b[33m'
const BOLD   = '\x1b[1m'
const DIM    = '\x1b[2m'

// tokens.css를 먼저 로드합니다
const tokensPath = resolve(__dirname, '../src/tokens.css')
let tokens
try {
  tokens = parseColorTokens(tokensPath)
} catch (e) {
  console.error(`${RED}${BOLD}오류: tokens.css를 읽을 수 없습니다: ${e.message}${RESET}`)
  process.exit(1)
}

console.log(`\n${BOLD}WCAG 2.1 AA 명도 대비 검사${RESET}\n`)

let passed = 0
let failed = 0
const resolveErrors = []

for (const [label, mode, fgToken, bgToken, isLarge] of CHECKS) {
  const map = mode === 'dark' ? tokens.dark : tokens.light

  // 라이트 모드 전용 토큰(action-hover 등)은 라이트 맵에서, 다크 맵에 없으면 라이트 맵 fallback
  const fgHex = map.get(fgToken) ?? tokens.light.get(fgToken)
  const bgHex = map.get(bgToken) ?? tokens.light.get(bgToken)

  if (!fgHex || !bgHex) {
    const missing = [!fgHex && fgToken, !bgHex && bgToken].filter(Boolean).join(', ')
    resolveErrors.push(`  ${label}\n  → tokens.css에서 찾을 수 없는 토큰: ${missing}`)
    failed++
    continue
  }

  const ratio     = contrastRatio(fgHex, bgHex)
  const threshold = isLarge ? 3.0 : 4.5
  const ok        = ratio >= threshold
  const icon      = ok ? `${GREEN}✅${RESET}` : `${RED}❌${RESET}`
  const ratioStr  = ratio.toFixed(2).padStart(5)
  const level     = isLarge ? 'AA 큰 텍스트 (3.0:1)' : 'AA 일반 텍스트 (4.5:1)'

  console.log(`${icon}  ${label}`)
  console.log(`${DIM}     대비: ${RESET}${ok ? GREEN : RED}${ratioStr}:1${RESET}${DIM}  기준: ${level}  (${fgToken} / ${bgToken})${RESET}`)

  ok ? passed++ : failed++
}

if (resolveErrors.length > 0) {
  console.log(`\n${RED}${BOLD}토큰 해석 오류 (CHECKS에 존재하지 않는 토큰 이름):${RESET}`)
  resolveErrors.forEach(e => console.log(`${RED}${e}${RESET}`))
}

console.log('')
console.log(`${'─'.repeat(60)}`)

// ─── tokens.css 미검사 토큰 — 커버리지 강제 ────────────────────
//
// CHECKS에 포함되지 않은 색상 토큰이 있으면 빌드를 실패시킵니다.
// 새 토큰을 추가할 때 CHECKS에도 반드시 대비 쌍을 추가해야 합니다.

const checkedNames = getCheckedTokenNames()
const unchecked = findUncheckedTokens(tokens, checkedNames)

if (unchecked.length > 0) {
  console.log(`\n${RED}${BOLD}❌ CHECKS에 포함되지 않은 색상 토큰 (${unchecked.length}개) — 빌드 실패${RESET}`)
  console.log(`${DIM}   tokens.css에 정의됐지만 대비 검사 쌍이 없습니다.${RESET}`)
  console.log(`${DIM}   check-contrast.mjs의 CHECKS 배열에 해당 토큰을 추가하세요.\n${RESET}`)
  for (const { mode, name, hex } of unchecked) {
    console.log(`   ${RED}${mode} ${name}${RESET}  ${DIM}${hex}${RESET}`)
  }
  console.log('')
  console.log(`${YELLOW}💡 수정 방법:${RESET}`)
  console.log(`   CHECKS 배열에 해당 토큰의 전경/배경 쌍을 추가하세요.`)
  console.log(`   예: ['[Light] 새 텍스트 | --new-token on --bg', 'light', '--color-new-token', '--color-bg-primary', false]\n`)
  failed += unchecked.length
}

// ─── 최종 결과 ────────────────────────────────────────────────

if (failed > 0) {
  console.log(
    `${RED}${BOLD}실패: ${failed}개 항목이 WCAG 2.1 AA 기준 미달 또는 미검사${RESET}  ` +
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
