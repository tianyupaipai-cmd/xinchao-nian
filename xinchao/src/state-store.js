import { mkdir, open, readFile, rename, rm } from 'node:fs/promises';
import { dirname } from 'node:path';

export class StateStore {
  #queue = Promise.resolve();

  constructor(path, factory) {
    this.path = path;
    this.factory = factory;
  }

  async read() {
    try {
      return JSON.parse(await readFile(this.path, 'utf8'));
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
      const state = this.factory();
      await this.write(state);
      return state;
    }
  }

  async write(state) {
    await mkdir(dirname(this.path), { recursive: true });
    const temp = `${this.path}.${process.pid}.${Date.now()}.tmp`;
    const handle = await open(temp, 'wx', 0o600);
    try {
      await handle.writeFile(`${JSON.stringify(state, null, 2)}\n`, 'utf8');
      await handle.sync();
    } finally {
      await handle.close();
    }
    try {
      await rename(temp, this.path);
    } catch (error) {
      if (process.platform !== 'win32') throw error;
      await rm(this.path, { force: true });
      await rename(temp, this.path);
    }
  }

  update(mutator) {
    const operation = this.#queue.then(async () => {
      const current = await this.read();
      const next = await mutator(structuredClone(current));
      await this.write(next);
      return next;
    });
    this.#queue = operation.catch(() => {});
    return operation;
  }
}
