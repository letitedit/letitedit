/*@block
{"title": "Word captions", "about": "Animated captions from word times: short groups of words, the word being said lights up in the accent colour and gently scales. For Shorts and Reels style captions. Feed it letitedit_words output for the clip's range.",
 "duration": 6.0,
 "params": {"words": [], "offset": 0, "text": "", "pace": 0.32, "max_words": 4, "max_chars": 22, "font": "captions", "size": 78,
            "fill": "light", "active_fill": "accent", "outline": "dark", "outline_width": 7, "position": "bottom",
            "margin_y": 0.2, "case": "upper", "active_scale": 1.08, "box": false},
 "docs": {"words": "[{text, start, end}] (or letitedit's own {w, s, e}) in seconds", "offset": "seconds subtracted from every word time: the source time where this motion clip starts",
          "text": "without word times: this text, one word every `pace` s",
          "position": "bottom | center | top", "margin_y": "distance from the edge (bottom/top) as a share of the height; Shorts UI covers about the bottom 0.2",
          "max_words": "most words on screen at once (a group also ends at a pause over 0.6 s or at punctuation)",
          "box": "true = a dark rounded box behind each group", "case": "upper | as_spoken"}}
@*/
M.block('word_captions', (stage, p, c) => {
  const u = c.u;
  let words = (p.words && p.words.length) ? p.words.map((w) => ({ text: String(w.text ?? w.word ?? w.w).trim(), start: +(w.start ?? w.s) - p.offset, end: +(w.end ?? w.e ?? w.start ?? w.s) - p.offset }))
    : String(p.text || '').split(/\s+/).filter(Boolean).map((w, i) => ({ text: w, start: 0.1 + i * p.pace, end: 0.1 + (i + 1) * p.pace }));
  words = words.filter((w) => w.text);
  if (p.case === 'upper') words.forEach((w) => { w.text = w.text.toUpperCase(); });
  // groups: up to max_words / max_chars, broken at pauses and sentence ends
  const groups = [];
  let g = [];
  words.forEach((w, i) => {
    const chars = g.reduce((n, x) => n + x.text.length + 1, 0) + w.text.length;
    if (g.length && (g.length >= p.max_words || chars > p.max_chars || w.start - g[g.length - 1].end > 0.6)) { groups.push(g); g = []; }
    g.push(w);
    if (/[.!?]$/.test(w.text)) { groups.push(g); g = []; }
  });
  if (g.length) groups.push(g);
  const ow = p.outline_width * u;
  const stroke = c.color(p.outline);
  const els = groups.map((grp) => {
    const line = M.el('div', { style: { position: 'absolute', left: '50%', textAlign: 'center', whiteSpace: 'nowrap',
      lineHeight: '1.15', padding: p.box ? `${10 * u}px ${24 * u}px` : '0', borderRadius: `${16 * u}px`,
      background: p.box ? c.color('dark').slice(0, 7) + 'CC' : 'transparent' } }, stage);
    c.style(line, p.font, p.size * u, p.fill);
    if (!p.box) { line.style.setProperty('-webkit-text-stroke', `${ow}px ${stroke}`); line.style.setProperty('paint-order', 'stroke fill'); }
    line.style.textShadow = `0 ${4 * u}px ${10 * u}px rgba(0,0,0,0.5)`;
    if (p.position === 'top') line.style.top = `${c.h * p.margin_y}px`;
    else if (p.position === 'center') line.style.top = `${c.h * 0.5}px`;
    else line.style.bottom = `${c.h * p.margin_y}px`;
    const spans = grp.map((w, i) => {
      return M.el('span', { text: w.text, style: { display: 'inline-block', transformOrigin: '50% 60%', margin: '0 0.14em' } }, line);
    });
    M.fit(line, p.size * u, c.w * 0.9);
    return { line, spans, grp, start: grp[0].start, end: grp[grp.length - 1].end };
  });
  const fill = c.color(p.fill), active = c.color(p.active_fill);
  return (t) => {
    els.forEach((e, gi) => {
      const next = els[gi + 1];
      const until = next ? Math.min(next.start, e.end + 0.8) : Math.min(c.len, e.end + 0.8);
      const on = t >= e.start - 0.04 && t < until;
      const k = M.prog(t, e.start - 0.04, 0.16, 'backOut');
      const y = p.position === 'center' ? '-50%' : '0';
      e.line.style.opacity = on ? '1' : '0';
      e.line.style.transform = `translate(-50%, ${y}) scale(${(0.85 + 0.15 * k).toFixed(4)})`;
      e.spans.forEach((s, i) => {
        const w = e.grp[i];
        const lit = t >= w.start && t < (e.grp[i + 1] ? e.grp[i + 1].start : until);
        s.style.color = lit ? active : fill;
        M.set(s, { s: lit ? 1 + (p.active_scale - 1) * M.prog(t, w.start, 0.12, 'out') : 1 });
      });
    });
  };
});
