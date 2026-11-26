/*@block
{"title": "End card", "about": "The closing screen: a thank-you line, the channel name or handle, a call to action, and optional video slots for a YouTube end screen.",
 "duration": 12.0,
 "params": {"title": "Thanks for watching", "handle": "", "cta": "Watch next", "slots": 0, "font": "heading",
            "body_font": "body", "size": 96, "fill": "light", "accent": "accent", "slot_outline": "light",
            "background": "none"},
 "docs": {"slots": "0-2 empty video frames (16:9, about 0.3 of the width, YouTube's end-screen element size) on the right half",
          "background": "none (transparent, over the last shot) | dim (darkens the picture) | a colour name or #rrggbb",
          "handle": "e.g. '@yourchannel'"}}
@*/
M.block('end_card', (stage, p, c) => {
  const u = c.u;
  let bg = null;
  if (p.background && p.background !== 'none') {
    bg = M.el('div', { style: { position: 'absolute', inset: '0', background: p.background === 'dim' ? 'rgba(0,0,0,0.55)' : c.color(p.background) } }, stage);
  }
  const portrait = c.portrait;
  const left = M.el('div', { style: { position: 'absolute', left: `${c.w * 0.07}px`, top: portrait ? (p.slots ? `${c.h * 0.14}px` : '42%') : '50%',
    width: portrait ? `${c.w * 0.86}px` : `${c.w * 0.4}px`, display: 'flex', flexDirection: 'column', gap: `${18 * u}px`,
    transform: portrait && p.slots ? 'none' : 'translateY(-50%)' } }, stage);
  const shadow = `0 ${4 * u}px ${18 * u}px rgba(0,0,0,0.6)`;
  const title = c.style(M.el('div', { text: p.title, style: { lineHeight: '1.05', textShadow: shadow, textWrap: 'balance' } }, left), p.font, p.size * u, p.fill);
  M.fit(title, p.size * u, portrait ? c.w * 0.86 : c.w * 0.4, c.h * 0.4);
  const tw = M.split(title, 'words');
  const rule = M.el('div', { style: { height: `${8 * u}px`, width: `${160 * u}px`, background: c.color(p.accent), borderRadius: `${4 * u}px`, transformOrigin: 'left center' } }, left);
  let handle = null, cta = null;
  if (p.handle) handle = c.style(M.el('div', { text: p.handle, style: { textShadow: shadow } }, left), p.body_font, 48 * u, 'secondary');
  if (p.cta) cta = c.style(M.el('div', { text: p.cta + '  →', style: { textShadow: shadow, letterSpacing: `${2 * u}px`, textTransform: 'uppercase' } }, left), p.body_font, 34 * u, p.accent);
  const slots = [];
  const n = Math.max(0, Math.min(2, p.slots | 0));
  const sw = portrait ? c.w * 0.78 : c.w * 0.3, sh = sw * 9 / 16;
  for (let i = 0; i < n; i++) {
    const s = M.el('div', { style: { position: 'absolute', width: `${sw}px`, height: `${sh}px`, border: `${4 * u}px solid ${c.color(p.slot_outline)}`,
      borderRadius: `${14 * u}px`, boxShadow: `0 0 0 ${2 * u}px rgba(0,0,0,0.35)` } }, stage);
    if (portrait) { s.style.left = `${(c.w - sw) / 2}px`; s.style.top = `${c.h * 0.46 + i * (sh + 40 * u)}px`; }
    else { s.style.left = `${c.w * 0.6}px`; s.style.top = `${c.h / 2 + (i - n / 2) * (sh + 40 * u) + 20 * u}px`; }
    slots.push(s);
  }
  return (t) => {
    const out = M.prog(t, c.len - 0.5, 0.5, 'in');
    if (bg) M.set(bg, { o: Math.min(M.prog(t, 0, 0.6, 'out'), 1 - out) });
    tw.forEach((w, i) => M.set(w, { o: Math.min(M.prog(t, 0.1 + i * 0.07, 0.3, 'linear'), 1 - out), y: (1 - M.prog(t, 0.1 + i * 0.07, 0.6, 'expoOut')) * 50 * u }));
    M.set(rule, { sx: M.prog(t, 0.45, 0.6, 'expoOut') * (1 - out) });
    if (handle) M.set(handle, { o: Math.min(M.prog(t, 0.6, 0.4, 'linear'), 1 - out), x: (1 - M.prog(t, 0.6, 0.6, 'expoOut')) * -30 * u });
    if (cta) M.set(cta, { o: Math.min(M.prog(t, 0.8, 0.4, 'linear'), 1 - out), x: (1 - M.prog(t, 0.8, 0.6, 'expoOut')) * -30 * u });
    slots.forEach((s, i) => M.set(s, { o: Math.min(M.prog(t, 0.5 + i * 0.15, 0.4, 'linear'), 1 - out), s: 0.9 + 0.1 * M.prog(t, 0.5 + i * 0.15, 0.6, 'backOut') }));
  };
});
