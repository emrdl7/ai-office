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
 * :root 블록에서 @against 어노테이션을 파싱해 대비 쌍 목록을 반환합니다.
 * 주석 형식: --color-text-foo: #hex;  /* ... @against bg-bar,bg-baz * /
 * → [{ fg: '--color-text-foo', bg: '--color-bg-bar' }, ...]
 *
 * 외부에서도 import 가능하도록 최상위 함수로 분리 (테스트에서 직접 사용).
 */
export function extractPairs(block) {
  const AGAINST_RE = /(--color-[\w-]+)\s*:[^\n]*@against\s+([\w,\s-]+)/g
  const pairs = []
  let m
  while ((m = AGAINST_RE.exec(block)) !== null) {
    const fgToken = m[1]
    // trim()으로 트레일링 공백 및 */ 이전 여백 제거 후 유효한 토큰명만 남김
    const bgTokens = m[2]
      .split(',')
      .map(s => `--color-${s.trim()}`)
      .filter(s => /^--color-[\w-]+$/.test(s))
    for (const bgToken of bgTokens) {
      pairs.push({ fg: fgToken, bg: bgToken })
    }
  }
  return pairs
}

/**
 * tokens.css에서 색상 토큰(--color-*)을 추출하고,
 * :root 블록의 `@against` 주석에서 대비 쌍을 자동으로 파싱합니다.
 *
 * @against 형식 (토큰 주석에 기재):
 *   --color-text-foo: #hex;  /* ... @against bg-bar,bg-baz * /
 *
 * Returns: {
 *   light: Map<name, hex>,
 *   dark:  Map<name, hex>,
 *   pairs: Array<{ fg: string, bg: string }>  ← :root @against 어노테이션에서 추출
 * }
 */
export function parseColorTokens(cssPath) {
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
    dark:  extractTokens(darkBlock),
    pairs: extractPairs(rootBlock),
  }
}

// ─── @against 어노테이션에서 CHECKS 자동 생성 ────────────────────
//
// tokens.css의 :root 블록에 선언된 @against 주석을 읽어
// 라이트·다크 두 모드에 대한 CHECKS 항목을 자동으로 만듭니다.
//
// 새 색상 쌍을 추가할 때는 tokens.css 주석에 @against 어노테이션만 추가하면
// 이 스크립트가 자동으로 반영합니다. CHECKS를 직접 수정할 필요가 없습니다.
//
export function buildChecks(pairs) {
  const checks = []
  for (const { fg, bg } of pairs) {
    const fgShort = fg.replace('--color-', '')
    const bgShort = bg.replace('--color-', '')
    checks.push([`[Light] ${fgShort} on ${bgShort}`, 'light', fg, bg, false])
    checks.push([`[Dark]  ${fgShort} on ${bgShort}`, 'dark',  fg, bg, false])
  }
  return checks
}

// ─── 미검사 토큰 탐지 ──────────────────────────────────────────

/**
 * tokens.css에 정의됐지만 pairs(@against 어노테이션)에 포함되지 않은 색상 토큰을 반환합니다.
 * 전경(fg) 또는 배경(bg)으로 한 번이라도 등장하면 커버된 것으로 간주합니다.
 */
export function findUncheckedTokens(tokens) {
  const covered = new Set()
  for (const { fg, bg } of tokens.pairs) {
    covered.add(fg)
    covered.add(bg)
  }

  const unchecked = []
  for (const [mode, map] of [['라이트', tokens.light], ['다크', tokens.dark]]) {
    for (const [name, hex] of map) {
      if (!covered.has(name)) {
        unchecked.push({ mode, name, hex })
      }
    }
  }
  return unchecked
}

// ─── 검사 실행 ─────────────────────────────────────────────────
// 직접 실행(node check-contrast.mjs)일 때만 아래 코드가 동작합니다.
// import로 불러올 때는 함수 export만 노출됩니다.

const isMain = process.argv[1] === fileURLToPath(import.meta.url)

if (isMain) {

const RESET  = '\x1b[0m'
const GREEN  = '\x1b[32m'
const RED    = '\x1b[31m'
const YELLOW = '\x1b[33m'
const BOLD   = '\x1b[1m'
const DIM    = '\x1b[2m'

// tokens.css를 먼저 로드하고 @against 어노테이션에서 CHECKS를 자동 생성합니다
const tokensPath = resolve(__dirname, '../src/tokens.css')
let tokens
try {
  tokens = parseColorTokens(tokensPath)
} catch (e) {
  console.error(`${RED}${BOLD}오류: tokens.css를 읽을 수 없습니다: ${e.message}${RESET}`)
  process.exit(1)
}

if (tokens.pairs.length === 0) {
  console.error(`${RED}${BOLD}오류: tokens.css에서 @against 어노테이션을 찾을 수 없습니다.${RESET}`)
  console.error(`${DIM}   예: --color-text-foo: #hex;  /* ... @against bg-bar,bg-baz */\n${RESET}`)
  process.exit(1)
}

// @against 어노테이션에서 CHECKS 자동 생성 (라이트·다크 양방향)
const CHECKS = buildChecks(tokens.pairs)

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
// @against 어노테이션(전경) 또는 배경 참조로 한 번도 등장하지 않은
// 색상 토큰이 있으면 빌드를 실패시킵니다.
// 새 토큰을 추가할 때는 주석에 @against 어노테이션을 달거나
// 기존 전경 토큰의 @against 목록에 추가하세요.

const unchecked = findUncheckedTokens(tokens)

if (unchecked.length > 0) {
  console.log(`\n${RED}${BOLD}❌ @against 어노테이션이 없는 색상 토큰 (${unchecked.length}개) — 빌드 실패${RESET}`)
  console.log(`${DIM}   tokens.css에 정의됐지만 대비 검사 쌍이 없습니다.${RESET}`)
  console.log(`${DIM}   전경 토큰: 주석에 @against <배경1>,<배경2> 어노테이션을 추가하세요.${RESET}`)
  console.log(`${DIM}   배경 토큰: 전경 토큰의 @against 목록에 이 토큰을 추가하세요.\n${RESET}`)
  for (const { mode, name, hex } of unchecked) {
    console.log(`   ${RED}${mode} ${name}${RESET}  ${DIM}${hex}${RESET}`)
  }
  console.log('')
  console.log(`${YELLOW}💡 수정 방법:${RESET}`)
  console.log(`   전경 토큰 예: --color-text-foo: #hex;  /* ... @against bg-bar,bg-baz */`)
  console.log(`   배경 토큰 예: 기존 --color-text-* 의 @against 목록에 이 토큰을 추가\n`)
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

} // end if (isMain)
