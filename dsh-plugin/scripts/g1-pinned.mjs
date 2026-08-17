import { withFreshPinnedBuild } from './isolation.mjs'
import { dispatchHealthPinned } from './health-dispatch-pinned.mjs'
import { smokeInstall } from './smoke-install.mjs'
import { typecheckPinned } from './typecheck-pinned.mjs'

await withFreshPinnedBuild(async ({ dshSource, temporaryRoot }) => {
  typecheckPinned({ dshSource, temporaryParent: temporaryRoot })
  await dispatchHealthPinned({ dshSource })
  smokeInstall({ dshSource, temporaryParent: temporaryRoot })
})
