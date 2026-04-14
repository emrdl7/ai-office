#!/usr/bin/env node
/**
 * WCAG 2.1 AA 명도 대비 자동 검증 스크립트
 *
 * 1) tokens.css를 파싱해 정의된 색상 토큰을 추출합니다.
 * 2) CHECKS 목록에 선언된 색상 쌍의 대비 비율을 계산합니다.
 * 3) tokens.css에 추가됐지만 CHECKS에 포함되지 않은 색상 토큰을 경고합니다.
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

// ─── 검사 목록: [레이블, 전경색, 배경색, 큰텍스트여부] ─────────────

/**
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
  ['[Dark]  멘션 텍스트  | --text-mention on --bubble-agent',  '#93c5fd', '#1f2937', false],
  ['[Dark]  버튼 텍스트  | --action-text on --action-bg',      '#ffffff', '#2563eb', false],
]

// ─── 미검사 토큰 탐지 ──────────────────────────────────────────

/**
 * CHECKS에서 사용된 hex값 집합을 구합니다.
 */
function getCheckedHexValues() {
  const hexSet = new Set()
  for (const [, fg, bg] of CHECKS) {
    hexSet.add(fg.toLowerCase())
    hexSet.add(bg.toLowerCase())
  }
  return hexSet
}

/**
 * tokens.css에 정의됐지만 CHECKS에 포함되지 않은 색상 토큰을 반환합니다.
 */
function findUncheckedTokens(tokens, checkedHex) {
  const unchecked = []
  for (const [mode, map] of [['라이트', tokens.light], ['다크', tokens.dark]]) {
    for (const [name, hex] of map) {
      if (!checkedHex.has(hex)) {
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

// ─── tokens.css 미검사 토큰 경고 ──────────────────────────────

const tokensPath = resolve(__dirname, '../src/tokens.css')
let uncheckedWarning = false

try {
  const tokens = parseColorTokens(tokensPath)
  const checkedHex = getCheckedHexValues()
  const unchecked = findUncheckedTokens(tokens, checkedHex)

  if (unchecked.length > 0) {
    uncheckedWarning = true
    console.log(`\n${YELLOW}${BOLD}⚠️  CHECKS에 포함되지 않은 색상 토큰 (${unchecked.length}개)${RESET}`)
    console.log(`${DIM}   tokens.css에 정의됐지만 대비 검사 쌍이 없습니다.${RESET}`)
    console.log(`${DIM}   check-contrast.mjs의 CHECKS 배열에 해당 토큰을 추가하세요.\n${RESET}`)
    for (const { mode, name, hex } of unchecked) {
      console.log(`   ${YELLOW}${mode} ${name}${RESET}  ${DIM}${hex}${RESET}`)
    }
    console.log('')
  }
} catch (e) {
  console.log(`${YELLOW}⚠️  tokens.css 파싱 실패 (미검사 토큰 탐지 건너뜀): ${e.message}${RESET}`)
}

// ─── 최종 결과 ────────────────────────────────────────────────

if (failed > 0) {
  console.log(
    `${RED}${BOLD}실패: ${failed}개 항목이 WCAG 2.1 AA 기준 미달${RESET}  ` +
    `${GREEN}(통과: ${passed}개)${RESET}`
  )
  console.log(`\n${YELLOW}💡 수정 방법:${RESET}`)
  console.log(`   tokens.css의 해당 색상값을 더 높은 대비의 색조로 변경하세요.`)
  console.log(`   참고: https://webaim.org/resources/contrastchecker/\n`)
  process.exit(1)
} else if (uncheckedWarning) {
  console.log(`${GREEN}${BOLD}통과: 모든 ${passed}개 항목이 WCAG 2.1 AA 기준 충족 ✓${RESET}`)
  console.log(`${YELLOW}경고: 미검사 토큰이 있습니다. CHECKS 배열을 업데이트하세요.${RESET}\n`)
  // 미검사 토큰은 경고만 출력하고 빌드는 통과시킵니다 (exit 0)
  process.exit(0)
} else {
  console.log(`${GREEN}${BOLD}통과: 모든 ${passed}개 항목이 WCAG 2.1 AA 기준 충족 ✓${RESET}\n`)
  process.exit(0)
}
