/*@block
{"title": "Route map", "about": "An illustrated route between supplied stops, drawn progressively with a moving marker. Stops are positions in a graphic, not GPS claims or map tiles; use letitedit_map for a geographic map.",
 "duration": 4.0,
 "params": {"title": "The route", "stops": [{"name": "Start", "x": 0.15, "y": 0.72}, {"name": "Stop", "x": 0.48, "y": 0.30}, {"name": "Finish", "x": 0.83, "y": 0.65}],
            "font": "heading", "body_font": "body", "size": 58, "label_size": 34, "fill": "light", "muted": "secondary", "line": "accent", "panel": "dark"},
 "docs": {"stops": "2-8 {name, x, y} positions within the illustrated panel (shares 0-1); label the real stops in order", "title": "short title above the route"}}
@*/
M.block('route_map', (stage, p, c) => {
  const u = c.u, stops = (p.stops || []).slice(0, 8);
  const panel = M.el('div', {style: {position: 'absolute', left: '6%', top: '26%', width: '88%', height: '48%',
    borderRadius: `${28 * u}px`, background: c.color(p.panel), boxShadow: `0 ${15 * u}px ${42 * u}px rgba(0,0,0,.4)`,
    overflow: 'hidden'}}, stage);
  const title = c.style(M.el('div', {text: p.title, style: {position: 'absolute', left: `${34 * u}px`, top: `${20 * u}px`}}, panel),
    p.font, p.size * u, p.fill);
  M.fit(title, p.size * u, c.w * 0.72);
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 1000 520');
  Object.assign(svg.style, {position: 'absolute', left: '0', top: `${60 * u}px`, width: '100%', height: `calc(100% - ${65 * u}px)`});
  panel.appendChild(svg);
  const mk = (tag, attrs) => { const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, String(v))); svg.appendChild(el); return el; };
  const pts = stops.map(s => [Math.max(80, Math.min(920, s.x * 1000)), Math.max(80, Math.min(440, s.y * 520))]);
  let path = null, marker = null, length = 1;
  if (pts.length > 1) {
    const d = `M ${pts[0][0]} ${pts[0][1]} ` + pts.slice(1).map(q => `L ${q[0]} ${q[1]}`).join(' ');
    mk('path', {d, fill: 'none', stroke: c.color(p.muted), 'stroke-width': 8, opacity: .28,
      'stroke-linecap': 'round', 'stroke-linejoin': 'round'});
    path = mk('path', {d, fill: 'none', stroke: c.color(p.line), 'stroke-width': 10,
      'stroke-linecap': 'round', 'stroke-linejoin': 'round'});
    length = path.getTotalLength();
    path.setAttribute('stroke-dasharray', `${length} ${length}`);
    marker = mk('circle', {cx: pts[0][0], cy: pts[0][1], r: 13, fill: c.color(p.line), stroke: '#ffffff', 'stroke-width': 5});
  }
  const labels = stops.map((s, i) => {
    const q = pts[i], anchor = q[0] > 680 ? 'end' : 'start';
    mk('circle', {cx: q[0], cy: q[1], r: 19, fill: c.color(p.panel), stroke: c.color(p.line), 'stroke-width': 6});
    const label = mk('text', {x: q[0] + (anchor === 'end' ? -30 : 30), y: q[1] - 27,
      fill: c.color(p.fill), 'font-size': p.label_size * 2.1, 'font-weight': 700,
      'font-family': 'Inter, sans-serif', 'text-anchor': anchor});
    label.textContent = s.name;
    return label;
  });
  return (t) => {
    const draw = M.prog(t, .35, Math.max(.3, c.len - 1.2), 'inOut');
    M.set(panel, {o: Math.min(M.prog(t, 0, .35, 'out'), 1 - M.prog(t, c.len - .35, .35, 'in'))});
    if (path) {
      path.setAttribute('stroke-dashoffset', String(length * (1 - draw)));
      const q = path.getPointAtLength(Math.max(0, length * draw));
      marker.setAttribute('cx', String(q.x)); marker.setAttribute('cy', String(q.y));
      marker.style.opacity = String(draw > .01 ? 1 : 0);
    }
    labels.forEach((label, i) => { label.style.opacity = String(M.prog(t, .35 + i * (c.len - 1.2) / Math.max(1, stops.length - 1), .25, 'out')); });
  };
});
