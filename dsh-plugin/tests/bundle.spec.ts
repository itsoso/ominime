import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, relative, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { describe, expect, it } from 'vitest'

const root = resolve(import.meta.dirname, '..')

describe('DSH bundle contract', () => {
  it('declares one installable bundle and one web client entry', () => {
    const manifest = JSON.parse(readFileSync(resolve(root, 'package.json'), 'utf8'))
    expect(manifest.dsh.bundle.patch).toBe('./cordis.patch.yml')
    expect(manifest.dsh.client.platform).toBe('web')
    expect(manifest.version).not.toMatch(/[x*]/)
    expect(manifest.scripts.pretest).toBe('pnpm run build')
    expect(manifest.scripts['typecheck:pinned']).toBe('node scripts/typecheck-pinned.mjs')
    expect(manifest.scripts['smoke:pinned']).toBe('node scripts/smoke-install.mjs')
    expect(manifest.scripts['check:node']).toBe('node scripts/check-node.mjs')
    expect(manifest.scripts['test:g1']).toBe('pnpm run check:node && pnpm test && node scripts/g1-pinned.mjs')
    expect(manifest.packageManager).toBe('pnpm@11.7.0')
  })

  it('pins the verified DSH compatibility baseline', () => {
    const text = readFileSync(resolve(root, 'DSH_COMPATIBILITY.md'), 'utf8')
    expect(text).toContain('0.1.0-rc.5')
    expect(text).toContain('47f943859bef60e4160492346772ded9b24f765a')
  })

  it('builds the Host and browser artifacts at the exported paths', () => {
    expect(existsSync(resolve(root, 'lib/index.js'))).toBe(true)
    expect(existsSync(resolve(root, 'lib/client.js'))).toBe(true)
  })

  it('ignores generated dependency and build trees', () => {
    expect(readFileSync(resolve(root, '.gitignore'), 'utf8')).toBe('/node_modules/\n/lib/\n')
  })

  it('isolates unique DSH homes, passes the real path, and cleans failures', async () => {
    const { runDsh, withIsolatedDshHome } = await import('../scripts/isolation.mjs')
    const parent = mkdtempSync(resolve(tmpdir(), 'ominime-isolation-test-'))
    const seenRoots: string[] = []
    const seenHomes: string[] = []
    try {
      for (let index = 0; index < 2; index += 1) {
        let createdRoot = ''
        withIsolatedDshHome(({ temporaryRoot, dshHome }) => {
          createdRoot = temporaryRoot
          seenRoots.push(temporaryRoot)
          const output = runDsh(['--dump-config'], {
            cli: '/pinned/dsh.js',
            cwd: '/pinned',
            dshHome,
            runner(command, args, options) {
              expect(command).toBe(process.execPath)
              expect(args).toEqual(['/pinned/dsh.js', '--dump-config'])
              seenHomes.push(options.env.DSH_HOME)
              return 'ok'
            },
          })
          expect(output).toBe('ok')
          expect(existsSync(temporaryRoot)).toBe(true)
        }, { temporaryParent: parent })
        expect(existsSync(createdRoot)).toBe(false)
      }
      expect(new Set(seenRoots).size).toBe(2)
      expect(seenHomes).toEqual(seenRoots.map(path => resolve(path, 'dsh-home')))

      let failedRoot = ''
      expect(() => withIsolatedDshHome(({ temporaryRoot }) => {
        failedRoot = temporaryRoot
        throw new Error('expected failure')
      }, { temporaryParent: parent })).toThrow('expected failure')
      expect(existsSync(failedRoot)).toBe(false)
    } finally {
      rmSync(parent, { recursive: true, force: true })
    }
  })

  it('fails G1 fast on unsupported Node versions', async () => {
    const { assertSupportedNodeVersion } = await import('../scripts/isolation.mjs')
    expect(() => assertSupportedNodeVersion('22.18.9')).toThrow(/unsupported Node/)
    expect(() => assertSupportedNodeVersion('23.10.0')).toThrow(/unsupported Node/)
    expect(() => assertSupportedNodeVersion('22.19.0')).not.toThrow()
    expect(() => assertSupportedNodeVersion('24.0.0')).not.toThrow()
    expect(() => assertSupportedNodeVersion('25.7.0')).not.toThrow()
  })

  it('cleans a fresh pinned build when an injected runner fails', async () => {
    const {
      FRESH_BUILD_ARTIFACTS,
      PINNED_DSH_COMMIT,
      PINNED_DSH_VERSION,
      withFreshPinnedBuild,
    } = await import('../scripts/isolation.mjs')
    const parent = mkdtempSync(resolve(tmpdir(), 'ominime-fresh-build-test-'))
    const canonical = join(parent, 'canonical')
    mkdirSync(canonical)
    writeFileSync(join(canonical, 'package.json'), `${JSON.stringify({ version: PINNED_DSH_VERSION })}\n`)
    let freshRoot = ''
    const runner = (command: string, args: string[]) => {
      if (command === 'git' && args.includes('rev-parse')) return `${PINNED_DSH_COMMIT}\n`
      if (command === 'git' && args.includes('status')) return ''
      if (command === 'git' && args[0] === 'clone') {
        const destination = args.at(-1) as string
        freshRoot = dirname(destination)
        mkdirSync(destination, { recursive: true })
        writeFileSync(join(destination, 'package.json'), `${JSON.stringify({ version: PINNED_DSH_VERSION })}\n`)
        return ''
      }
      if (command === 'git') return ''
      if (command === 'corepack' && args.includes('build:lib')) {
        for (const relativePath of FRESH_BUILD_ARTIFACTS) {
          const artifact = join(freshRoot, 'deepseek-harness', relativePath)
          mkdirSync(dirname(artifact), { recursive: true })
          writeFileSync(artifact, '')
        }
      }
      return ''
    }
    try {
      await expect(withFreshPinnedBuild(() => {
        throw new Error('expected action failure')
      }, {
        canonicalSource: canonical,
        temporaryParent: parent,
        runner: runner as never,
      })).rejects.toThrow('expected action failure')
      expect(freshRoot).not.toBe('')
      expect(existsSync(freshRoot)).toBe(false)
    } finally {
      rmSync(parent, { recursive: true, force: true })
    }
  })

  it('provides a real pinned ToolRuntime health-dispatch proof', async () => {
    const proof = await import('../scripts/health-dispatch-pinned.mjs')
    expect(proof.dispatchHealthPinned).toBeTypeOf('function')
  })

  it('collects every supported production TypeScript source with strict tree boundaries', async () => {
    const { collectTypecheckFiles } = await import('../scripts/typecheck-pinned.mjs')
    const temporaryRoot = mkdtempSync(resolve(tmpdir(), 'ominime-typecheck-collector-test-'))
    const sourceRoot = join(temporaryRoot, 'src')
    const clientRoot = join(sourceRoot, 'client')
    const hostFiles = [
      'src/host.ts',
      'src/host.tsx',
      'src/host.mts',
      'src/host.cts',
      'src/nested/future.mts',
    ]
    const clientFiles = [
      'src/client/browser.ts',
      'src/client/browser.tsx',
      'src/client/browser.mts',
      'src/client/browser.cts',
      'src/client/nested/future.tsx',
    ]
    try {
      for (const relativePath of [
        ...hostFiles,
        ...clientFiles,
        'tests/ignored.ts',
        'lib/ignored.tsx',
      ]) {
        const target = join(temporaryRoot, relativePath)
        mkdirSync(dirname(target), { recursive: true })
        writeFileSync(target, 'export {}\n')
      }

      const projects = collectTypecheckFiles(temporaryRoot)
      const relativePaths = (files: readonly string[]) => files.map(file => relative(temporaryRoot, file))
      expect(relativePaths(projects.host)).toEqual(hostFiles.sort())
      expect(relativePaths(projects.client)).toEqual(clientFiles.sort())

      const symlink = join(sourceRoot, 'linked.ts')
      symlinkSync(join(sourceRoot, 'host.ts'), symlink)
      expect(() => collectTypecheckFiles(temporaryRoot)).toThrow(/symbolic link/i)
      rmSync(symlink)

      const unsupportedHost = join(sourceRoot, 'future.mtsx')
      writeFileSync(unsupportedHost, 'export {}\n')
      expect(() => collectTypecheckFiles(temporaryRoot)).toThrow(/unsupported TypeScript-like extension/i)
      rmSync(unsupportedHost)

      const unsupportedClient = join(clientRoot, 'future.ctsx')
      writeFileSync(unsupportedClient, 'export {}\n')
      expect(() => collectTypecheckFiles(temporaryRoot)).toThrow(/unsupported TypeScript-like extension/i)
    } finally {
      rmSync(temporaryRoot, { recursive: true, force: true })
    }
  })

  it('rejects a symlinked source root without following it outside the project', async () => {
    const { collectTypecheckFiles } = await import('../scripts/typecheck-pinned.mjs')
    const temporaryRoot = mkdtempSync(resolve(tmpdir(), 'ominime-typecheck-root-test-'))
    const projectRoot = join(temporaryRoot, 'project')
    const outsideRoot = join(temporaryRoot, 'outside', 'tree')
    try {
      mkdirSync(projectRoot, { recursive: true })
      mkdirSync(outsideRoot, { recursive: true })
      writeFileSync(join(outsideRoot, 'escaped.ts'), 'export {}\n')
      symlinkSync(outsideRoot, join(projectRoot, 'src'))

      let error: unknown
      try {
        collectTypecheckFiles(projectRoot)
      } catch (candidate) {
        error = candidate
      }
      expect(error).toMatchObject({
        name: 'TypecheckSourceTreeError',
        code: 'TYPECHECK_SOURCE_TREE_INVALID',
        metadata: { reason: 'ROOT_NOT_DIRECTORY' },
      })
      expect(String(error)).not.toContain(temporaryRoot)
      expect(JSON.stringify(error)).not.toContain(temporaryRoot)
    } finally {
      rmSync(temporaryRoot, { recursive: true, force: true })
    }
  })

  it('uses fixed path-free diagnostics for a missing or non-directory source root', async () => {
    const { collectTypecheckFiles } = await import('../scripts/typecheck-pinned.mjs')
    const temporaryRoot = mkdtempSync(resolve(tmpdir(), 'ominime-typecheck-root-test-'))
    const missingProject = join(temporaryRoot, 'missing-project')
    const fileProject = join(temporaryRoot, 'file-project')
    try {
      mkdirSync(missingProject)
      mkdirSync(fileProject)
      writeFileSync(join(fileProject, 'src'), 'not a directory\n')

      for (const [projectRoot, reason] of [
        [missingProject, 'ROOT_MISSING'],
        [fileProject, 'ROOT_NOT_DIRECTORY'],
      ] as const) {
        let error: unknown
        try {
          collectTypecheckFiles(projectRoot)
        } catch (candidate) {
          error = candidate
        }
        expect(error).toMatchObject({
          name: 'TypecheckSourceTreeError',
          code: 'TYPECHECK_SOURCE_TREE_INVALID',
          metadata: { reason },
        })
        expect(String(error)).not.toContain(temporaryRoot)
        expect(JSON.stringify(error)).not.toContain(temporaryRoot)
      }
    } finally {
      rmSync(temporaryRoot, { recursive: true, force: true })
    }
  })

  it('registers a health tool with the exact scaffold result', async () => {
    let definition: {
      name: string
      parameters: unknown
      output: { schema: { required?: string[]; properties: Record<string, { required?: boolean }> } }
      execute: (args: unknown) => Promise<unknown>
    } | undefined
    const plugin = await import(pathToFileURL(resolve(root, 'lib/index.js')).href)
    plugin.apply({
      tools: {
        register(candidate: typeof definition) {
          definition = candidate
        },
      },
    })

    expect(definition?.name).toBe('personal_context_health')
    expect(definition?.parameters).toEqual({
      type: 'object',
      properties: {},
      additionalProperties: false,
    })
    expect(definition?.output.schema.required).toEqual(['status', 'schemaVersion', 'sources'])
    expect(Object.values(definition?.output.schema.properties ?? {}).some(value => value.required)).toBe(false)
    expect(await definition?.execute({})).toEqual({ status: 'scaffold', schemaVersion: 0, sources: [] })
    for (const invalid of [{ unexpected: true }, [], 'text', null]) {
      await expect(definition?.execute(invalid)).rejects.toMatchObject({
        name: 'InvalidHealthArgsError',
        code: 'INVALID_HEALTH_ARGS',
      })
    }
  })

  it('adds the Personal Context view for each declaration lifetime', async () => {
    const plugin = await import('../src/client/index.tsx')
    const entries = new Map<string, { options: Record<string, unknown>; component: () => unknown }>()
    let callback: (() => () => void) | undefined
    const ctx = {
      slots: {
        inject(name: string, candidate: () => () => void) {
          expect(name).toBe('conversation.view')
          callback = candidate
          return () => {}
        },
        register(options: Record<string, unknown>, component: () => unknown) {
          const id = String(options.id)
          entries.set(id, { options, component })
          return () => { entries.delete(id) }
        },
      },
    }

    plugin.apply(ctx as never)
    expect(entries.size).toBe(0)
    const disposeFirst = callback?.()
    expect(entries.get('personal-context')?.options).toMatchObject({
      name: 'conversation.view',
      order: 20,
      label: '个人上下文',
    })
    const rendered = entries.get('personal-context')?.component() as {
      props: { 'aria-label': string; children: Array<{ props: { children: string } }> }
    }
    expect(rendered.props['aria-label']).toBe('个人上下文')
    expect(rendered.props.children.map(child => child.props.children)).toEqual([
      '个人上下文',
      '启用本地上下文来源后，相关内容会显示在这里。',
    ])
    disposeFirst?.()
    expect(entries.size).toBe(0)
    const disposeSecond = callback?.()
    expect(entries.size).toBe(1)
    disposeSecond?.()
    expect(entries.size).toBe(0)
  })
})
