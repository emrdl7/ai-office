#!/usr/bin/env node
// stdin으로 HTML 받아 axe-core로 a11y 검증 후 JSON 출력
// 요구: npm i puppeteer axe-core  (없으면 error JSON 반환)
import { readFileSync } from 'node:fs';

async function main() {
  const html = readFileSync(0, 'utf-8');
  let puppeteer, axe;
  try {
    puppeteer = (await import('puppeteer')).default;
  } catch (e) {
    process.stdout.write(JSON.stringify({ error: 'puppeteer 모듈 없음 — npm i puppeteer' }));
    return;
  }
  try {
    axe = await import('axe-core');
  } catch (e) {
    process.stdout.write(JSON.stringify({ error: 'axe-core 모듈 없음 — npm i axe-core' }));
    return;
  }

  let browser;
  try {
    browser = await puppeteer.launch({ headless: 'new', args: ['--no-sandbox'] });
    const page = await browser.newPage();
    await page.setContent(html, { waitUntil: 'domcontentloaded' });
    await page.addScriptTag({ content: axe.source });
    const result = await page.evaluate(async () => {
      // @ts-ignore
      return await axe.run(document, {
        resultTypes: ['violations', 'passes'],
        runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] },
      });
    });

    const violations = (result.violations || []).map((v) => ({
      id: v.id,
      impact: v.impact || 'unknown',
      description: v.description || '',
      help: v.help || '',
      count: (v.nodes || []).length,
    }));
    process.stdout.write(JSON.stringify({
      a11y: {
        violation_count: violations.length,
        passes: (result.passes || []).length,
        violations,
      },
    }));
  } catch (e) {
    process.stdout.write(JSON.stringify({ error: String(e).slice(0, 400) }));
  } finally {
    if (browser) await browser.close().catch(() => {});
  }
}

main().catch((e) => {
  process.stdout.write(JSON.stringify({ error: String(e).slice(0, 400) }));
});
