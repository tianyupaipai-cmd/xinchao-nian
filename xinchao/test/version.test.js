import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { SYSTEM_VERSION } from '../src/version.js';

test('package and runtime versions stay aligned', async () => {
  const packageJson = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'));
  assert.equal(packageJson.version, SYSTEM_VERSION);
});
