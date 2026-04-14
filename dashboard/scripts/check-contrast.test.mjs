#!/usr/bin/env node
/**
 * check-contrast.mjs 핵심 파싱 로직 단위 테스트
 * 실행: node scripts/check-contrast.test.mjs
 *
 * 순수 함수(extractPairs, buildChecks)를 사이드이펙트 없이 검증하기 위해
 * 로직을 인라인으로 재구현합니다. 메인 스크립트를 import하면 실행 시점에
 * 파일 I/O·process.exit 이 발생하므로 테스트에서는 분리합니다.
 */

import assert from 'node:assert/strict'

// ─── 테스트 대상 로직 (check-contrast.mjs와 동일하게 유지) ─────────────────

/** @param {string} block  :root 또는 .dark CSS 블록 */
function extractPairs(block) {
  const AGAINST_RE = /(--color-[\w-]+)\s*:[^\n]*@against\s+([\w,\s-]+)/g
  const pairs = []
  let m
  while ((m = AGAINST_RE.exec(block)) !== null) {
    const fgToken = m[1]
    const bgTokens = m[2]
      .split(',')
      .map(s => `--color-${s.trim()}`)
      .filter(s => /^--color-[\w-]+$/.test(s))  // ← 수정된 필터
    for (const bgToken of bgTokens) {
      pairs.push({ fg: fgToken, bg: bgToken })
    }
  }
  return pairs
}

/** @param {Array<{fg:string, bg:string}>} pairs */
function buildChecks(pairs) {
  const checks = []
  for (const { fg, bg } of pairs) {
    const fgShort = fg.replace('--color-', '')
    const bgShort = bg.replace('--color-', '')
    checks.push([`[Light] ${fgShort} on ${bgShort}`, 'light', fg, bg, false])
    checks.push([`[Dark]  ${fgShort} on ${bgShort}`, 'dark',  fg, bg, false])
  }
  return checks
}

// ─── 테스트 헬퍼 ─────────────────────────────────────────────────────────────

let passed = 0
let failed = 0

function test(name, fn) {
  try {
    fn()
    console.log(`✅  ${name}`)
    passed++
  } catch (e) {
    console.error(`❌  ${name}`)
    console.error(`    ${e.message}`)
    failed++
  }
}

// ─── extractPairs 테스트 ──────────────────────────────────────────────────────

test('단일 @against 파싱', () => {
  const block = `--color-text-primary: #111827;  /* gray-900 | @against bg-primary */`
  const pairs = extractPairs(block)
  assert.equal(pairs.length, 1)
  assert.deepEqual(pairs[0], { fg: '--color-text-primary', bg: '--color-bg-primary' })
})

test('복수 @against 배경 파싱 (콤마 구분)', () => {
  const block = `--color-text-primary: #111827;  /* gray-900 | @against bg-primary,bg-surface */`
  const pairs = extractPairs(block)
  assert.equal(pairs.length, 2)
  assert.deepEqual(pairs[0], { fg: '--color-text-primary', bg: '--color-bg-primary' })
  assert.deepEqual(pairs[1], { fg: '--color-text-primary', bg: '--color-bg-surface' })
})

test('@against 없으면 빈 배열 반환', () => {
  const block = `--color-text-primary: #111827;  /* gray-900 — 일반 주석 */`
  const pairs = extractPairs(block)
  assert.equal(pairs.length, 0)
})

test('블록이 비어 있으면 빈 배열 반환', () => {
  assert.equal(extractPairs('').length, 0)
})

test('주석 종결자 */ 가 토큰 이름에 포함되지 않음', () => {
  const block = `--color-action-text: #ffffff;  /* white | @against action-bg,action-hover */`
  const pairs = extractPairs(block)
  assert.equal(pairs.length, 2)
  for (const { bg } of pairs) {
    assert.ok(
      /^--color-[\w-]+$/.test(bg),
      `bg 토큰에 특수문자 포함됨: "${bg}"`
    )
  }
})

test('빈/공백 콤마 항목은 필터링됨', () => {
  // 콤마만 있거나 공백만 있는 항목 → --color- 만 생성 → 필터에서 제거
  const block = `--color-text-foo: #aabbcc;  /* @against , ,bg-bar */`
  const pairs = extractPairs(block)
  assert.equal(pairs.length, 1, '유효한 항목만 남아야 함')
  assert.equal(pairs[0].bg, '--color-bg-bar')
})

test('여러 줄에 걸친 복수 토큰 파싱', () => {
  const block = [
    `--color-text-primary: #111827;  /* | @against bg-primary,bg-surface */`,
    `--color-text-link:    #1d4ed8;  /* | @against bg-primary */`,
  ].join('\n')
  const pairs = extractPairs(block)
  assert.equal(pairs.length, 3)
  assert.equal(pairs[0].fg, '--color-text-primary')
  assert.equal(pairs[2].fg, '--color-text-link')
})

test('하이픈 포함 배경 토큰 파싱 (bubble-agent 등)', () => {
  const block = `--color-text-mention: #93c5fd;  /* blue-300 | @against bg-bubble-agent */`
  const pairs = extractPairs(block)
  assert.equal(pairs.length, 1)
  assert.equal(pairs[0].bg, '--color-bg-bubble-agent')
})

// ─── buildChecks 테스트 ───────────────────────────────────────────────────────

test('buildChecks: 라이트·다크 양방향 생성', () => {
  const pairs = [{ fg: '--color-text-primary', bg: '--color-bg-primary' }]
  const checks = buildChecks(pairs)
  assert.equal(checks.length, 2)
  const [light, dark] = checks
  assert.equal(light[1], 'light')
  assert.equal(dark[1],  'dark')
})

test('buildChecks: 라벨 형식 — [Light]/[Dark] 접두사', () => {
  const pairs = [{ fg: '--color-text-primary', bg: '--color-bg-primary' }]
  const [light, dark] = buildChecks(pairs)
  assert.ok(light[0].startsWith('[Light]'), `라이트 라벨: "${light[0]}"`)
  assert.ok(dark[0].startsWith('[Dark]'),   `다크 라벨:  "${dark[0]}"`)
})

test('buildChecks: fg/bg 토큰이 그대로 전달됨', () => {
  const pairs = [{ fg: '--color-text-link', bg: '--color-bg-primary' }]
  const [light] = buildChecks(pairs)
  assert.equal(light[2], '--color-text-link')
  assert.equal(light[3], '--color-bg-primary')
})

test('buildChecks: isLarge 기본값 false', () => {
  const pairs = [{ fg: '--color-text-primary', bg: '--color-bg-primary' }]
  const [light] = buildChecks(pairs)
  assert.equal(light[4], false)
})

test('buildChecks: 빈 pairs → 빈 배열', () => {
  assert.equal(buildChecks([]).length, 0)
})

test('buildChecks: n쌍 → 2n 항목', () => {
  const pairs = [
    { fg: '--color-text-primary',   bg: '--color-bg-primary' },
    { fg: '--color-text-primary',   bg: '--color-bg-surface' },
    { fg: '--color-text-secondary', bg: '--color-bg-primary' },
  ]
  assert.equal(buildChecks(pairs).length, 6)
})

// ─── 결과 출력 ────────────────────────────────────────────────────────────────

console.log(`\n${'─'.repeat(50)}`)
if (failed > 0) {
  console.error(`\n실패: ${failed}개 / 전체 ${passed + failed}개\n`)
  process.exit(1)
} else {
  console.log(`\n통과: 모든 ${passed}개 테스트 ✓\n`)
  process.exit(0)
}
