import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

const webEleRoot = existsSync(resolve(process.cwd(), 'src/views/agentmesh'))
  ? process.cwd()
  : resolve(process.cwd(), 'apps/web-ele');

const productionSources = [
  resolve(webEleRoot, 'src/views/agentmesh/workspace/index.vue'),
  resolve(webEleRoot, 'src/views/agentmesh/tasks/index.vue'),
  resolve(webEleRoot, 'src/api/agentmesh/client.ts'),
];

const knownCorruptText = ['Worker ???????????????', '???????', '<b>????</b>'];

describe('p25 user-visible text encoding', () => {
  for (const sourcePath of productionSources) {
    const source = readFileSync(sourcePath, 'utf8');

    it(`contains no Unicode replacement character in ${sourcePath}`, () => {
      expect(source).not.toContain('\uFFFD');
    });

    it(`contains none of the known corrupt P25 strings in ${sourcePath}`, () => {
      for (const corruptText of knownCorruptText) {
        expect(source).not.toContain(corruptText);
      }
    });
  }
});
