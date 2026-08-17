import { existsSync, readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import {
  PINNED_DSH_COMMIT,
  PINNED_DSH_VERSION,
  runDsh,
  verifyPinnedCheckout,
  withFreshPinnedBuild,
  withIsolatedDshHome,
} from './isolation.mjs'

const scriptDir = dirname(fileURLToPath(import.meta.url))
const pluginRoot = resolve(scriptDir, '..')

export function smokeInstall({
  dshSource,
  runner,
  temporaryParent,
} = {}) {
  if (dshSource === undefined) throw new Error('smokeInstall requires a fresh built DSH source')
  const cli = join(dshSource, 'apps/cli/lib/bin.js')
  if (!existsSync(cli)) throw new Error(`built DSH CLI not found: ${cli}`)
  verifyPinnedCheckout(dshSource, runner === undefined ? undefined : { runner })

  return withIsolatedDshHome(({ dshHome }) => {
    const execute = args => runDsh(args, {
      cli,
      cwd: dshSource,
      dshHome,
      ...(runner === undefined ? {} : { runner }),
    })

    execute(['plugin', '--profile', 'web', 'add', pluginRoot])
    const config = execute(['--profile', 'web', '--dump-config'])
    if (!config.includes('id: personal-context')) {
      throw new Error('composed config is missing the Personal Context Host row')
    }
    if (!config.includes("name: '@ominime/dsh-personal-context'")
      && !config.includes('name: @ominime/dsh-personal-context')) {
      throw new Error('composed config is missing the Personal Context package row')
    }

    const installedRoot = join(
      dshHome,
      'profiles/web/node_modules/@ominime/dsh-personal-context',
    )
    const installedManifest = JSON.parse(readFileSync(join(installedRoot, 'package.json'), 'utf8'))
    if (installedManifest.dsh?.client?.platform !== 'web') {
      throw new Error('installed package is missing the Personal Context browser row declaration')
    }
    if (!existsSync(join(installedRoot, 'lib/client.js'))) {
      throw new Error('installed Personal Context package has no browser artifact')
    }
    if (!existsSync(join(installedRoot, 'lib/index.js'))) {
      throw new Error('installed Personal Context package has no Host artifact')
    }

    const result = {
      status: 'ok',
      dshVersion: PINNED_DSH_VERSION,
      dshCommit: PINNED_DSH_COMMIT,
      hostRow: 'personal-context',
      browserPackage: '@ominime/dsh-personal-context',
      installedHostArtifact: 'lib/index.js',
      installedClientArtifact: 'lib/client.js',
    }
    process.stdout.write(`${JSON.stringify(result)}\n`)
    return result
  }, temporaryParent === undefined ? undefined : { temporaryParent })
}

const invokedPath = process.argv[1] === undefined ? undefined : pathToFileURL(resolve(process.argv[1])).href
if (invokedPath === import.meta.url) {
  await withFreshPinnedBuild(({ dshSource }) => smokeInstall({ dshSource }))
}
