// A code scene that is one full-frame canvas, drawn without a screenshot per frame: the page hands its canvas pixels straight
// to the encoder. Same page, same seek events as the engine, so the same picture (bridge\motion.py chooses it, falls back to
// the engine on anything it can't do, and tests\t61 compares the two frame by frame).
// usage: node canvas-render.js <job.json>
// job: {browser, page, width, height, fps, frames, out, ffmpeg, pages, chunk, encode: [ffmpeg output args]}
// One JSON line at the end: {ok, frames, ms} or {fatal}.
const fs = require('fs');
const http = require('http');
const path = require('path');
const { spawn } = require('child_process');
const { pathToFileURL } = require('url');
const engine = path.join(__dirname, '..', 'engine', 'node_modules');
const puppeteer = require(path.join(engine, 'puppeteer-core'));
const { WebSocketServer } = require(path.join(engine, 'ws'));

const job = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const FRAME_BYTES = job.width * job.height * 4;
const chunkFrames = job.chunk || 12;
const pages = job.pages || 3;

function fail(message) {
  console.log(JSON.stringify({ fatal: String(message).slice(0, 1500) }));
  process.exit(1);
}

(async () => {
  const started = Date.now();
  const encoder = spawn(job.ffmpeg, ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgba',
    '-s', `${job.width}x${job.height}`, '-r', String(job.fps), '-i', '-', ...job.encode, job.out],
  { stdio: ['pipe', 'ignore', 'pipe'], windowsHide: true });
  let encoderError = '';
  encoder.stderr.on('data', d => { encoderError += d; });
  const encoderDone = new Promise(resolve => encoder.on('close', resolve));
  encoder.stdin.on('error', e => fail(`the encoder stopped: ${e.message} ${encoderError}`));

  // Frames arrive from any page; they go to the encoder in order, and a page waits while too much is ahead.
  const ready = new Map();
  let nextFrame = 0;
  let wake = null;
  let draining = false;
  function pump() {
    while (!draining && ready.has(nextFrame)) {
      const buffer = ready.get(nextFrame);
      ready.delete(nextFrame);
      nextFrame += 1;
      if (!encoder.stdin.write(buffer)) {
        draining = true;
        encoder.stdin.once('drain', () => { draining = false; pump(); });
      }
    }
    if (wake) { const w = wake; wake = null; w(); }
  }

  const server = http.createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const sockets = new WebSocketServer({ server, maxPayload: FRAME_BYTES + 16 });
  const port = server.address().port;
  sockets.on('connection', socket => {
    socket.on('message', data => {
      const frame = data.readUInt32LE(0);
      ready.set(frame, data.subarray(4));
      pump();
      socket.send(String(frame));
    });
  });

  const browser = await puppeteer.launch({
    executablePath: job.browser, headless: /headless-shell/i.test(job.browser) ? 'shell' : true,
    args: ['--disable-background-networking', '--disable-extensions', '--no-first-run', '--disable-features=Translate',
      '--disable-gpu', '--force-color-profile=srgb', '--font-render-hinting=none', '--disable-background-timer-throttling',
      '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding', '--edge-skip-compat-layer-relaunch',
      '--allow-file-access-from-files'],   // a scene's photos sit beside its page: without this they taint the canvas (T78)
  });

  let nextChunk = 0;
  const lastChunk = Math.ceil(job.frames / chunkFrames);
  async function work() {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(String((e && e.message) || e)));
    await page.setViewport({ width: job.width, height: job.height, deviceScaleFactor: 1 });
    await page.goto(pathToFileURL(job.page).href, { waitUntil: 'load' });
    await page.evaluate(() => Promise.all(Object.values((window.__hf || {}).buildReady || {})));
    await page.evaluate(() => document.fonts.ready.then(() => null));
    // Only what the canvas holds may show: the page has nothing else, and nothing changes how the browser would show it.
    const fit = await page.evaluate((w, h) => {
      const stage = document.querySelector('#stage');
      const c = stage && stage.querySelector('canvas');
      const seen = document.body.querySelectorAll(':not(script):not(style)').length;
      if (!c || seen !== 3 || c.width !== w || c.height !== h) return 'not one full-frame canvas';
      const box = c.getBoundingClientRect();
      if (box.left !== 0 || box.top !== 0 || box.width !== w || box.height !== h) return 'the canvas is not shown at full size';
      for (const el of [c, stage, stage.parentElement, document.body]) {
        const st = getComputedStyle(el);
        if (st.opacity !== '1' || st.filter !== 'none' || st.mixBlendMode !== 'normal' || st.transform !== 'none'
            || st.visibility !== 'visible' || st.display === 'none') return 'the page changes how the canvas shows';
      }
      const sign = () => [c.style.cssText, stage.style.cssText, c.className, stage.className,
        document.body.querySelectorAll(':not(script):not(style)').length, c.width, c.height].join('|');
      window.__canvasSign = sign;
      window.__canvasSigned = sign();
      return '';
    }, job.width, job.height);
    if (fit) throw new Error(fit);
    await page.evaluate(port_ => new Promise((resolve, reject) => {
      const socket = new WebSocket(`ws://127.0.0.1:${port_}`);
      socket.binaryType = 'arraybuffer';
      window.__canvasRender = { socket, waiting: null };
      socket.onopen = resolve;
      socket.onerror = () => reject(new Error('no connection to the encoder'));
      socket.onmessage = () => { const w = window.__canvasRender.waiting; window.__canvasRender.waiting = null; if (w) w(); };
    }), port);
    while (nextChunk < lastChunk) {
      const chunk = nextChunk;
      nextChunk += 1;
      const first = chunk * chunkFrames;
      const last = Math.min(job.frames, first + chunkFrames);
      while (first >= nextFrame + chunkFrames * pages) {
        await new Promise(resolve => { const w = wake; wake = () => { if (w) w(); resolve(); }; });
      }
      await page.evaluate(async (a, b, fps, w, h) => {
        const c = document.querySelector('#stage canvas');
        const g = c.getContext('2d');
        const state = window.__canvasRender;
        for (let i = a; i < b; i += 1) {
          window.dispatchEvent(new CustomEvent('hf-seek', { detail: { time: i / fps } }));
          if (window.__canvasSign() !== window.__canvasSigned) throw new Error('the page changed while drawing');
          const pixels = g.getImageData(0, 0, w, h).data;
          const out = new Uint8Array(pixels.length + 4);
          new DataView(out.buffer).setUint32(0, i, true);
          out.set(pixels, 4);
          const answered = new Promise(resolve => { state.waiting = resolve; });
          state.socket.send(out.buffer);
          await answered;
        }
      }, first, last, job.fps, job.width, job.height);
      if (errors.length) throw new Error(errors[0]);
    }
    await page.close();
  }
  await Promise.all(Array.from({ length: pages }, work));
  await browser.close();
  while (nextFrame < job.frames) {
    await new Promise(resolve => { const w = wake; wake = () => { if (w) w(); resolve(); }; });
  }
  encoder.stdin.end();
  const code = await encoderDone;
  server.close();
  if (code !== 0) fail(`the encoder failed: ${encoderError}`);
  console.log(JSON.stringify({ ok: true, frames: job.frames, ms: Date.now() - started }));
  process.exit(0);
})().catch(e => fail((e && e.stack) || e));
