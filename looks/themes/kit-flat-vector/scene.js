const F = M.look.flatVector.start(c.w, c.h), C = F.palette, s = K(1);
const back = F.plate('back', (x) => { F.fill(x, FRAME, C.sky, {grain: {ang: -1.5, k: .2}}); F.fill(x, F.oval(SUN.x, SUN.y, SUN.r, SUN.r, 26), '#f6c863', {grain: {ang: 1, k: .3}});
  F.fill(x, HILL, C.far, {grain: {ang: .3, k: .4}}); F.fill(x, SEA, '#2f7f92', {grain: {ang: 1.4, k: .4}}); });
const boat = F.plate('boat', (x) => { F.longShadow(x, HULL, 170*s); F.fill(x, HULL, C.coral, {grain: {ang: 2.6, k: .5}}); F.fill(x, SAIL, '#f7efe0', {grain: {ang: 2.4, k: .3}}); F.fill(x, JIB, '#f2b872', {grain: {ang: 2.4, k: .3}}); F.fill(x, T([[562,300],[570,300],[570,700],[562,700]]), '#2c2b3a'); });
return (t) => { F.begin(g); g.fillStyle = '#f7efe0'; g.fillRect(0, 0, c.w, c.h); back.draw(g); const arrival = M.prog(t, .2, 3.4); boat.draw(g, {x: K(-100) * (1 - arrival), alpha: arrival}); F.finish(g); };
