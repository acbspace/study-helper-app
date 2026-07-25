/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Jest setup: mock the native modules the app depends on.
 *
 * expo-sqlite is mocked with a small in-memory implementation rather than a stub, so tests
 * exercise the real persistence code paths (insert, append, read back) instead of asserting
 * against a fake.
 */

jest.mock('expo-crypto', () => {
  let counter = 0;
  return {
    randomUUID: () => {
      counter += 1;
      return `00000000-0000-4000-8000-${counter.toString().padStart(12, '0')}`;
    },
  };
});

jest.mock('expo-secure-store', () => {
  const store = new Map();
  return {
    getItemAsync: jest.fn(async (key) => store.get(key) ?? null),
    setItemAsync: jest.fn(async (key, value) => {
      store.set(key, value);
    }),
    deleteItemAsync: jest.fn(async (key) => {
      store.delete(key);
    }),
  };
});

jest.mock('expo-keep-awake', () => ({
  useKeepAwake: jest.fn(),
  activateKeepAwakeAsync: jest.fn(),
  deactivateKeepAwake: jest.fn(),
}));

jest.mock('expo-constants', () => ({
  __esModule: true,
  default: { expoConfig: { extra: { apiBaseUrl: 'http://localhost:8000/api/v1' } } },
}));

// In-memory SQLite double. Supports the exact SQL shapes the app issues.
jest.mock('expo-sqlite', () => {
  const { createMockDatabase } = require('./src/test-support/mockSqlite');
  return {
    openDatabaseAsync: jest.fn(async () => createMockDatabase()),
  };
});

jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), back: jest.fn() }),
  useSegments: () => [],
  Redirect: () => null,
  Stack: Object.assign(() => null, { Screen: () => null }),
  Tabs: Object.assign(() => null, { Screen: () => null }),
}));
