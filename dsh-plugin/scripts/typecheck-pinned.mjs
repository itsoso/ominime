import { execFileSync } from 'node:child_process'
import { lstatSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, extname, join, relative, resolve, sep } from 'node:path'
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
    allowImportingTsExtensions: true,
    paths: {
      '@deepseek-ai/cordis': [declaration(dshSource, 'vendor/cordis/lib/types/index.d.ts')],
      '@deepseek-ai/dsh-tools': [declaration(dshSource, 'packages/core/tools/lib/types/index.d.ts')],
      '@deepseek-ai/dsh-client-ui-conversation/client': [
        declaration(dshSource, 'packages/client/ui-conversation/lib/types/client/index.d.ts'),
      ],
    },
  }
}

const SUPPORTED_TYPESCRIPT_EXTENSIONS = new Set(['.ts', '.tsx', '.mts', '.cts'])
const TYPESCRIPT_LIKE_EXTENSION = /\.[cm]?tsx?$/i

export class TypecheckSourceTreeError extends Error {
  constructor(reason) {
    const message = reason === 'ROOT_MISSING'
      ? 'typecheck source root is missing'
      : reason === 'ROOT_NOT_DIRECTORY'
        ? 'typecheck source root must be an ordinary directory'
        : 'typecheck source root is unavailable'
    super(message)
    this.name = 'TypecheckSourceTreeError'
    Object.defineProperties(this, {
      code: { enumerable: true, value: 'TYPECHECK_SOURCE_TREE_INVALID' },
      metadata: { enumerable: true, value: Object.freeze({ reason }) },
    })
  }
}

function assertOrdinarySourceRoot(sourceRoot) {
  let stats
  try {
    stats = lstatSync(sourceRoot, { throwIfNoEntry: false })
  } catch {
    throw new TypecheckSourceTreeError('ROOT_UNAVAILABLE')
  }
  if (stats === undefined) throw new TypecheckSourceTreeError('ROOT_MISSING')
  if (stats.isSymbolicLink() || !stats.isDirectory()) {
    throw new TypecheckSourceTreeError('ROOT_NOT_DIRECTORY')
  }
}

function collectFiles(directory) {
  const files = []
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const candidate = join(directory, entry.name)
    if (entry.isSymbolicLink()) {
      throw new Error('typecheck source tree must not contain symbolic links')
    }
    if (entry.isDirectory()) {
      files.push(...collectFiles(candidate))
      continue
    }
    if (!entry.isFile()) continue
    const extension = extname(entry.name)
    if (SUPPORTED_TYPESCRIPT_EXTENSIONS.has(extension)) {
      files.push(candidate)
    } else if (TYPESCRIPT_LIKE_EXTENSION.test(entry.name)) {
      // Reject likely future TS variants rather than silently omitting production code.
      throw new Error('typecheck source tree contains an unsupported TypeScript-like extension')
    }
  }
  return files.sort()
}

export function collectTypecheckFiles(root = pluginRoot) {
  const sourceRoot = join(resolve(root), 'src')
  assertOrdinarySourceRoot(sourceRoot)
  const files = collectFiles(sourceRoot)
  const isClientFile = file => relative(sourceRoot, file).startsWith(`client${sep}`)
  return {
    host: files.filter(file => !isClientFile(file)),
    client: files.filter(isClientFile),
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
    const files = collectTypecheckFiles()
    const projects = [
      {
        name: 'host',
        config: {
          compilerOptions: {
            ...shared,
            types: ['node'],
            typeRoots: [join(pluginRoot, 'node_modules/@types')],
          },
          files: files.host,
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
          files: files.client,
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
