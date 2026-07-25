/**
 * Runtime configuration.
 *
 * `VITE_API_BASE_URL` lets each deploy point at its own API; the default targets a local
 * backend so `npm run dev` works with no setup.
 */

const DEFAULT_API_BASE_URL = 'http://localhost:8000/api/v1';

export const config = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL,
} as const;
