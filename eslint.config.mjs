// Correctness rules only (eslint:recommended); no style rules. The scope is the FLUX studio front end.
import js from '@eslint/js';
import globals from 'globals';

export default [
  // Local runtimes and untracked review output are not project source.
  {ignores: ['**/.venv*/**', 'flux-studio/comparison-review/**', 'flux-studio/gpu-cpu-measurement-*/**', 'flux-studio/pipeline-audit/**']},
  js.configs.recommended,
  {
    files: ['flux-studio/**/*.{js,mjs}'],
    languageOptions: {ecmaVersion: 'latest', sourceType: 'module', globals: {...globals.browser}},
    rules: {
      // An empty catch is how optional browser storage is skipped.
      'no-empty': ['error', {allowEmptyCatch: true}],
    },
  },
  // Tests and the benchmark helper run under Node.
  {files: ['flux-studio/test-*.mjs', 'flux-studio/benchmark_metrics.mjs'], languageOptions: {globals: {...globals.node}}},
];
