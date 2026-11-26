/*@block
{"title": "Bar chart", "about": "A simple bar chart that grows bar by bar with values counting up: costs compared, before/after, time per step. Up to 8 bars, horizontal by default (labels read better).",
 "duration": 6.0,
 "params": {"title": "", "bars": [{"label": "Before", "value": 40}, {"label": "After", "value": 85}], "unit": "",
            "prefix": "", "decimals": 0, "max": null, "highlight": -1, "orientation": "horizontal", "font": "heading",
            "body_font": "body", "fill": "light", "bar": "secondary", "highlight_bar": "accent", "panel": true},
 "docs": {"bars": "[{label, value}] in order", "highlight": "index of the bar to colour with the accent (-1 = the largest)",
          "max": "axis maximum (null = the largest value)", "orientation": "horizontal | vertical",
          "unit": "after each value, e.g. ' h' or '%'", "prefix": "before each value, e.g. '$'"}}
@*/
M.block('bar_chart', (stage, p, c) => {
  const u = c.u;
  const bars = (p.bars || []).slice(0, 8);
  const maxV = p.max || Math.max(...bars.map((b) => +b.value), 1);
  const hi = p.highlight >= 0 ? p.highlight : bars.reduce((bi, b, i, a) => (+b.value > +a[bi].value ? i : bi), 0);
  const W = c.portrait ? c.w * 0.88 : c.w * 0.62, H = c.portrait ? c.h * 0.5 : c.h * 0.66;
  const panel = M.el('div', { style: { position: 'absolute', left: `${(c.w - W) / 2}px`, top: `${(c.h - H) / 2}px`, width: `${W}px`, height: `${H}px`,
    padding: `${40 * u}px ${48 * u}px`, borderRadius: `${24 * u}px`, display: 'flex', flexDirection: 'column', gap: `${24 * u}px`,
    background: p.panel ? 'rgba(12,14,16,0.82)' : 'transparent' } }, stage);
  const shadow = p.panel ? 'none' : `0 ${3 * u}px ${12 * u}px rgba(0,0,0,0.7)`;
  let title = null;
  if (p.title) { title = c.style(M.el('div', { text: p.title, style: { textShadow: shadow } }, panel), p.font, 60 * u, p.fill); M.fit(title, 60 * u, W - 96 * u); }
  const area = M.el('div', { style: { flex: '1', display: 'flex', flexDirection: p.orientation === 'vertical' ? 'row' : 'column',
    justifyContent: 'space-around', alignItems: 'stretch', gap: `${18 * u}px` } }, panel);
  const rows = bars.map((b, i) => {
    const vert = p.orientation === 'vertical';
    const row = M.el('div', { style: { flex: '1', display: 'flex', flexDirection: vert ? 'column-reverse' : 'row', alignItems: vert ? 'center' : 'center', gap: `${16 * u}px`, minWidth: '0', minHeight: '0' } }, area);
    const lab = c.style(M.el('div', { text: b.label, style: { whiteSpace: 'nowrap', textShadow: shadow, width: vert ? 'auto' : `${W * 0.24}px`, textAlign: vert ? 'center' : 'right', overflow: 'hidden', textOverflow: 'ellipsis' } }, row), p.body_font, 38 * u, p.fill);
    const track = M.el('div', { style: { flex: '1', position: 'relative', display: 'flex', flexDirection: vert ? 'column-reverse' : 'row', alignItems: vert ? 'stretch' : 'center', width: vert ? '60%' : 'auto', height: vert ? 'auto' : '70%' } }, row);
    const bar = M.el('div', { style: { background: c.color(i === hi ? p.highlight_bar : p.bar), borderRadius: `${8 * u}px`,
      transformOrigin: vert ? 'bottom center' : 'left center', [vert ? 'height' : 'width']: `${(+b.value / maxV) * 82}%`, [vert ? 'width' : 'height']: '100%' } }, track);
    const val = c.style(M.el('div', { style: { whiteSpace: 'nowrap', padding: vert ? `0 0 ${8 * u}px` : `0 ${14 * u}px`, fontVariantNumeric: 'tabular-nums', textShadow: shadow, textAlign: 'center' } }, track), p.font, 40 * u, p.fill);
    return { bar, val, value: +b.value, vert, lab };
  });
  return (t) => {
    const out = M.prog(t, c.len - 0.5, 0.5, 'in');
    M.set(panel, { o: Math.min(M.prog(t, 0, 0.35, 'linear'), 1 - out), s: 0.96 + 0.04 * M.prog(t, 0, 0.5, 'out') });
    if (title) M.set(title, { o: M.prog(t, 0.15, 0.4, 'linear') });
    rows.forEach((r, i) => {
      const st = 0.45 + i * 0.22;
      const k = M.prog(t, st, 0.9, 'expoOut');
      M.set(r.bar, r.vert ? { sy: k } : { sx: k });
      r.val.textContent = M.num(r.value * k, p.decimals, ',', p.prefix, p.unit);
      M.set(r.val, { o: M.prog(t, st, 0.3, 'linear') });
      M.set(r.lab, { o: M.prog(t, st - 0.15, 0.3, 'linear') });
    });
  };
});
