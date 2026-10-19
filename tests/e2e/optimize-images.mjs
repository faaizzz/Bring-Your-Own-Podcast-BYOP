// Shrinks the PNGs `make screenshots` just took (palette quantisation, like pngquant): the
// pictures are flat UI, so they stay sharp at a fraction of the size. Usage: node optimize-images.mjs <dir>
import { readdir, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import sharp from 'sharp';

const dir = process.argv[2];
if (!dir) throw new Error('usage: node optimize-images.mjs <dir>');

for (const name of (await readdir(dir)).filter((file) => file.endsWith('.png')).sort()) {
  const path = join(dir, name);
  const before = await readFile(path);
  const after = await sharp(before)
    .png({ palette: true, quality: 85, effort: 10, colours: 256 })
    .toBuffer();
  if (after.length < before.length) await writeFile(path, after);
  const kept = Math.min(after.length, before.length);
  console.log(`${name}: ${Math.round(before.length / 1024)} kB -> ${Math.round(kept / 1024)} kB`);
}
