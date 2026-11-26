/*@block
{"title": "Count-up", "about": "A number that counts from one value to another (cost, distance, days, views) with a label, then holds so it can be read. Prefix and suffix for units and money.",
 "duration": 4.0,
 "params": {"from": 0, "to": 1000, "decimals": 0, "prefix": "", "suffix": "", "separator": ",", "label": "",
            "count_time": 1.6, "ease": "expoOut", "font": "heading", "label_font": "body", "size": 220, "label_size": 56,
            "fill": "light", "label_fill": "secondary", "accent": "accent", "position": "center", "panel": false},
 "docs": {"count_time": "seconds the count takes (starts at 0.25 s)", "ease": "expoOut (fast then settles) | out | inOut | linear",
          "position": "center | left | right | top | bottom | [x,y] fractions", "panel": "true = a dark rounded panel behind it",
          "prefix": "e.g. '$'", "suffix": "e.g. ' mi' or '%'"}}
@*/
M.block('count_up', (stage, p, c) => {
  const u = c.u;
  const box = M.el('div', { style: { position: 'absolute', display: 'flex', flexDirection: 'column', alignItems: 'center',
    gap: `${4 * u}px`, padding: p.panel ? `${30 * u}px ${56 * u}px` : '0', borderRadius: `${24 * u}px`,
    background: p.panel ? c.color('dark').slice(0, 7) + 'D0' : 'transparent' } }, stage);
  const pos = Array.isArray(p.position) && p.position.length === 2 ? p.position :
    ({ center: [0.5, 0.5], left: [0.25, 0.5], right: [0.75, 0.5], top: [0.5, 0.25], bottom: [0.5, 0.72] }[p.position] || [0.5, 0.5]);
  box.style.left = `${c.w * pos[0]}px`;
  box.style.top = `${c.h * pos[1]}px`;
  const shadow = `0 ${5 * u}px ${22 * u}px rgba(0,0,0,0.6)`;
  const num = c.style(M.el('div', { style: { fontVariantNumeric: 'tabular-nums', lineHeight: '1', textShadow: shadow, whiteSpace: 'nowrap' } }, box), p.font, p.size * u, p.fill);
  // size for the widest text the count will show, so it never jumps
  num.textContent = M.num(Math.max(Math.abs(p.from), Math.abs(p.to)) * (p.to < 0 || p.from < 0 ? -1 : 1), p.decimals, p.separator, p.prefix, p.suffix);
  M.fit(num, p.size * u, c.w * 0.8);
  num.style.minWidth = `${num.scrollWidth}px`;
  num.style.textAlign = 'center';
  const bar = M.el('div', { style: { height: `${8 * u}px`, width: '100%', background: c.color(p.accent), borderRadius: `${4 * u}px`, transformOrigin: 'left center' } }, box);
  let label = null;
  if (p.label) label = c.style(M.el('div', { text: p.label, style: { textShadow: shadow, whiteSpace: 'nowrap', marginTop: `${8 * u}px` } }, box), p.label_font, p.label_size * u, p.label_fill);
  return (t) => {
    const out = M.prog(t, c.len - 0.4, 0.4, 'in');
    const k = M.prog(t, 0.25, p.count_time, p.ease);
    num.textContent = M.num(M.lerp(p.from, p.to, k), p.decimals, p.separator, p.prefix, p.suffix);
    const inK = M.prog(t, 0, 0.4, 'backOut');
    box.style.transform = `translate(-50%, -50%) scale(${(0.8 + 0.2 * inK).toFixed(4)})`;
    M.set(box, { o: Math.min(M.prog(t, 0, 0.25, 'linear'), 1 - out) });
    M.set(bar, { sx: k });
    if (label) M.set(label, { o: M.prog(t, 0.4, 0.4, 'linear'), y: (1 - M.prog(t, 0.4, 0.5, 'expoOut')) * 20 * u });
  };
});
