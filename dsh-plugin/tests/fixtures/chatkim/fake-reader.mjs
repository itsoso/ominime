import { createInterface } from 'node:readline'

const mode = process.env.FAKE_CHATKIM_MODE ?? 'normal'
const lines = createInterface({ input: process.stdin, crlfDelay: Infinity })

function reply(value) {
  process.stdout.write(`${JSON.stringify(value)}\n`)
}

for await (const line of lines) {
  const request = JSON.parse(line)
  if (request.id === undefined) continue

  if (mode === 'hang') continue
  if (mode === 'exit') process.exit(7)
  if (mode === 'malformed') {
    process.stdout.write('not-json\n')
    continue
  }
  if (mode === 'overflow') {
    process.stdout.write(`${'x'.repeat(4096)}\n`)
    continue
  }
  if (mode === 'stderr') process.stderr.write('SYNTHETIC-PRIVATE-STDERR\n')

  const id = mode === 'wrong-id' ? request.id + 100 : request.id
  if (request.method === 'initialize') {
    reply({
      jsonrpc: '2.0',
      id,
      result: {
        protocolVersion: '2025-11-25',
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: 'fake-chatkim', version: '0.0.0-test' },
      },
    })
    continue
  }

  if (mode === 'unexpected') {
    reply({ jsonrpc: '2.0', id, result: { isError: false } })
    continue
  }
  if (mode === 'reader-error') {
    reply({
      jsonrpc: '2.0',
      id,
      result: {
        isError: true,
        structuredContent: { private: 'SYNTHETIC-READER-ERROR' },
        content: [{ type: 'text', text: 'SYNTHETIC-READER-ERROR' }],
      },
    })
    continue
  }
  reply({
    jsonrpc: '2.0',
    id,
    result: {
      isError: false,
      structuredContent: {
        operation: request.params?.name,
        arguments: request.params?.arguments,
        body: 'SYNTHETIC-CHAT-BODY',
      },
      content: [{ type: 'text', text: 'unused duplicate content' }],
    },
  })
}
