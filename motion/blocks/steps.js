/*@block
{"title": "Steps", "about": "A short checklist of steps (a repair, a recipe, a how-to): the steps appear one by one, the finished ones get a tick, the current one is highlighted. Use one clip per step change, or one clip that ticks through them with `tick_times`.",
 "duration": 5.0,
 "params": {"title": "", "steps": ["Remove the cover", "Swap the motor", "Test it"], "current": 1, "tick_times": [],
            "position": "left", "font": "heading", "body_font": "body", "size": 54, "fill": "light", "done_fill": "secondary",
            "accent": "accent", "panel": true},
 "docs": {"current": "1-based index of the step in progress (earlier steps show ticked); 0 = none yet",
          "tick_times": "seconds at which the current step and the following ones get ticked, e.g. [2.0, 3.5]",
          "position": "left | right | center"}}
@*/
M.block('steps', (stage, p, c) => {
  const u = c.u;
  const steps = (p.steps || []).slice(0, 8);
  const panel = M.el('div', { style: { position: 'absolute', top: '50%', display: 'flex', flexDirection: 'column', gap: `${18 * u}px`,
    padding: `${32 * u}px ${40 * u}px`, borderRadius: `${22 * u}px`, background: p.panel ? 'rgba(12,14,16,0.82)' : 'transparent', maxWidth: `${c.w * (c.portrait ? 0.9 : 0.46)}px` } }, stage);
  if (p.position === 'right') { panel.style.right = `${c.w * 0.05}px`; panel.style.transform = 'translateY(-50%)'; }
  else if (p.position === 'center') { panel.style.left = '50%'; panel.style.transform = 'translate(-50%, -50%)'; }
  else { panel.style.left = `${c.w * 0.05}px`; panel.style.transform = 'translateY(-50%)'; }
  const baseTf = panel.style.transform;
  let title = null;
  if (p.title) title = c.style(M.el('div', { text: p.title, style: { marginBottom: `${6 * u}px` } }, panel), p.font, p.size * 1.25 * u, p.accent);
  const accent = c.color(p.accent);
  const rows = steps.map((s, i) => {
    const row = M.el('div', { style: { display: 'flex', alignItems: 'center', gap: `${20 * u}px` } }, panel);
    const box = M.el('div', { style: { flex: '0 0 auto', width: `${p.size * 1.15 * u}px`, height: `${p.size * 1.15 * u}px`, borderRadius: '50%',
      border: `${4 * u}px solid ${c.color(p.fill)}`, display: 'grid', placeItems: 'center', position: 'relative' } }, row);
    const num = c.style(M.el('span', { text: String(i + 1), style: { gridArea: '1/1' } }, box), p.body_font, p.size * 0.6 * u, p.fill);
    const tick = M.el('div', { html: '<svg viewBox="0 0 24 24" width="100%" height="100%"><path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="white" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" pathLength="1" stroke-dasharray="1 1"/></svg>',
      style: { gridArea: '1/1', width: '72%', height: '72%' } }, box);
    const label = c.style(M.el('div', { text: s, style: { lineHeight: '1.15' } }, row), p.body_font, p.size * u, p.fill);
    return { row, box, num, tick, path: tick.querySelector('path'), label };
  });
  const cur = p.current | 0;
  const tickAt = (i) => {
    if (i < cur - 1) return -1;                                    // done before the clip
    const k = i - (cur - 1);
    return p.tick_times && k < p.tick_times.length ? +p.tick_times[k] : Infinity;
  };
  return (t) => {
    const out = M.prog(t, c.len - 0.45, 0.45, 'in');
    M.set(panel, { o: Math.min(M.prog(t, 0, 0.3, 'linear'), 1 - out) });
    panel.style.transform = baseTf + ` translateX(${((1 - M.prog(t, 0, 0.5, 'expoOut')) * (p.position === 'right' ? 60 : -60) * u).toFixed(1)}px)`;
    if (title) M.set(title, { o: M.prog(t, 0.1, 0.3, 'linear') });
    let active = -1;
    rows.forEach((r, i) => {
      const at = tickAt(i);
      const done = t >= at;
      if (!done && active < 0 && (i >= cur - 1)) active = i;
      const show = M.prog(t, 0.2 + i * 0.12, 0.35, 'expoOut');
      M.set(r.row, { o: show, x: (1 - show) * -30 * u });
      const dk = at < 0 ? 1 : M.prog(t, at, 0.35, 'out');
      r.box.style.background = done ? accent : 'transparent';
      r.box.style.borderColor = done ? accent : (i === active ? accent : c.color(p.fill));
      r.num.style.opacity = done ? '0' : '1';
      r.path.setAttribute('stroke-dashoffset', String(done ? 1 - dk : 1));
      r.label.style.color = done ? c.color(p.done_fill) : c.color(p.fill);
      r.label.style.textDecoration = 'none';
      M.set(r.box, { s: i === active ? 1 + 0.06 * Math.sin(t * 5) : 1 });
    });
  };
});
