/**
 * OpenAPI JSON → TypeScript 타입 자동 생성 (4-5)
 *
 * 사용법:
 *   node scripts/gen-types.mjs
 *
 * 입력:  src/openapi.json  (server/scripts/gen_openapi.py로 생성)
 * 출력:  src/api-types.ts  (자동 생성 — 직접 수정 금지)
 */
import { readFileSync, writeFileSync, existsSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(__dirname, '..')
const SCHEMA_PATH = resolve(ROOT, 'src/openapi.json')
const OUT_PATH = resolve(ROOT, 'src/api-types.ts')

if (!existsSync(SCHEMA_PATH)) {
  console.error('openapi.json 없음. 먼저 server/scripts/gen_openapi.py를 실행하세요.')
  process.exit(1)
}

const schema = JSON.parse(readFileSync(SCHEMA_PATH, 'utf8'))
const schemas = schema?.components?.schemas ?? {}

// OpenAPI 타입 → TypeScript 타입 매핑
function mapType(prop, schemas, depth = 0) {
  if (!prop) return 'unknown'
  if (prop.$ref) {
    const name = prop.$ref.split('/').pop()
    return name
  }
  if (prop.anyOf || prop.oneOf) {
    const types = (prop.anyOf || prop.oneOf).map(p => mapType(p, schemas, depth))
    return types.join(' | ')
  }
  if (prop.type === 'array') {
    return `${mapType(prop.items, schemas, depth)}[]`
  }
  if (prop.type === 'object') {
    if (prop.additionalProperties) {
      return `Record<string, ${mapType(prop.additionalProperties, schemas, depth)}>`
    }
    if (prop.properties) {
      const inner = Object.entries(prop.properties)
        .map(([k, v]) => `${k}: ${mapType(v, schemas, depth + 1)}`)
        .join('; ')
      return `{ ${inner} }`
    }
    return 'Record<string, unknown>'
  }
  const typeMap = {
    string: 'string',
    integer: 'number',
    number: 'number',
    boolean: 'boolean',
    null: 'null',
  }
  return typeMap[prop.type] ?? 'unknown'
}

function genInterface(name, schemaDef, allSchemas) {
  const lines = [`export interface ${name} {`]
  const props = schemaDef.properties ?? {}
  const required = new Set(schemaDef.required ?? [])

  for (const [key, prop] of Object.entries(props)) {
    const optional = !required.has(key) ? '?' : ''
    const tsType = mapType(prop, allSchemas)
    const desc = prop.description ? `  /** ${prop.description} */\n` : ''
    lines.push(`${desc}  ${key}${optional}: ${tsType}`)
  }
  lines.push('}')
  return lines.join('\n')
}

// 생성
const interfaces = []
const SKIP = new Set(['HTTPValidationError', 'ValidationError'])

for (const [name, def] of Object.entries(schemas)) {
  if (SKIP.has(name)) continue
  if (def.type !== 'object' && !def.properties) continue
  interfaces.push(genInterface(name, def, schemas))
}

// API 경로에서 파라미터 타입 추출 (주요 POST body)
const requestTypes = []
const paths = schema.paths ?? {}
for (const [path, methods] of Object.entries(paths)) {
  for (const [method, op] of Object.entries(methods)) {
    if (!op.requestBody) continue
    const content = op.requestBody?.content?.['application/json']?.schema
    if (!content) continue
    if (content.$ref) continue  // 이미 interface로 생성됨
    const opId = op.operationId?.replace(/_[a-z]+_api_/g, '_') ?? ''
    if (opId) {
      const typeName = opId.split('_').filter(Boolean).map(w => w[0].toUpperCase() + w.slice(1)).join('') + 'Body'
      requestTypes.push(`// ${method.toUpperCase()} ${path}\nexport type ${typeName} = ${mapType(content, schemas)}`)
    }
  }
}

const header = `// ⚠️ 자동 생성 파일 — 직접 수정 금지
// 생성: node scripts/gen-types.mjs  (입력: src/openapi.json)
// 소스: server/scripts/gen_openapi.py → FastAPI /openapi.json
`

const output = [header, ...interfaces, ...requestTypes].join('\n\n')
writeFileSync(OUT_PATH, output)

console.log(`[gen-types] 완료: ${OUT_PATH}`)
console.log(`  - 인터페이스: ${interfaces.length}개`)
console.log(`  - 요청 타입: ${requestTypes.length}개`)
