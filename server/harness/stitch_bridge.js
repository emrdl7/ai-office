// Stitch SDK 브릿지 — Python에서 subprocess로 호출
// 사용법: node stitch_bridge.js generate "프롬프트 텍스트" [output_dir]
//         node stitch_bridge.js edit "screen_id" "수정 프롬프트" [output_dir]
const { stitch } = require('@google/stitch-sdk')
const fs = require('fs')
const path = require('path')
const https = require('https')
const http = require('http')

const [,, action, ...args] = process.argv

async function downloadFile(url, dest) {
  return new Promise((resolve, reject) => {
    const proto = url.startsWith('https') ? https : http
    const file = fs.createWriteStream(dest)
    proto.get(url, (res) => {
      res.pipe(file)
      file.on('finish', () => { file.close(); resolve(dest) })
    }).on('error', (e) => { fs.unlink(dest, () => {}); reject(e) })
  })
}

async function generate(prompt, outputDir) {
  fs.mkdirSync(outputDir, { recursive: true })

  // 프로젝트 생성 또는 기존 사용
  const project = stitch.project()
  const screen = await project.generate(prompt)

  // HTML 다운로드
  const htmlUrl = await screen.getHtml()
  const htmlPath = path.join(outputDir, 'design.html')
  if (htmlUrl) {
    await downloadFile(htmlUrl, htmlPath)
  }

  // 스크린샷 다운로드
  const imageUrl = await screen.getImage()
  const imagePath = path.join(outputDir, 'design.png')
  if (imageUrl) {
    await downloadFile(imageUrl, imagePath)
  }

  console.log(JSON.stringify({
    success: true,
    screen_id: screen.id || 'unknown',
    html_path: fs.existsSync(htmlPath) ? htmlPath : null,
    image_path: fs.existsSync(imagePath) ? imagePath : null,
    html_url: htmlUrl,
    image_url: imageUrl,
  }))
}

async function edit(screenId, prompt, outputDir) {
  fs.mkdirSync(outputDir, { recursive: true })

  const project = stitch.project()
  const screen = await project.getScreen(screenId)
  const updated = await screen.edit(prompt)

  const htmlUrl = await updated.getHtml()
  const htmlPath = path.join(outputDir, 'design.html')
  if (htmlUrl) await downloadFile(htmlUrl, htmlPath)

  const imageUrl = await updated.getImage()
  const imagePath = path.join(outputDir, 'design.png')
  if (imageUrl) await downloadFile(imageUrl, imagePath)

  console.log(JSON.stringify({
    success: true,
    screen_id: updated.id || screenId,
    html_path: fs.existsSync(htmlPath) ? htmlPath : null,
    image_path: fs.existsSync(imagePath) ? imagePath : null,
  }))
}

async function main() {
  try {
    if (action === 'generate') {
      const prompt = args[0]
      const outputDir = args[1] || './output'
      await generate(prompt, outputDir)
    } else if (action === 'edit') {
      const screenId = args[0]
      const prompt = args[1]
      const outputDir = args[2] || './output'
      await edit(screenId, prompt, outputDir)
    } else {
      console.log(JSON.stringify({ success: false, error: `Unknown action: ${action}` }))
    }
  } catch (e) {
    console.log(JSON.stringify({ success: false, error: e.message }))
  }
}

main()
