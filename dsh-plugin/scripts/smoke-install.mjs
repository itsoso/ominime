import { execFileSync, spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, readdirSync, readFileSync } from 'node:fs'
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

  return withIsolatedDshHome(({ temporaryRoot, dshHome }) => {
    const execute = args => runDsh(args, {
      cli,
      cwd: dshSource,
      dshHome,
      ...(runner === undefined ? {} : { runner }),
    })

    const packRoot = join(temporaryRoot, 'pack')
    mkdirSync(packRoot)
    execFileSync('corepack', ['pnpm', 'pack', '--pack-destination', packRoot], {
      cwd: pluginRoot,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    const archives = readdirSync(packRoot).filter(name => name.endsWith('.tgz'))
    if (archives.length !== 1) throw new Error('package smoke did not create exactly one archive')
    execute(['plugin', '--profile', 'web', 'add', join(packRoot, archives[0])])
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
    if (installedManifest.exports?.['./probe-wechat'] !== undefined) {
      throw new Error('installed package exposes the internal WeChat probe as a library API')
    }
    if (!existsSync(join(installedRoot, 'lib/client.js'))) {
      throw new Error('installed Personal Context package has no browser artifact')
    }
    if (!existsSync(join(installedRoot, 'lib/index.js'))) {
      throw new Error('installed Personal Context package has no Host artifact')
    }
    const installedProbe = join(installedRoot, 'lib/probe-wechat.js')
    if (!existsSync(installedProbe)) {
      throw new Error('installed Personal Context package has no WeChat probe artifact')
    }
    const {
      OMINIME_WECHAT_CONTAINER_ROOT: _containerRoot,
      OMINIME_WECHAT_ACCOUNT_DIRECTORY: _accountDirectory,
      OMINIME_WECHAT_ADAPTER_VERSION: _adapterVersion,
      ...probeEnvironment
    } = process.env
    const isolatedProbeEnvironment = { ...probeEnvironment, HOME: dshHome }
    const importProbe = spawnSync(process.execPath, [
      '--input-type=module',
      '--eval',
      `const loaded = await import(${JSON.stringify(pathToFileURL(installedProbe).href)}); process.stdout.write(JSON.stringify(Object.keys(loaded).sort()))`,
    ], {
      cwd: installedRoot,
      encoding: 'utf8',
      env: isolatedProbeEnvironment,
    })
    if (importProbe.status !== 0 || importProbe.signal !== null || importProbe.error !== undefined) {
      throw new Error('installed WeChat probe artifact could not be imported in isolation')
    }
    let probeExports
    try {
      probeExports = JSON.parse(importProbe.stdout)
    } catch {
      throw new Error('installed WeChat probe artifact did not expose parseable exports')
    }
    if (!Array.isArray(probeExports)) {
      throw new Error('installed WeChat probe artifact exports are not an array')
    }
    const forbiddenExport = probeExports.find(name =>
      /Synthetic|TestOnly|Snapshot|Provider|resolve|discover|probeWechatSource/.test(name))
    if (forbiddenExport !== undefined || JSON.stringify(probeExports) !== '["runWechatProbeCli"]') {
      throw new Error('installed WeChat probe artifact exposes non-CLI APIs')
    }
    const probe = spawnSync(process.execPath, [installedProbe, '--redact'], {
      cwd: installedRoot,
      encoding: 'utf8',
      env: isolatedProbeEnvironment,
    })
    if (probe.status !== 2 || probe.signal !== null || probe.error !== undefined) {
      throw new Error('installed WeChat probe did not fail closed')
    }
    let probeReport
    try {
      probeReport = JSON.parse(probe.stdout)
    } catch {
      throw new Error('installed WeChat probe did not return redacted JSON')
    }
    if (
      probeReport.failureCodes?.length !== 1
      || probeReport.failureCodes[0] !== 'WECHAT_ATOMIC_OPEN_UNAVAILABLE'
    ) {
      throw new Error('installed WeChat probe did not report atomic-open unavailability')
    }

    const result = {
      status: 'ok',
      dshVersion: PINNED_DSH_VERSION,
      dshCommit: PINNED_DSH_COMMIT,
      hostRow: 'personal-context',
      browserPackage: '@ominime/dsh-personal-context',
      installedHostArtifact: 'lib/index.js',
      installedClientArtifact: 'lib/client.js',
      installedProbeArtifact: 'lib/probe-wechat.js',
      wechatProbeFailureCode: 'WECHAT_ATOMIC_OPEN_UNAVAILABLE',
    }
    process.stdout.write(`${JSON.stringify(result)}\n`)
    return result
  }, temporaryParent === undefined ? undefined : { temporaryParent })
}

const invokedPath = process.argv[1] === undefined ? undefined : pathToFileURL(resolve(process.argv[1])).href
if (invokedPath === import.meta.url) {
  await withFreshPinnedBuild(({ dshSource }) => smokeInstall({ dshSource }))
}
