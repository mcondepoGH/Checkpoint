import js from '@eslint/js';
import globals from 'globals';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import jsxA11y from 'eslint-plugin-jsx-a11y';
import prettier from 'eslint-config-prettier';

export default [
  { ignores: ['dist/', 'node_modules/', 'coverage/'] },
  js.configs.recommended,
  {
    files: ['src/**/*.{js,jsx}'],
    plugins: { react, 'react-hooks': reactHooks },
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: { ...globals.browser },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    settings: { react: { version: '18.3' } },
    rules: {
      'react/jsx-uses-vars': 'error',
      'react/jsx-uses-react': 'error',
      'react/jsx-key': 'error',
      'react/jsx-no-duplicate-props': 'error',
      'react/jsx-no-undef': 'error',
      'react/no-children-prop': 'error',
      'react/no-danger-with-children': 'error',
      'react/no-direct-mutation-state': 'error',
      'react/no-unescaped-entities': 'error',
      'react/jsx-no-target-blank': 'error',
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
    },
  },
  {
    files: ['src/**/*.{js,jsx}'],
    ...jsxA11y.flatConfigs.recommended,
    languageOptions: { globals: { ...globals.browser }, parserOptions: { ecmaFeatures: { jsx: true } } },
    rules: {
      ...jsxA11y.flatConfigs.recommended.rules,
      // Zonas con scroll enfocables (WCAG 2.1.1): solo role=region con nombre, además de tabpanel.
      'jsx-a11y/no-noninteractive-tabindex': ['error', { tags: [], roles: ['tabpanel', 'region'], allowExpressionValues: true }],
      // El texto de la etiqueta puede estar anidado a 3 niveles (label > span > b > texto).
      'jsx-a11y/label-has-associated-control': ['error', { depth: 3 }],
    },
  },
  { files: ['public/sw.js'], languageOptions: { globals: { ...globals.serviceworker } } },
  {
    files: ['test/**/*.mjs', 'scripts/**/*.mjs', 'vite.config.js'],
    languageOptions: { ecmaVersion: 'latest', sourceType: 'module', globals: { ...globals.node } },
  },
  prettier,
];
