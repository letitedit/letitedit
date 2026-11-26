// Builds motion\runtime\looks\<style>.js from the sources beside this file, with the esbuild in motion\engine\node_modules.
// A build step of ours, never run on a customer's PC: nothing at draw time needs Node, esbuild or the network.
// usage: node motion\runtime\looks-src\build.mjs
// Run it after changing a source: the output's text joins the hash of any scene that uses it, so a scene already saved on the
// old text draws again next time.
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(join(here, '..', '..', 'engine', 'package.json'));
const esbuild = require('esbuild');
const STYLES = ['flatVector', 'paperCraft', 'scrapbook', 'paintedOil', 'brokenColour', 'dreamGlaze', 'midCentury', 'sumiE', 'folkTale', 'risograph', 'halftone', 'woodcut', 'cutPaper', 'embroidery', 'markerComic', 'rubberHose', 'crayon', 'storybook', 'pixelArt', 'lowPoly', 'isometric', 'toyBrick', 'ballpoint', 'colouredPencil', 'pencilWatercolour', 'inkWash', 'stipple', 'singleLine', 'scratchboard', 'charcoal', 'chalkboard', 'blueprint'];
const wanted = process.argv.slice(2);
const root = join(here, '..', '..', '..');   // esbuild writes file paths into the output as comments: always relative to the repo, whatever folder this runs from, or a rebuild changes every scene's hash
const banner = (name) => `/* letitedit drawing hand: ${name}. Built from motion\\runtime\\looks-src (node build.mjs); don't edit this file.
 * Includes code from anidoodle (https://github.com/alexgreensh/anidoodle, commit 9c20e77), Copyright 2026 Alex Greenshpun, under the
 * Apache License 2.0: LICENSE-anidoodle.txt and NOTICE-anidoodle.txt beside this file. Changed by letitedit: see the headers in
 * looks-src. The rest is letitedit's own, GPL-3.0-or-later. Loaded into a code scene's page only when its script says M.look.${name}. */`;

for (const name of wanted.length ? wanted : STYLES) {
  const out = await esbuild.build({
    absWorkingDir: root, entryPoints: [join(here, `${name}.ts`)], outfile: join(here, '..', 'looks', `${name}.js`), bundle: true, format: 'iife',
    target: 'chrome100', charset: 'utf8', legalComments: 'none', treeShaking: true, banner: { js: banner(name) }, logLevel: 'warning', metafile: true,
  });
  const bytes = Object.values(out.metafile.outputs)[0].bytes;
  console.log(`${name}: ${(bytes / 1024).toFixed(1)} KB`);
}
