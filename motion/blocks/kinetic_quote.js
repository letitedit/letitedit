/*@block
{"title": "Kinetic quote", "about": "A line of speech or a quote set in big type, word by word in time with the voice: each word pops in when it is said, chosen words land bigger in the accent colour. Give word times from letitedit_words to sync it, or let it pace itself.",
 "duration": 5.0,
 "params": {"offset": 0, "text": "This is the line people will remember", "words": [], "emphasis": [], "font": "heading", "size": 110,
            "fill": "light", "emphasis_fill": "accent", "emphasis_scale": 1.25, "position": "center", "align": "center",
            "style": "pop", "pace": 0.28, "max_width": 0.82, "attribution": "", "attribution_font": "body", "case": "as_written"},
 "docs": {"words": "[{text, start, end}] (or letitedit's own {w, s, e}) in seconds; Empty = one word every `pace` s", "offset": "seconds subtracted from every word time: the source time where this motion clip starts",
          "emphasis": "words to stress, matched without case or punctuation, e.g. ['never', '$12']",
          "style": "pop (scale up with overshoot) | slam (drop in from above) | fade (soft fade up) | type (appear instantly)",
          "position": "center | top | bottom", "case": "as_written | upper", "attribution": "small line under the quote, e.g. '- Alex'"}}
@*/
M.block('kinetic_quote', (stage, p, c) => {
  const u = c.u;
  const norm = (s) => String(s).toLowerCase().replace(/[^\p{L}\p{N}$%]+/gu, '');
  const stress = new Set((p.emphasis || []).map(norm));
  let words = (p.words && p.words.length) ? p.words.map((w) => ({ text: String(w.text ?? w.word ?? w.w).trim(), start: +(w.start ?? w.s) - p.offset, end: +(w.end ?? w.e ?? w.start ?? w.s) - p.offset }))
    : String(p.text).split(/\s+/).filter(Boolean).map((w, i) => ({ text: w, start: 0.2 + i * p.pace, end: 0.2 + (i + 1) * p.pace }));
  if (p.case === 'upper') words.forEach((w) => { w.text = w.text.toUpperCase(); });
  const box = M.el('div', { style: { position: 'absolute', left: `${c.w * (1 - p.max_width) / 2}px`, width: `${c.w * p.max_width}px`,
    textAlign: p.align, lineHeight: '1.12', textWrap: 'balance' } }, stage);
  if (p.position === 'top') box.style.top = `${c.h * 0.1}px`;
  else if (p.position === 'bottom') box.style.bottom = `${c.h * 0.16}px`;
  else { box.style.top = '50%'; box.style.transform = 'translateY(-50%)'; }
  c.style(box, p.font, p.size * u, p.fill);
  box.style.textShadow = `0 ${4 * u}px ${20 * u}px rgba(0,0,0,0.6)`;
  const spans = words.map((w, i) => {
    const s = M.el('span', { text: w.text, style: { display: 'inline-block', transformOrigin: '50% 70%' } }, box);
    if (i < words.length - 1) box.appendChild(document.createTextNode(' '));
    if (stress.has(norm(w.text))) {
      s.style.color = c.color(p.emphasis_fill);
      s.style.fontSize = `${p.emphasis_scale * 100}%`;
    }
    return s;
  });
  M.fit(box, p.size * u, c.w * p.max_width, c.h * 0.72, 24);
  let attr = null;
  if (p.attribution) {
    attr = c.style(M.el('div', { text: p.attribution, style: { marginTop: `${24 * u}px`, fontSize: `${Math.max(30, p.size * 0.38) * u}px`, lineHeight: '1.2' } }, box),
      p.attribution_font, null, 'secondary');
  }
  const last = words.length ? words[words.length - 1].end : 0;
  return (t) => {
    const out = M.prog(t, c.len - 0.4, 0.4, 'in');
    spans.forEach((s, i) => {
      const st = words[i].start;
      const o = Math.min(p.style === 'type' ? (t >= st ? 1 : 0) : M.prog(t, st, 0.12, 'linear'), 1 - out);
      if (p.style === 'slam') M.set(s, { o, y: -(1 - M.prog(t, st, 0.22, 'bounceOut')) * 90 * u });
      else if (p.style === 'fade') M.set(s, { o: Math.min(M.prog(t, st, 0.35, 'out'), 1 - out), y: (1 - M.prog(t, st, 0.35, 'out')) * 16 * u });
      else if (p.style === 'type') M.set(s, { o });
      else M.set(s, { o, s: 0.55 + 0.45 * M.prog(t, st, 0.3, 'backOut') });
    });
    if (attr) M.set(attr, { o: Math.min(M.prog(t, last + 0.2, 0.4, 'linear'), 1 - out) });
  };
});
