/*@block
{"title":"3D flip card","about":"A lit, dimensional card turns to reveal the next idea. Transparent outside the card, with a real perspective flip and soft shadows.",
 "duration":2.4,
 "params":{"front":"THE PROBLEM","back":"THE FIX","eyebrow":"NEXT CHAPTER","font":"heading","body_font":"body","size":118,
           "fill":"light","accent":"accent","background":"dark","flip_at":0.95},
 "docs":{"front":"first face of the card","back":"second face","flip_at":"seconds at which the turn begins"}}
@*/
M.block('flip_card', (stage, p, c) => {
  const u = c.u, width = c.w * 0.82, height = Math.min(c.h * 0.38, c.w * 0.7);
  const frame = M.el('div', { style: { position: 'absolute', left: '50%', top: '50%', width: `${width}px`,
    height: `${height}px`, perspective: `${Math.max(c.w, c.h) * 1.5}px`, transform: 'translate(-50%, -50%)' } }, stage);
  const card = M.el('div', { style: { position: 'absolute', inset: '0', transformStyle: 'preserve-3d',
    borderRadius: `${30*u}px` } }, frame);
  const colors = [c.color(p.background), c.color(p.accent)];
  const face = (label, reverse, index) => {
    const pane = M.el('div', { style: { position: 'absolute', inset: '0', borderRadius: `${30*u}px`,
      boxSizing: 'border-box', padding: `${54*u}px`, display: 'flex', flexDirection: 'column',
      justifyContent: 'center', alignItems: 'flex-start', backfaceVisibility: 'visible',
      background: `linear-gradient(145deg, ${colors[index]} 0%, ${c.color('dark')} 100%)`,
      border: `${3*u}px solid rgba(255,255,255,.24)`,
      boxShadow: `0 ${24*u}px ${75*u}px rgba(0,0,0,.42), inset 0 ${2*u}px ${5*u}px rgba(255,255,255,.25)` } }, card);
    M.el('div', { style: { width: `${90*u}px`, height: `${8*u}px`, background: c.color(p.accent),
      borderRadius: `${4*u}px`, marginBottom: `${24*u}px`, boxShadow: `0 0 ${24*u}px ${c.color(p.accent)}` } }, pane);
    c.style(M.el('div', { text: p.eyebrow, style: { letterSpacing: `${4*u}px`, opacity: '.82', marginBottom: `${12*u}px` } }, pane),
      p.body_font, 35*u, 'light');
    const title = c.style(M.el('div', { text: label, style: { lineHeight: '1.04', maxWidth: '100%',
      overflowWrap: 'break-word', textShadow: `0 ${6*u}px ${18*u}px rgba(0,0,0,.35)` } }, pane), p.font, p.size*u, p.fill);
    M.fit(title, p.size*u, width - 110*u, height - 130*u, 20*u);
    return pane;
  };
  const frontPane = face(p.front, false, 0);
  const backPane = face(p.back, true, 1);
  return (t) => {
    const enter = M.prog(t, 0, 0.42, 'backOut');
    const turn = M.prog(t, p.flip_at, 0.75, 'backOut');
    const leave = 1 - M.prog(t, c.len - 0.35, 0.35, 'in');
    // Chromium's screenshot path does not consistently honour backface-visibility.
    // Switch the visible face at edge-on so the old words cannot show mirrored.
    frontPane.style.visibility = turn < .5 ? 'visible' : 'hidden';
    backPane.style.visibility = turn < .5 ? 'hidden' : 'visible';
    frame.style.opacity = String(Math.min(M.prog(t,0,.2,'linear'),leave));
    card.style.transform = `translateY(${((1-enter)*95*u).toFixed(1)}px) scale(${(.88+.12*enter).toFixed(4)})`;
    frontPane.style.transform = `rotateY(${(-180*turn).toFixed(2)}deg) translateZ(${8*u}px)`;
    backPane.style.transform = `rotateY(${(180*(1-turn)).toFixed(2)}deg) translateZ(${8*u}px)`;
    card.style.filter = `blur(${Math.max(0, (Math.sin(Math.PI*turn)**6)*3*u).toFixed(2)}px)`;
  };
});
