import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import {
  PINNED_DSH_COMMIT,
  PINNED_DSH_VERSION,
  verifyPinnedCheckout,
  withFreshPinnedBuild,
} from './isolation.mjs'

const scriptDir = dirname(fileURLToPath(import.meta.url))
const pluginRoot = resolve(scriptDir, '..')

function declaration(dshSource, relativePath) {
  return join(dshSource, relativePath)
}

function compilerOptions(dshSource) {
  return {
    target: 'ES2024',
    module: 'NodeNext',
    moduleResolution: 'NodeNext',
    strict: true,
    noEmit: true,
    skipLibCheck: true,
    paths: {
      '@deepseek-ai/cordis': [declaration(dshSource, 'vendor/cordis/lib/types/index.d.ts')],
      '@deepseek-ai/dsh-tools': [declaration(dshSource, 'packages/core/tools/lib/types/index.d.ts')],
      '@deepseek-ai/dsh-client-ui-conversation/client': [
        declaration(dshSource, 'packages/client/ui-conversation/lib/types/client/index.d.ts'),
      ],
    },
  }
}

export function typecheckPinned({
  dshSource,
  runner = execFileSync,
  temporaryParent = tmpdir(),
} = {}) {
  if (dshSource === undefined) throw new Error('typecheckPinned requires a fresh built DSH source')
  verifyPinnedCheckout(dshSource, { runner })
  const tsc = join(pluginRoot, 'node_modules/typescript/bin/tsc')
  const temporaryRoot = mkdtempSync(join(resolve(temporaryParent), 'ominime-dsh-typecheck-'))
  try {
    const shared = compilerOptions(dshSource)
    const projects = [
      {
        name: 'host',
        config: {
          compilerOptions: shared,
          files: [join(pluginRoot, 'src/index.ts')],
        },
      },
      {
        name: 'client',
        config: {
          compilerOptions: {
            ...shared,
            jsx: 'react-jsx',
            lib: ['ES2024', 'DOM', 'DOM.Iterable'],
            types: ['react'],
            typeRoots: [join(pluginRoot, 'node_modules/@types')],
          },
          files: [join(pluginRoot, 'src/client/index.tsx')],
        },
      },
    ]
    for (const project of projects) {
      const configPath = join(temporaryRoot, `tsconfig.${project.name}.json`)
      writeFileSync(configPath, `${JSON.stringify(project.config, null, 2)}\n`)
      runner(process.execPath, [tsc, '--project', configPath], {
        cwd: pluginRoot,
        encoding: 'utf8',
        stdio: 'inherit',
      })
    }
    const result = {
      status: 'ok',
      dshVersion: PINNED_DSH_VERSION,
      dshCommit: PINNED_DSH_COMMIT,
      projects: ['host', 'client'],
    }
    process.stdout.write(`${JSON.stringify(result)}\n`)
    return result
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true })
  }
}

const invokedPath = process.argv[1] === undefined ? undefined : pathToFileURL(resolve(process.argv[1])).href
if (invokedPath === import.meta.url) {
  await withFreshPinnedBuild(({ dshSource }) => typecheckPinned({ dshSource }))
}
