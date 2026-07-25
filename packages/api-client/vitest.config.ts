import { defineConfig } from 'vitest/config';

export default defineConfig({
  // The transport layer is pure TypeScript over an injected `fetch`, so it needs no DOM and
  // no native runtime — plain Node is the fastest honest environment for it.
  test: { environment: 'node' },
});
