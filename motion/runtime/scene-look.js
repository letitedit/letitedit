// A browser that stays open and hands back frames of a code scene (letitedit's fast look; bridge\scene_look.py runs it).
// One JSON job per line on stdin, one JSON answer per line on stdout. It closes itself after `idle` seconds without a job
// and when stdin closes (the tool server exited), so nothing is left running.
// usage: node scene-look.js <browser exe> <idle seconds>
const fs = require('fs');
const path = require('path');
const readline = require('readline');
const { pathToFileURL } = require('url');
const puppeteer = require(path.join(__dirname, '..', 'engine', 'node_modules', 'puppeteer-core'));

const browserPath = process.argv[2];
const idleMs = Math.max(5, Number(process.argv[3] || 300)) * 1000;
let browser = null;
let idleTimer = null;

async function quit(code) {
  clearTimeout(idleTimer);
  try { if (browser) await browser.close(); } catch (e) { /* already gone */ }
  process.exit(code);
}
function rearm() {
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => quit(0), idleMs);
}

(async () => {
  const started = Date.now();
  browser = await puppeteer.launch({
    executablePath: browserPath, headless: /headless-shell/i.test(browserPath) ? 'shell' : true,
    args: ['--disable-background-networking', '--disable-extensions', '--no-first-run', '--disable-features=Translate',
      '--edge-skip-compat-layer-relaunch',
      '--allow-file-access-from-files'],   // a scene's photos sit beside its page: without this they taint the canvas (T78)
  });
  browser.on('disconnected', () => process.exit(0));
  const page = await browser.newPage();
  let errors = [];
  page.on('pageerror', e => errors.push(String((e && e.message) || e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  console.log(JSON.stringify({ ready_ms: Date.now() - started }));
  rearm();

  const lines = readline.createInterface({ input: process.stdin });
  lines.on('close', () => quit(0));
  for await (const line of lines) {
    if (!line.trim()) continue;
    clearTimeout(idleTimer);
    const job = JSON.parse(line);
    if (job.quit) await quit(0);
    errors = [];
    fs.mkdirSync(job.out, { recursive: true });
    const begin = Date.now();
    await page.setViewport({ width: job.width, height: job.height, deviceScaleFactor: 1 });
    await page.goto(pathToFileURL(job.page).href, { waitUntil: 'load' });
    try {
      await page.evaluate(() => Promise.all(Object.values((window.__hf || {}).buildReady || {})));
    } catch (e) {
      errors.push('the scene did not build: ' + String((e && e.message) || e));
    }
    const loaded = Date.now();
    const canvas = await page.evaluate(() => !!document.querySelector('#stage canvas'));
    const frames = [];
    for (const [i, time] of job.times.entries()) {
      const file = path.join(job.out, `scene-${String(i).padStart(5, '0')}.png`);
      let ok = false;
      try {
        if (canvas) {
          const data = await page.evaluate(t => {
            window.dispatchEvent(new CustomEvent('hf-seek', { detail: { time: t } }));
            const c = document.querySelector('#stage canvas');
            return c ? c.toDataURL('image/png') : null;
          }, time);
          if (data) { fs.writeFileSync(file, Buffer.from(data.split(',')[1], 'base64')); ok = true; }
        } else {
          // A scene drawn with page elements: a screenshot with a transparent background (slower).
          await page.evaluate(t => new Promise(resolve => {
            window.dispatchEvent(new CustomEvent('hf-seek', { detail: { time: t } }));
            requestAnimationFrame(() => requestAnimationFrame(resolve));
          }), time);
          await page.screenshot({ path: file, type: 'png', omitBackground: true });
          ok = true;
        }
      } catch (e) {
        errors.push(`at ${time.toFixed(2)} s: ` + String((e && e.message) || e));
      }
      frames.push(ok ? file : null);
    }
    // An error thrown inside an event listener is reported a moment after the seek returns.
    await new Promise(resolve => setTimeout(resolve, 20));
    console.log(JSON.stringify({ load_ms: loaded - begin, frames_ms: Date.now() - loaded, mode: canvas ? 'canvas' : 'screenshot',
                                 frames, errors: [...new Set(errors)] }));
    rearm();
  }
})().catch(e => { console.log(JSON.stringify({ fatal: String((e && e.message) || e) })); quit(1); });
