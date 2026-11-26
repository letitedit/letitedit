/* letitedit motion runtime: one continuous camera over one big world, with real pictures on it (T78, 4 Nov 2026).
 *
 * In a page, and in its hash, only when its script names M.world (bridge\motion.py), so no saved scene changes.
 * Written for letitedit (GPL-3.0-or-later). No third-party code.
 */
(function () {
  'use strict';
  const M = window.M;
  const clamp01 = (x) => Math.max(0, Math.min(1, x));
  const cr = (a, b, c, d, u) => 0.5 * (2 * b + (c - a) * u + (2 * a - 5 * b + 4 * c - d) * u * u + (3 * b - a - 3 * c + d) * u * u * u);

  M.world = {
    /** Real pictures, loaded before the first frame. Call it at the top of the script, outside M.block.
     *  urls: {name: 'file:///...'}. Returns {images: {name: Image}, done: false until all have answered}. A picture that
     *  can't load is a page error, which the fast look reports, and its name stays in `missing`. */
    pictures(urls) {
      const out = { images: {}, missing: [], done: false };
      const each = Object.keys(urls).map((name) => new Promise((resolve) => {
        const image = new Image();
        out.images[name] = image;
        image.onload = resolve;
        image.onerror = () => { out.missing.push(name); console.error('a picture did not load: ' + urls[name]); resolve(); };
        image.src = urls[name];
      }));
      window.__hf = window.__hf || {};
      window.__hf.buildReady = window.__hf.buildReady || {};
      window.__hf.buildReady['pictures' + Object.keys(window.__hf.buildReady).length] = Promise.all(each).then(() => { out.done = true; });
      return out;
    },

    /** A camera that never stops at a key: a smooth curve through keys [{t, x, y, z}] sorted by t, x and y the view's centre
     *  in world px, z the zoom, even in log space. Before the first and after the last key it holds. Returns {x, y, z}. */
    path(keys, t) {
      if (t <= keys[0].t) return { x: keys[0].x, y: keys[0].y, z: keys[0].z };
      const n = keys.length;
      if (t >= keys[n - 1].t) return { x: keys[n - 1].x, y: keys[n - 1].y, z: keys[n - 1].z };
      let i = 0;
      while (t > keys[i + 1].t) i++;
      const a = keys[Math.max(0, i - 1)], b = keys[i], c = keys[i + 1], d = keys[Math.min(n - 1, i + 2)];
      const u = (t - b.t) / (c.t - b.t);
      return { x: cr(a.x, b.x, c.x, d.x, u), y: cr(a.y, b.y, c.y, d.y, u),
        z: Math.exp(cr(Math.log(a.z), Math.log(b.z), Math.log(c.z), Math.log(d.z), u)) };
    },

    /** Where the view leaves the page. keys as for path; page {x0, y0, x1, y1} in world px; w and h the frame; pxPerWorld the
     *  frame's px per world px at zoom 1. Returns [{t, by}]: the times (every 1/fps s) a corner of the view is off the page, and
     *  by how many world px. Empty means the page always fills the frame. */
    offPage(keys, page, w, h, pxPerWorld = 1, fps = 30) {
      const out = [];
      const end = keys[keys.length - 1].t;
      for (let f = 0; f <= end * fps; f++) {
        const t = f / fps, cam = M.world.path(keys, t), hw = w / (2 * cam.z * pxPerWorld), hh = h / (2 * cam.z * pxPerWorld);
        const by = Math.max(page.x0 - (cam.x - hw), cam.x + hw - page.x1, page.y0 - (cam.y - hh), cam.y + hh - page.y1);
        if (by > 0) out.push({ t: Math.round(t * 100) / 100, by: Math.round(by) });
      }
      return out;
    },

    /** How far a thing has fallen back while another is the hero: 0 while it is the hero, 1 once it isn't, eased over `fade` s.
     *  heroes: [[from, to, id], ...] in order, covering the video. Draw with it however suits the thing. */
    back(heroes, id, t, fade = 0.33) {
      const i = heroes.findIndex((h) => t < h[1]);
      const at = i < 0 ? heroes.length - 1 : i;
      const now = heroes[at][2] === id ? 0 : 1, before = at > 0 ? (heroes[at - 1][2] === id ? 0 : 1) : now;
      const u = clamp01((t - heroes[at][0]) / fade), s = u * u * (3 - 2 * u);
      return before + (now - before) * s;
    },
  };
})();
