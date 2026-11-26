/*@block
{"title": "Location tag", "about": "A pin drops and bounces, then the place name and a detail line (date, state, mile marker) slide out beside it. For 'where we are now' moments in travel videos.",
 "duration": 4.5,
 "params": {"place": "Moab, Utah", "detail": "", "position": "top-left", "font": "heading", "body_font": "body",
            "size": 64, "detail_size": 36, "fill": "light", "detail_fill": "secondary", "pin": "accent", "panel": true, "margin": 0.07},
 "docs": {"position": "top-left | top-right | bottom-left | bottom-right", "detail": "small second line, e.g. 'Day 12 - 2,140 miles'",
          "panel": "true = a dark rounded panel behind the text"}}
@*/
M.block('location', (stage, p, c) => {
  const u = c.u, pos = p.position || 'top-left', right = pos.includes('right');
  const wrap = M.el('div', { style: { position: 'absolute', display: 'flex', flexDirection: right ? 'row-reverse' : 'row', alignItems: 'center', gap: `${14 * u}px` } }, stage);
  const m = c.h * p.margin;
  if (pos.includes('bottom')) wrap.style.bottom = `${m}px`; else wrap.style.top = `${m}px`;
  wrap.style[right ? 'right' : 'left'] = `${m}px`;
  const pinSize = (p.size + p.detail_size) * 1.05 * u;
  const pin = M.el('div', { html: `<svg viewBox="0 0 24 32" width="100%" height="100%"><path d="M12 1C6 1 1.5 5.6 1.5 11.5 1.5 19.5 12 31 12 31s10.5-11.5 10.5-19.5C22.5 5.6 18 1 12 1Z" fill="${c.color(p.pin)}" stroke="white" stroke-width="1.6"/><circle cx="12" cy="11.5" r="4.2" fill="white"/></svg>`,
    style: { width: `${pinSize * 0.75}px`, height: `${pinSize}px`, transformOrigin: '50% 100%', filter: `drop-shadow(0 ${4 * u}px ${6 * u}px rgba(0,0,0,0.5))` } }, wrap);
  const txt = M.el('div', { style: { display: 'flex', flexDirection: 'column', alignItems: right ? 'flex-end' : 'flex-start', padding: p.panel ? `${12 * u}px ${26 * u}px` : '0',
    borderRadius: `${14 * u}px`, background: p.panel ? 'rgba(12,14,16,0.78)' : 'transparent' } }, wrap);
  const shadow = p.panel ? 'none' : `0 ${3 * u}px ${12 * u}px rgba(0,0,0,0.75)`;
  const place = c.style(M.el('div', { text: p.place, style: { whiteSpace: 'nowrap', lineHeight: '1.1', textShadow: shadow } }, txt), p.font, p.size * u, p.fill);
  M.fit(place, p.size * u, c.w * 0.6);
  let det = null;
  if (p.detail) { det = c.style(M.el('div', { text: p.detail, style: { whiteSpace: 'nowrap', lineHeight: '1.2', textShadow: shadow } }, txt), p.body_font, p.detail_size * u, p.detail_fill); M.fit(det, p.detail_size * u, c.w * 0.6); }
  return (t) => {
    const out = M.prog(t, c.len - 0.45, 0.45, 'in');
    const drop = M.prog(t, 0, 0.7, 'bounceOut');
    M.set(pin, { o: Math.min(M.prog(t, 0, 0.1, 'linear'), 1 - out), y: -(1 - drop) * 140 * u, sy: 1 - 0.12 * Math.max(0, Math.sin(Math.min(1, t / 0.7) * Math.PI * 3)) * (1 - drop) });
    const open = M.prog(t, 0.45, 0.6, 'expoOut') * (1 - out);
    M.set(txt, { o: Math.min(M.prog(t, 0.45, 0.2, 'linear'), 1 - out), clip: right ? [0, 0, 0, 1 - open] : [0, 1 - open, 0, 0] });
    M.set(place, { x: (right ? 1 : -1) * (1 - M.prog(t, 0.5, 0.6, 'expoOut')) * 40 * u });
    if (det) M.set(det, { o: M.prog(t, 0.7, 0.3, 'linear'), x: (right ? 1 : -1) * (1 - M.prog(t, 0.7, 0.6, 'expoOut')) * 40 * u });
  };
});
