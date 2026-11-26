/*@block
{"title": "Lower third", "about": "A name and role (or place and date) on a panel with an accent bar: the bar drops in, the panel wipes open, the text slides in, then it all closes.",
 "duration": 5.0,
 "params": {"name": "Name", "role": "", "side": "left", "font": "heading", "role_font": "body", "size": 62,
            "role_size": 38, "fill": "light", "role_fill": "secondary", "panel": "dark", "panel_opacity": 0.85,
            "accent": "accent", "margin_x": 0.06, "margin_y": 0.2, "radius": 10},
 "docs": {"side": "left | right", "margin_y": "distance from the bottom edge as a share of the height (0.2 sits above two lines of captions)",
          "panel_opacity": "0-1; 0 = no panel, text over the picture with a shadow"}}
@*/
M.block('lower_third', (stage, p, c) => {
  const u = c.u, right = p.side === 'right';
  const wrap = M.el('div', { style: { position: 'absolute', bottom: `${c.h * p.margin_y}px`, display: 'flex',
    flexDirection: right ? 'row-reverse' : 'row', alignItems: 'stretch' } }, stage);
  wrap.style[right ? 'right' : 'left'] = `${c.w * p.margin_x}px`;
  const bar = M.el('div', { style: { width: `${12 * u}px`, background: c.color(p.accent), borderRadius: `${3 * u}px`, transformOrigin: 'bottom' } }, wrap);
  const alpha = Math.round(M.clamp(p.panel_opacity) * 255).toString(16).padStart(2, '0');
  const panel = M.el('div', { style: { background: c.color(p.panel).slice(0, 7) + alpha, padding: `${20 * u}px ${34 * u}px`,
    borderRadius: right ? `${p.radius * u}px 0 0 ${p.radius * u}px` : `0 ${p.radius * u}px ${p.radius * u}px 0`,
    display: 'flex', flexDirection: 'column', gap: `${6 * u}px`, alignItems: right ? 'flex-end' : 'flex-start' } }, wrap);
  const shadow = p.panel_opacity < 0.3 ? `0 ${3 * u}px ${12 * u}px rgba(0,0,0,0.7)` : 'none';
  const name = c.style(M.el('div', { text: p.name, style: { whiteSpace: 'nowrap', lineHeight: '1.1', textShadow: shadow } }, panel), p.font, p.size * u, p.fill);
  M.fit(name, p.size * u, c.w * 0.7);
  let role = null;
  if (p.role) {
    role = c.style(M.el('div', { text: p.role, style: { whiteSpace: 'nowrap', lineHeight: '1.1', textShadow: shadow } }, panel), p.role_font, p.role_size * u, p.role_fill);
    M.fit(role, p.role_size * u, c.w * 0.7);
  }
  const dir = right ? 1 : -1;
  return (t) => {
    const out = M.prog(t, c.len - 0.5, 0.5, 'inOut');
    M.set(bar, { sy: M.prog(t, 0, 0.35, 'expoOut') * (1 - M.prog(t, c.len - 0.2, 0.2, 'in')) });
    const open = M.prog(t, 0.15, 0.55, 'expoOut') * (1 - out);
    M.set(panel, { clip: right ? [0, 0, 0, 1 - open] : [0, 1 - open, 0, 0] });
    const k = M.prog(t, 0.3, 0.5, 'expoOut');
    M.set(name, { o: Math.min(M.prog(t, 0.3, 0.25, 'linear'), 1 - out), x: dir * (1 - k) * 40 * u });
    if (role) {
      const k2 = M.prog(t, 0.42, 0.5, 'expoOut');
      M.set(role, { o: Math.min(M.prog(t, 0.42, 0.25, 'linear'), 1 - out), x: dir * (1 - k2) * 40 * u });
    }
  };
});
