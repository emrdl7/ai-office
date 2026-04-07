// Stitch SDK 브릿지 — 디자인 생성 + HTML/스크린샷 다운로드
import { StitchToolClient } from '@google/stitch-sdk'
import fs from 'fs'
import path from 'path'

const [,, action, ...args] = process.argv
const apiKey = process.env.STITCH_API_KEY
const projectId = process.env.STITCH_PROJECT_ID || '16138809057658740976'

async function generate(prompt, outputDir) {
  fs.mkdirSync(outputDir, { recursive: true })
  const client = new StitchToolClient({ apiKey })

  try {
    const result = await client.callTool('generate_screen_from_text', {
      prompt, project_id: projectId,
    })

    // 스크린 데이터 추출
    const screens = result?.outputComponents?.[0]?.design?.screens || []
    const screen = screens[0]
    if (!screen) {
      console.log(JSON.stringify({ success: false, error: 'No screen generated' }))
      return
    }

    // HTML 다운로드
    let htmlPath = null
    const htmlUrl = screen.htmlCode?.downloadUrl
    if (htmlUrl) {
      htmlPath = path.join(outputDir, 'design.html')
      const resp = await fetch(htmlUrl)
      fs.writeFileSync(htmlPath, await resp.text())
    }

    // 스크린샷 다운로드
    let imagePath = null
    const imgUrl = screen.screenshot?.downloadUrl
    if (imgUrl) {
      imagePath = path.join(outputDir, 'design.png')
      const resp = await fetch(imgUrl)
      fs.writeFileSync(imagePath, Buffer.from(await resp.arrayBuffer()))
    }

    // 디자인 시스템 마크다운
    let designMdPath = null
    const designMd = screen.theme?.designMd || screen.designSystem?.designSystem?.theme?.designMd
    if (designMd) {
      designMdPath = path.join(outputDir, 'design_system.md')
      fs.writeFileSync(designMdPath, designMd)
    }

    console.log(JSON.stringify({
      success: true,
      title: screen.title || '',
      screen_id: screen.id,
      html_path: htmlPath,
      image_path: imagePath,
      design_md_path: designMdPath,
    }))
  } catch (e) {
    console.log(JSON.stringify({ success: false, error: e.message || String(e) }))
  } finally {
    await client.close()
  }
}

// stdin에서 프롬프트 읽기 헬퍼
function readStdin() {
  return new Promise((resolve) => {
    let data = ''
    process.stdin.setEncoding('utf-8')
    process.stdin.on('data', (chunk) => { data += chunk })
    process.stdin.on('end', () => resolve(data))
  })
}

try {
  if (action === 'generate') {
    // --stdin 플래그면 stdin에서 프롬프트 읽기, 아니면 인자에서
    let prompt, outputDir
    if (args[0] === '--stdin') {
      prompt = await readStdin()
      outputDir = args[1] || './output'
    } else {
      prompt = args[0]
      outputDir = args[1] || './output'
    }
    await generate(prompt, outputDir)
  } else {
    console.log(JSON.stringify({ success: false, error: `Unknown: ${action}` }))
  }
} catch (e) {
  console.log(JSON.stringify({ success: false, error: e.message }))
}
