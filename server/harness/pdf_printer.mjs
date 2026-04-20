#!/usr/bin/env node
// stdin으로 {html, output_path, format?} JSON 받아 PDF 저장
// 요구: npm i puppeteer
import { readFileSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';

async function main() {
  const payload = JSON.parse(readFileSync(0, 'utf-8'));
  const { html, output_path, format = 'A4' } = payload;

  let puppeteer;
  try {
    puppeteer = (await import('puppeteer')).default;
  } catch (e) {
    process.stdout.write(JSON.stringify({ error: 'puppeteer 모듈 없음 — npm i puppeteer' }));
    return;
  }

  mkdirSync(dirname(output_path), { recursive: true });
  let browser;
  try {
    browser = await puppeteer.launch({ headless: 'new', args: ['--no-sandbox'] });
    const page = await browser.newPage();
    await page.setContent(html, { waitUntil: 'networkidle0', timeout: 30000 });
    await page.pdf({
      path: output_path,
      format,
      printBackground: true,
      margin: { top: '20mm', bottom: '20mm', left: '15mm', right: '15mm' },
    });
    process.stdout.write(JSON.stringify({ path: output_path }));
  } catch (e) {
    process.stdout.write(JSON.stringify({ error: String(e).slice(0, 400) }));
  } finally {
    if (browser) await browser.close().catch(() => {});
  }
}

main().catch((e) => {
  process.stdout.write(JSON.stringify({ error: String(e).slice(0, 400) }));
});
