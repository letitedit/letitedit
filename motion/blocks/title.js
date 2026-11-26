/*@block
{"title": "Title", "about": "A big title (and optional subtitle) that builds in word by word, holds and leaves. For openers, section titles and video names.",
 "duration": 4.0,
 "params": {"title": "Your title here", "subtitle": "", "kicker": "", "position": "center", "align": "center",
            "font": "heading", "subtitle_font": "body", "size": 150, "subtitle_size": 54, "fill": "light",
            "subtitle_fill": "secondary", "accent": "accent", "style": "rise", "backdrop": "none", "shadow": true,
            "max_width": 0.84},
 "docs": {"position": "center | top | bottom", "align": "center | left", "style": "rise (words rise in) | pop (words scale up) | wipe (revealed left to right) | blur (words sharpen in)",
          "backdrop": "none | band (a dark band behind the text) | underline (an accent line grows under the title)",
          "kicker": "small line above the title, e.g. 'Episode 3'", "max_width": "share of the frame width the title may use (it shrinks to fit)"}}
@*/
M.block('title', (stage, p, c) => {
  const u = c.u;
  const box = M.el('div', { style: { position: 'absolute', left: '0', right: '0', display: 'flex', flexDirection: 'column',
    alignItems: p.align === 'left' ? 'flex-start' : 'center', padding: `0 ${c.w * (1 - p.max_width) / 2}px`, gap: `${14 * u}px` } }, stage);
  if (p.position === 'top') box.style.top = `${c.h * 0.12}px`;
  else if (p.position === 'bottom') box.style.bottom = `${c.h * 0.14}px`;
  else { box.style.top = '50%'; box.style.transform = 'translateY(-50%)'; }
  const shadow = p.shadow ? `0 ${4 * u}px ${18 * u}px rgba(0,0,0,0.55)` : 'none';
  let band = null;
  if (p.backdrop === 'band') {
    band = M.el('div', { style: { position: 'absolute', left: '0', right: '0', background: c.color('dark') + 'C8' } }, stage);
  }
  let kicker = null;
  if (p.kicker) {
    kicker = c.style(M.el('div', { text: p.kicker, style: { letterSpacing: `${0.18 * p.subtitle_size * u}px`, textTransform: 'uppercase', textShadow: shadow } }, box),
      p.subtitle_font, p.subtitle_size * 0.8 * u, p.accent);
  }
  const title = c.style(M.el('div', { text: p.title, style: { lineHeight: '1.02', textAlign: p.align, textWrap: 'balance', textShadow: shadow, maxWidth: `${c.w * p.max_width}px` } }, box),
    p.font, p.size * u, p.fill);
  M.fit(title, p.size * u, c.w * p.max_width, c.h * 0.5);
  const words = M.split(title, 'words');
  const rects = words.map((w) => w.getBoundingClientRect());
  const textW = rects.length ? Math.max(...rects.map((r) => r.right)) - Math.min(...rects.map((r) => r.left)) : 0;
  let line = null;
  if (p.backdrop === 'underline') {
    line = M.el('div', { style: { height: `${10 * u}px`, marginTop: `${8 * u}px`, width: `${textW}px`, background: c.color(p.accent), borderRadius: `${5 * u}px`, transformOrigin: p.align === 'left' ? 'left center' : 'center' } }, box);
  }
  let sub = null, subWords = [];
  if (p.subtitle) {
    sub = c.style(M.el('div', { text: p.subtitle, style: { textAlign: p.align, textShadow: shadow, maxWidth: `${c.w * p.max_width}px` } }, box),
      p.subtitle_font, p.subtitle_size * u, p.subtitle_fill);
    M.fit(sub, p.subtitle_size * u, c.w * p.max_width);
    subWords = M.split(sub, 'words');
  }
  if (band) {
    const r = box.getBoundingClientRect();
    band.style.top = `${r.top - 40 * u}px`;
    band.style.height = `${r.height + 80 * u}px`;
  }
  const stagger = Math.min(0.09, 0.9 / Math.max(1, words.length));
  const outDur = 0.45;
  const show = (e, t, start, i) => {
    const k = M.prog(t, start, 0.55, p.style === 'pop' ? 'backOut' : 'expoOut');
    const out = M.prog(t, c.len - outDur, outDur, 'in');
    const o = Math.min(M.prog(t, start, 0.3, 'linear'), 1 - out);
    if (p.style === 'pop') M.set(e, { o, s: 0.4 + 0.6 * k, y: -out * 30 * u });
    else if (p.style === 'blur') M.set(e, { o, blur: (1 - k) * 18 * u + out * 10 * u, y: -out * 30 * u });
    else if (p.style === 'wipe') M.set(e, { o: 1 - out, clip: [0, 1 - k, 0, 0], y: -out * 30 * u });
    else M.set(e, { o, y: (1 - k) * 70 * u - out * 40 * u });
  };
  return (t) => {
    if (band) M.set(band, { o: M.life(t, c.len, 0.35, 0.4), clip: [0, 1 - M.prog(t, 0, 0.5, 'expoOut'), 0, 0] });
    if (kicker) show(kicker, t, 0.0, 0);
    words.forEach((w, i) => show(w, t, 0.12 + i * stagger, i));
    if (line) M.set(line, { sx: M.prog(t, 0.35, 0.6, 'expoOut') * (1 - M.prog(t, c.len - outDur, outDur, 'in')) });
    const subStart = 0.25 + words.length * stagger;
    subWords.forEach((w, i) => show(w, t, subStart + i * 0.04, i));
  };
});
