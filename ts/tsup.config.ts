import { defineConfig } from 'tsup';

export default defineConfig({
  entry: [
    'src/index.ts',
    'src/component/index.ts',
    'src/component/vanilla.ts',
  ],
  format: ['esm', 'cjs'],
  dts: true,
  clean: true,
  sourcemap: true,
  treeshake: true,
  // The easing table is read from `an`'s contract at build time and inlined,
  // so the published package carries no runtime JSON import.
  noExternal: ['@thorwhalen/an-contract'],
});
