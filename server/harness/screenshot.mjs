#!/usr/bin/env node
// stdin으로 {html, output_dir, job_id, viewports} JSON 받아 mobile/tablet/desktop PNG 저장
// 요구: npm i puppeteer
import { readFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';

async function main() {
  const payload = JSON.parse(readFileSync(0, 'utf-8'));
  const { html, output_dir, job_id, viewports } = payload;

  let puppeteer;
  try {
    puppeteer = (await import('puppeteer')).default;
  } catch (e) {
    process.stdout.write(JSON.stringify({ error: 'puppeteer 모듈 없음 — npm i puppeteer' }));
    return;
  }

  mkdirSync(output_dir, { recursive: true });
  const screenshots = {};
  let browser;
  try {
    browser = await puppeteer.launch({ headless: 'new', args: ['--no-sandbox'] });
    for (const [name, vp] of Object.entries(viewports || {})) {
      const page = await browser.newPage();
      await page.setViewport({ width: vp.width, height: vp.height, deviceScaleFactor: 1 });
      await page.setContent(html, { waitUntil: 'networkidle0', timeout: 30000 });
      const path = join(output_dir, `${job_id}-${name}.png`);
      await page.screenshot({ path, fullPage: true });
      screenshots[name] = path;
      await page.close();
    }
    process.stdout.write(JSON.stringify({ screenshots }));
  } catch (e) {
    process.stdout.write(JSON.stringify({ error: String(e).slice(0, 400), screenshots }));
  } finally {
    if (browser) await browser.close().catch(() => {});
  }
}

main().catch((e) => {
  process.stdout.write(JSON.stringify({ error: String(e).slice(0, 400) }));
});
