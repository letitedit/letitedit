/*@block
{"title": "Subscribe nudge", "about": "A small follow/subscribe button that slides in, gets 'clicked' by a pointer, turns into the done state with a bell ring, then slides away. Text is yours, so it works for any platform.",
 "duration": 4.5,
 "params": {"text": "Subscribe", "done_text": "Subscribed", "handle": "", "bell": true, "position": "bottom-left",
            "font": "body", "size": 46, "button": "accent", "done_button": "#3A3A3A", "fill": "#FFFFFF", "margin": 0.07},
 "docs": {"position": "bottom-left | bottom-right | top-left | top-right | center", "button": "button colour (kit name or #rrggbb)",
          "handle": "optional name shown beside the button, e.g. 'Your Channel'"}}
@*/
M.block('subscribe', (stage, p, c) => {
  const u = c.u;
  const pos = p.position || 'bottom-left';
  const wrap = M.el('div', { style: { position: 'absolute', display: 'flex', alignItems: 'center', gap: `${18 * u}px`,
    padding: `${14 * u}px`, borderRadius: `${60 * u}px`, background: 'rgba(15,15,15,0.72)' } }, stage);
  const m = c.h * p.margin;
  if (pos === 'center') { wrap.style.left = '50%'; wrap.style.top = '50%'; }
  else {
    if (pos.includes('bottom')) wrap.style.bottom = `${m}px`; else wrap.style.top = `${m}px`;
    if (pos.includes('right')) wrap.style.right = `${m}px`; else wrap.style.left = `${m}px`;
  }
  let handle = null;
  if (p.handle) handle = c.style(M.el('div', { text: p.handle, style: { whiteSpace: 'nowrap', paddingLeft: `${14 * u}px` } }, wrap), p.font, p.size * 0.8 * u, 'light');
  const btn = M.el('div', { style: { position: 'relative', borderRadius: `${50 * u}px`, padding: `${14 * u}px ${34 * u}px`, whiteSpace: 'nowrap', display: 'grid' } }, wrap);
  c.style(btn, p.font, p.size * u, p.fill);
  btn.style.fontWeight = '800';
  const a = M.el('span', { text: p.text, style: { gridArea: '1/1' } }, btn);
  const b = M.el('span', { text: p.done_text, style: { gridArea: '1/1' } }, btn);
  let bell = null;
  if (p.bell) {
    bell = M.el('div', { html: '<svg viewBox="0 0 24 24" width="100%" height="100%"><path fill="currentColor" d="M12 22a2.5 2.5 0 0 0 2.45-2h-4.9A2.5 2.5 0 0 0 12 22Zm7-6V11a7 7 0 0 0-5.5-6.84V3.5a1.5 1.5 0 0 0-3 0v.66A7 7 0 0 0 5 11v5l-2 2v1h18v-1Z"/></svg>',
      style: { width: `${p.size * 1.1 * u}px`, height: `${p.size * 1.1 * u}px`, color: c.color('light'), transformOrigin: '50% 10%', marginRight: `${10 * u}px` } }, wrap);
  }
  const cursor = M.el('div', { html: '<svg viewBox="0 0 24 24" width="100%" height="100%"><path d="M4 2l15 9.5-6.6 1.3 3.9 7.4-2.7 1.4-3.9-7.4L4 19Z" fill="white" stroke="black" stroke-width="1.3" stroke-linejoin="round"/></svg>',
    style: { position: 'absolute', width: `${54 * u}px`, height: `${54 * u}px`, left: '0', top: '0' } }, stage);
  // too wide for the frame (a phone-shaped video): shrink the whole nudge to fit inside the margins
  const fitS = Math.min(1, (c.w - 2 * m) / Math.max(1, wrap.offsetWidth));
  wrap.style.transformOrigin = pos === 'center' ? 'center' : `${pos.includes('right') ? 'right' : 'left'} ${pos.includes('bottom') ? 'bottom' : 'top'}`;
  const btnColor = c.color(p.button), doneColor = c.color(p.done_button);
  const clickAt = 1.25;
  const dir = pos.includes('right') ? 1 : -1;
  return (t) => {
    const out = M.prog(t, c.len - 0.5, 0.5, 'in');
    const ink = M.prog(t, 0, 0.5, 'backOut');
    const slide = (1 - ink + out) * 260 * u * dir;
    wrap.style.transform = (pos === 'center' ? 'translate(-50%, -50%) ' : '') + `translateX(${slide.toFixed(1)}px) scale(${fitS.toFixed(4)})`;
    M.set(wrap, { o: Math.min(M.prog(t, 0, 0.2, 'linear'), 1 - out) });
    const done = t >= clickAt;
    const press = t >= clickAt - 0.08 && t < clickAt + 0.12 ? 0.92 : 1;
    btn.style.background = done ? doneColor : btnColor;
    btn.style.transform = `scale(${press})`;
    a.style.opacity = done ? '0' : '1';
    b.style.opacity = done ? '1' : '0';
    if (bell) {
      const ring = t > clickAt + 0.15 ? Math.sin((t - clickAt - 0.15) * 28) * 22 * Math.exp(-(t - clickAt - 0.15) * 3.2) : 0;
      M.set(bell, { r: ring });
    }
    // the pointer glides to the button, clicks, and leaves
    const r = btn.getBoundingClientRect();
    const tx = r.left + r.width * 0.55, ty = r.top + r.height * 0.6;
    const k = M.prog(t, 0.45, 0.75, 'inOut');
    const leave = M.prog(t, clickAt + 0.35, 0.5, 'in');
    const cx = M.lerp(tx + 220 * u * -dir, tx, k) + leave * 160 * u, cy = M.lerp(ty + 160 * u, ty, k) + leave * 120 * u;
    cursor.style.transform = `translate(${cx.toFixed(1)}px, ${cy.toFixed(1)}px) scale(${press})`;
    cursor.style.opacity = String(Math.min(M.prog(t, 0.4, 0.2, 'linear'), 1 - leave));
  };
});
