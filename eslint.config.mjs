/**
 * ESLint flat config for every JavaScript workspace.
 *
 * The backend has had ruff and strict mypy in CI since the first commit; the TypeScript side
 * had neither. This closes that asymmetry with one config at the root rather than three that
 * drift apart.
 *
 * Type-aware linting is deliberately not enabled: `tsc --noEmit` already runs per workspace
 * in CI and catches type errors, so paying the project-graph cost again here would slow the
 * pipeline down for rules we mostly already have.
 */

import js from '@eslint/js';
import prettier from 'eslint-config-prettier';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    // Build output, dependencies, and generated code. `api.d.ts` is written by
    // `npm run generate:api` — linting it would mean fixing the generator's style.
    ignores: [
      '**/node_modules/**',
      '**/dist/**',
      '**/build/**',
      '**/coverage/**',
      '**/.expo/**',
      // Python services: virtualenvs vendor JavaScript that is not ours to lint.
      '**/.venv/**',
      'services/**',
      'packages/shared-types/src/generated/**',
    ],
  },

  js.configs.recommended,
  ...tseslint.configs.recommended,

  {
    files: ['**/*.{ts,tsx,js,jsx,mjs}'],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: 'module',
      globals: { ...globals.es2021, ...globals.browser, ...globals.node },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { react, 'react-hooks': reactHooks },
    settings: { react: { version: 'detect' } },
    rules: {
      ...react.configs.flat.recommended.rules,
      ...reactHooks.configs.recommended.rules,

      // The automatic JSX runtime (React 19) makes the import unnecessary.
      'react/react-in-jsx-scope': 'off',
      // Prop types are expressed in TypeScript, not the runtime `propTypes` object.
      'react/prop-types': 'off',

      // A stale dependency array is a real bug — a screen that silently stops updating —
      // so this is an error rather than the plugin's default warning.
      'react-hooks/exhaustive-deps': 'error',

      // `_`-prefixed names are the established convention here for deliberate non-use.
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrors: 'none' },
      ],
      // Floating promises are the top source of silently swallowed async failures; the
      // codebase already marks intentional ones with `void`.
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      eqeqeq: ['error', 'smart'],
    },
  },

  {
    // Test files use their runner's injected globals (jest / vitest) and legitimately
    // reach for `any` when building fixtures and mocks.
    files: [
      '**/__tests__/**/*.{ts,tsx}',
      '**/*.{test,spec}.{ts,tsx}',
      '**/test-support/**/*.{ts,tsx}',
      '**/jest.setup.js',
      '**/vitest.setup.ts',
    ],
    languageOptions: { globals: { ...globals.jest, ...globals.node } },
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-require-imports': 'off',
      'no-console': 'off',
    },
  },

  {
    // Config files run in Node before any bundler sees them.
    files: ['**/*.config.{js,mjs,ts}', '**/babel.config.js'],
    languageOptions: { globals: globals.node },
    rules: { '@typescript-eslint/no-require-imports': 'off' },
  },

  // Must stay last: switches off every rule that would fight the formatter.
  prettier,
);
