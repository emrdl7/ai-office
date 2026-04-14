#!/usr/bin/env node
/**
 * check-contrast.mjs 테스트
 * 실행: node scripts/check-contrast.test.mjs
 *
 * [단위 테스트] extractPairs, buildChecks — 인라인 CSS 문자열로 순수 함수 검증
 * [통합 테스트] 실제 tokens.css 파일을 읽어 전체 파이프라인(parse→build→check→unchecked 감지) 검증
 *
 * check-contrast.mjs에서 직접 import하므로 로직 이중화 없음.
 */

import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'
import {
  extractPairs,
  buildChecks,
  parseColorTokens,
  findUncheckedTokens,
} from './check-contrast.mjs'

const __dirname = dirname(fileURLToPath(import.meta.url))

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

async function testAsync(name, fn) {
  try {
    await fn()
    console.log(`✅  ${name}`)
    passed++
  } catch (e) {
    console.error(`❌  ${name}`)
    console.error(`    ${e.message}`)
    failed++
  }
}

// ─── extractPairs 단위 테스트 ─────────────────────────────────────────────────

console.log('\nextractPairs')

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

test('bg- 접두사 없는 @against 토큰 파싱 (action-bg 형식)', () => {
  const block = `--color-action-text: #ffffff;  /* white | @against action-bg,action-hover */`
  const pairs = extractPairs(block)
  assert.equal(pairs.length, 2)
  assert.equal(pairs[0].bg, '--color-action-bg')
  assert.equal(pairs[1].bg, '--color-action-hover')
})

// ─── buildChecks 단위 테스트 ──────────────────────────────────────────────────

console.log('\nbuildChecks')

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

// ─── 통합 테스트: 실제 tokens.css 파일 ───────────────────────────────────────
// parse → build → findUnchecked 전체 흐름을 실제 파일로 검증합니다.
// tokens.css가 없는 CI 환경(예: 서버 전용 빌드)에서는 통합 테스트를 건너뜁니다.

console.log('\n통합 테스트 (실제 tokens.css)')

const tokensPath = resolve(__dirname, '../src/tokens.css')

if (!existsSync(tokensPath)) {
  console.log(`⚠️  tokens.css 없음 (${tokensPath}) — 통합 테스트 건너뜀`)
  console.log(`   파일을 생성하거나 dashboard/ 디렉터리에서 실행하세요.`)
}

const tokensExist = existsSync(tokensPath)

function testIfTokens(name, fn) {
  if (!tokensExist) {
    console.log(`⏭️  (skip) ${name}`)
    return
  }
  test(name, fn)
}

testIfTokens('tokens.css 파싱 성공 — pairs 1개 이상', () => {
  const tokens = parseColorTokens(tokensPath)
  assert.ok(tokens.pairs.length > 0, `@against 파싱 결과가 비어 있음`)
})

testIfTokens('tokens.css 라이트 토큰 추출 — --color-text-primary 존재', () => {
  const tokens = parseColorTokens(tokensPath)
  assert.ok(
    tokens.light.has('--color-text-primary'),
    '라이트 맵에 --color-text-primary 없음'
  )
})

testIfTokens('tokens.css 다크 토큰 추출 — --color-bg-primary 존재', () => {
  const tokens = parseColorTokens(tokensPath)
  assert.ok(
    tokens.dark.has('--color-bg-primary'),
    '다크 맵에 --color-bg-primary 없음'
  )
})

testIfTokens('tokens.css — 미검사 토큰 없음 (모든 --color-* 가 @against로 커버됨)', () => {
  const tokens = parseColorTokens(tokensPath)
  const unchecked = findUncheckedTokens(tokens)
  if (unchecked.length > 0) {
    const names = unchecked.map(u => `${u.mode} ${u.name}`).join(', ')
    assert.fail(`@against 미등록 토큰 ${unchecked.length}개: ${names}`)
  }
})

testIfTokens('tokens.css — buildChecks 결과가 pairs * 2 개', () => {
  const tokens = parseColorTokens(tokensPath)
  const checks = buildChecks(tokens.pairs)
  assert.equal(checks.length, tokens.pairs.length * 2)
})

testIfTokens('tokens.css — @against 배경 토큰이 covered 집합에 포함됨 (action-hover 등)', () => {
  const tokens = parseColorTokens(tokensPath)
  // pairs의 bg 목록을 수집
  const bgsCovered = new Set(tokens.pairs.map(p => p.bg))
  // 라이트 맵에 있는 배경 계열 토큰이 covered 집합에 포함되는지 확인
  for (const [name] of tokens.light) {
    // 배경(bg-* 또는 action-bg/action-hover)으로만 쓰이는 토큰은
    // fg 쌍이 없어도 bgsCovered에 있으면 OK
    const covered = bgsCovered.has(name) || tokens.pairs.some(p => p.fg === name)
    if (!covered) {
      assert.fail(`라이트 토큰 ${name}이 pairs에 전혀 등장하지 않음`)
    }
  }
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
