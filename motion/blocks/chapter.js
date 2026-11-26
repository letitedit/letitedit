/*@block
{"title": "Chapter", "about": "A chapter marker: a big number and the chapter's name, with a line that draws across. Transparent, so it sits over the opening shot of the section.",
 "duration": 3.5,
 "params": {"number": "01", "title": "Chapter name", "kicker": "Chapter", "font": "heading", "body_font": "body",
            "size": 84, "number_size": 200, "fill": "light", "number_fill": "accent", "position": "left", "dim": true},
 "docs": {"position": "left | center", "dim": "true = a soft dark gradient behind the text so it reads on bright footage",
          "number": "any short text: '01', '2', 'IV', 'Day 3'"}}
@*/
M.block('chapter', (stage, p, c) => {
  const u = c.u, centered = p.position === 'center';
  let dim = null;
  if (p.dim) {
    dim = M.el('div', { style: { position: 'absolute', inset: '0', background: centered
      ? 'radial-gradient(ellipse at center, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0) 65%)'
      : 'linear-gradient(90deg, rgba(0,0,0,0.6) 0%, rgba(0,0,0,0.25) 45%, rgba(0,0,0,0) 70%)' } }, stage);
  }
  const box = M.el('div', { style: { position: 'absolute', top: '50%', display: 'flex', flexDirection: 'column',
    alignItems: centered ? 'center' : 'flex-start', gap: `${6 * u}px` } }, stage);
  if (centered) { box.style.left = '50%'; box.style.transform = 'translate(-50%, -50%)'; }
  else { box.style.left = `${c.w * 0.08}px`; box.style.transform = 'translateY(-50%)'; }
  const shadow = `0 ${4 * u}px ${18 * u}px rgba(0,0,0,0.55)`;
  const kick = p.kicker ? c.style(M.el('div', { text: p.kicker, style: { textTransform: 'uppercase', letterSpacing: `${8 * u}px`, textShadow: shadow } }, box), p.body_font, 34 * u, 'light') : null;
  const num = c.style(M.el('div', { text: p.number, style: { lineHeight: '0.9', textShadow: shadow } }, box), p.font, p.number_size * u, p.number_fill);
  const line = M.el('div', { style: { height: `${6 * u}px`, width: `${Math.min(c.w * 0.5, 520 * u)}px`, background: c.color('light'), transformOrigin: centered ? 'center' : 'left center', margin: `${10 * u}px 0` } }, box);
  const title = c.style(M.el('div', { text: p.title, style: { lineHeight: '1.05', textShadow: shadow, maxWidth: `${c.w * 0.8}px` } }, box), p.font, p.size * u, p.fill);
  M.fit(title, p.size * u, c.w * 0.8);
  return (t) => {
    const out = M.prog(t, c.len - 0.45, 0.45, 'in');
    if (dim) M.set(dim, { o: Math.min(M.prog(t, 0, 0.5, 'out'), 1 - out) });
    if (kick) M.set(kick, { o: Math.min(M.prog(t, 0.05, 0.3, 'linear'), 1 - out) });
    M.set(num, { o: Math.min(M.prog(t, 0.1, 0.25, 'linear'), 1 - out), y: (1 - M.prog(t, 0.1, 0.6, 'expoOut')) * 60 * u, s: 1 + 0.15 * (1 - M.prog(t, 0.1, 0.6, 'expoOut')) });
    M.set(line, { sx: M.prog(t, 0.3, 0.7, 'expoOut') * (1 - out) });
    M.set(title, { o: 1 - out, clip: [0, 1 - M.prog(t, 0.45, 0.7, 'expoOut'), 0, 0] });
  };
});
