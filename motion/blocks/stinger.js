/*@block
{"title": "Stinger", "about": "A short intro or section transition: coloured bands sweep across the frame, a word or logo line flashes up on them, and the bands sweep off, uncovering the next shot. Fully covers the frame mid-way, so a cut placed at the middle is hidden.",
 "duration": 1.6,
 "params": {"text": "NEXT UP", "colors": ["accent", "secondary", "dark"], "direction": "right", "font": "heading", "size": 150,
            "fill": "light", "angle": -12},
 "docs": {"colors": "2-4 band colours, front to back", "direction": "right | left | up | down (where the bands travel)",
          "angle": "slant of the bands in degrees", "text": "optional word shown while the frame is covered"}}
@*/
M.block('stinger', (stage, p, c) => {
  const u = c.u;
  const cols = (p.colors && p.colors.length ? p.colors : ['accent', 'secondary', 'dark']).slice(0, 4);
  const vertical = p.direction === 'up' || p.direction === 'down';
  const sign = p.direction === 'left' || p.direction === 'up' ? -1 : 1;
  const span = (vertical ? c.h : c.w) * 1.6;
  const bands = cols.map((col, i) => M.el('div', { style: { position: 'absolute', left: `${-c.w * 0.3}px`, top: `${-c.h * 0.3}px`,
    width: `${c.w * 1.6}px`, height: `${c.h * 1.6}px`, background: c.color(col), zIndex: String(cols.length - i) } }, stage));
  let text = null;
  if (p.text) {
    text = c.style(M.el('div', { text: p.text, style: { position: 'absolute', left: '50%', top: '50%', whiteSpace: 'nowrap', zIndex: '10', letterSpacing: `${2 * u}px` } }, stage), p.font, p.size * u, p.fill);
    M.fit(text, p.size * u, c.w * 0.85);
  }
  const L = c.len;
  return (t) => {
    // each band: in from one side to cover (by 45% of the clip), out the other side (from 55%)
    bands.forEach((b, i) => {
      const lag = (cols.length - 1 - i) * 0.06 * L;   // back bands lead in, front bands lead out
      const inK = M.prog(t, lag * 0.5, 0.42 * L, 'inOut');
      const outK = M.prog(t, 0.55 * L + i * 0.05 * L, 0.4 * L, 'inOut');
      const pos = (-1 + inK) * span + outK * span;
      b.style.transform = vertical ? `translateY(${(sign * pos).toFixed(1)}px) skewY(${p.angle}deg)` : `translateX(${(sign * pos).toFixed(1)}px) skewX(${p.angle}deg)`;
    });
    if (text) {
      const k = M.prog(t, 0.3 * L, 0.2 * L, 'backOut');
      const o = Math.min(M.prog(t, 0.3 * L, 0.1 * L, 'linear'), 1 - M.prog(t, 0.6 * L, 0.1 * L, 'linear'));
      text.style.opacity = String(o);
      text.style.transform = `translate(-50%, -50%) scale(${(0.7 + 0.3 * k).toFixed(4)})`;
    }
  };
});
