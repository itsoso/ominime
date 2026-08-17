import { defineConfig } from 'tsdown'

const packageName = '@ominime/dsh-personal-context'

export default defineConfig([
  {
    name: packageName,
    entry: { index: 'src/index.ts' },
    outDir: 'lib',
    format: 'esm',
    platform: 'node',
    target: 'es2024',
    fixedExtension: false,
    clean: true,
    dts: false,
    deps: {
      neverBundle: ['@deepseek-ai/cordis', '@deepseek-ai/dsh-tools'],
    },
  },
  {
    name: `${packageName}/probe-wechat`,
    entry: { 'probe-wechat': 'src/connectors/wechat/cli.ts' },
    outDir: 'lib',
    format: 'esm',
    platform: 'node',
    target: 'es2024',
    fixedExtension: false,
    clean: false,
    dts: false,
  },
  {
    name: `${packageName}/probe-kim`,
    entry: { 'probe-kim': 'src/connectors/kim/cli.ts' },
    outDir: 'lib',
    format: 'esm',
    platform: 'node',
    target: 'es2024',
    fixedExtension: false,
    clean: false,
    dts: false,
  },
  {
    name: `${packageName}/client`,
    entry: { client: 'src/client/index.tsx' },
    outDir: 'lib',
    format: 'cjs',
    platform: 'browser',
    target: 'es2022',
    fixedExtension: false,
    clean: false,
    dts: false,
    sourcemap: true,
    deps: {
      neverBundle: [
        '@deepseek-ai/cordis',
        '@deepseek-ai/dsh-client-ui-slots',
        'react',
        'react/jsx-runtime',
      ],
    },
    outputOptions: {
      entryFileNames: 'client.js',
      banner: `window.__ModuleLoader__.load({ id: ${JSON.stringify(packageName)}, factory: (require) => {`,
      footer: 'return module.exports; } });',
      intro: 'var module = { exports: {} }; var exports = module.exports;',
    },
  },
])
