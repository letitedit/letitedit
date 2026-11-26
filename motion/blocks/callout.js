/*@block
{"title": "Callout", "about": "Points at something in the shot: a ring pulses at a point, a line draws out to a label. Point and label are shares of the frame (0-1), so measure the point on a frame first. For a moving object use letitedit_annotate (it tracks); this one is for a fixed spot.",
 "duration": 4.0,
 "params": {"text": "The broken part", "at": [0.5, 0.5], "label_at": null, "ring": true, "ring_size": 70,
            "font": "heading", "size": 54, "fill": "dark", "panel": "light", "line": "light", "accent": "accent"},
 "docs": {"at": "[x, y] the point, shares of the frame", "label_at": "[x, y] where the label sits; null = up and to the side, away from the nearest edge",
          "ring_size": "ring diameter in px at 1080p", "fill": "label text colour", "panel": "label background colour"}}
@*/
M.block('callout', (stage, p, c) => {
  const u = c.u;
  const ax = p.at[0] * c.w, ay = p.at[1] * c.h;
  let lx, ly;
  if (p.label_at) { lx = p.label_at[0] * c.w; ly = p.label_at[1] * c.h; }
  else {
    lx = ax + (p.at[0] > 0.6 ? -1 : 1) * 260 * u;
    ly = ay + (p.at[1] > 0.35 ? -1 : 1) * 170 * u;
  }
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('width', c.w); svg.setAttribute('height', c.h);
  Object.assign(svg.style, { position: 'absolute', left: '0', top: '0', overflow: 'visible' });
  stage.appendChild(svg);
  const mk = (tag, attrs) => { const e = document.createElementNS('http://www.w3.org/2000/svg', tag); for (const k in attrs) e.setAttribute(k, attrs[k]); svg.appendChild(e); return e; };
  const lineColor = c.color(p.line), accent = c.color(p.accent);
  const shadowLine = mk('line', { x1: ax, y1: ay, x2: lx, y2: ly, stroke: 'rgba(0,0,0,0.45)', 'stroke-width': 9 * u, 'stroke-linecap': 'round' });
  const line = mk('line', { x1: ax, y1: ay, x2: lx, y2: ly, stroke: lineColor, 'stroke-width': 5 * u, 'stroke-linecap': 'round' });
  const L = Math.hypot(lx - ax, ly - ay);
  [line, shadowLine].forEach((e) => { e.setAttribute('stroke-dasharray', `${L} ${L}`); });
  const r = p.ring_size * u / 2;
  const ring = p.ring ? mk('circle', { cx: ax, cy: ay, r, fill: 'none', stroke: accent, 'stroke-width': 7 * u }) : null;
  const pulse = p.ring ? mk('circle', { cx: ax, cy: ay, r, fill: 'none', stroke: accent, 'stroke-width': 4 * u }) : null;
  const dot = mk('circle', { cx: ax, cy: ay, r: 9 * u, fill: accent, stroke: 'white', 'stroke-width': 3 * u });
  const label = c.style(M.el('div', { text: p.text, style: { position: 'absolute', whiteSpace: 'nowrap', padding: `${12 * u}px ${24 * u}px`,
    borderRadius: `${12 * u}px`, background: c.color(p.panel), boxShadow: `0 ${6 * u}px ${20 * u}px rgba(0,0,0,0.4)`, borderLeft: `${8 * u}px solid ${accent}` } }, stage), p.font, p.size * u, p.fill);
  M.fit(label, p.size * u, c.w * 0.45);
  const lw = label.offsetWidth, lh = label.offsetHeight;
  let left = lx < ax ? lx - lw : lx, top = ly - lh / 2;
  left = M.clamp(left, c.w * 0.03, c.w * 0.97 - lw); top = M.clamp(top, c.h * 0.03, c.h * 0.97 - lh);
  label.style.left = `${left}px`; label.style.top = `${top}px`;
  label.style.transformOrigin = lx < ax ? 'right center' : 'left center';
  return (t) => {
    const out = M.prog(t, c.len - 0.4, 0.4, 'in');
    const ringK = M.prog(t, 0, 0.45, 'backOut');
    if (ring) { ring.setAttribute('r', Math.max(0.1, r * ringK)); ring.style.opacity = String(1 - out); }
    if (pulse) {
      const ph = ((Math.max(0, t - 0.4)) % 1.2) / 1.2;
      pulse.setAttribute('r', r * (1 + ph * 0.8)); pulse.style.opacity = String((t > 0.4 ? (1 - ph) * 0.8 : 0) * (1 - out));
    }
    dot.style.opacity = String(Math.min(M.prog(t, 0, 0.2, 'linear'), 1 - out));
    const d = M.prog(t, 0.25, 0.45, 'inOut');
    [line, shadowLine].forEach((e) => { e.setAttribute('stroke-dashoffset', String(L * (1 - d))); e.style.opacity = String(1 - out); });
    M.set(label, { o: Math.min(M.prog(t, 0.6, 0.2, 'linear'), 1 - out), s: 0.7 + 0.3 * M.prog(t, 0.6, 0.4, 'backOut') });
  };
});
