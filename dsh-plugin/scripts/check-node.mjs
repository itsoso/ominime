import { assertSupportedNodeVersion } from './isolation.mjs'

assertSupportedNodeVersion()
process.stdout.write(`${JSON.stringify({ status: 'ok', node: process.versions.node })}\n`)
