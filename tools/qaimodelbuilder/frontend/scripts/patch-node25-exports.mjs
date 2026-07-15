/**
 * Post-install patch for Node 25+ CJS strict-exports compatibility.
 *
 * Node 25 enforces package.json "exports" strictly for CJS require().
 * Several packages in our dependency tree have incomplete exports:
 *
 * - entities@4.5.0: missing "./decode" subpath
 * - estree-walker@3.0.3: missing "require" condition in "." export
 *
 * This script patches ALL physical copies in node_modules after install.
 * It's idempotent — safe to run multiple times.
 *
 * Why not just downgrade Node? Because:
 * - Node 24 LTS also has stricter exports than 22 (this future-proofs)
 * - The patches are minimal and well-understood
 * - When upstream packages fix their exports, this script becomes a no-op
 */

import { readFileSync, writeFileSync, readdirSync } from 'fs';
import { join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const nodeModules = join(__dirname, '..', 'node_modules');

let patchCount = 0;

function walkForPackage(dir, pkgName, patchFn) {
  try {
    const entries = readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      const full = join(dir, entry.name);
      if (entry.name === pkgName) {
        const pkgJson = join(full, 'package.json');
        try {
          const raw = readFileSync(pkgJson, 'utf8');
          const pkg = JSON.parse(raw);
          if (patchFn(pkg)) {
            writeFileSync(pkgJson, JSON.stringify(pkg, null, 2) + '\n');
            patchCount++;
          }
        } catch { /* skip */ }
      } else if (entry.name !== '.cache' && entry.name !== '.bin') {
        walkForPackage(full, pkgName, patchFn);
      }
    }
  } catch { /* skip permission errors */ }
}

// Patch 1: entities — add ./decode export
walkForPackage(nodeModules, 'entities', (pkg) => {
  if (pkg.exports && !pkg.exports['./decode']) {
    pkg.exports['./decode'] = {
      require: './lib/decode.js',
      import: './lib/esm/decode.js',
    };
    return true;
  }
  return false;
});

// Patch 2: estree-walker — add "require" condition
walkForPackage(nodeModules, 'estree-walker', (pkg) => {
  if (pkg.exports && pkg.exports['.'] && !pkg.exports['.'].require && pkg.exports['.'].import) {
    pkg.exports['.'].require = pkg.exports['.'].import;
    return true;
  }
  return false;
});

if (patchCount > 0) {
  console.log(`[patch-node25-exports] Patched ${patchCount} package(s) for Node 25+ compat.`);
} else {
  console.log(`[patch-node25-exports] All packages already compatible.`);
}
