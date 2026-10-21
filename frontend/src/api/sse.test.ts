import { describe, expect, it } from 'vitest'
import { readSSE } from './sse'

/** 把字节按给定位置切成多个 chunk，模拟网络分块 */
function streamOf(bytes: Uint8Array<ArrayBuffer>, cuts: number[]): ReadableStream<Uint8Array<ArrayBuffer>> {
  const bounds = [0, ...[...cuts].sort((a, b) => a - b), bytes.length]
  return new ReadableStream({
    start(controller) {
      for (let i = 0; i < bounds.length - 1; i++) controller.enqueue(bytes.slice(bounds[i], bounds[i + 1]))
      controller.close()
    },
  })
}

async function collect(stream: ReadableStream<Uint8Array<ArrayBuffer>>) {
  const out = []
  for await (const m of readSSE(stream)) out.push(m)
  return out
}

// 与后端 FastAPI 实际输出的格式一致（行分隔符是 \n，见 docs/10-frontend.md）
const RAW =
  'event: session\ndata: {"session_id":"s1","title":"莉可丽丝"}\n\n' +
  ': ping\n\n' +
  'event: token\ndata: {"content":"我来查"}\n\n' +
  'event: done\ndata: {"payload":{"iterations":1}}\n\n'

const EXPECTED = [
  { event: 'session', data: '{"session_id":"s1","title":"莉可丽丝"}' },
  { event: 'token', data: '{"content":"我来查"}' },
  { event: 'done', data: '{"payload":{"iterations":1}}' },
]

describe('readSSE', () => {
  it('解析事件、跳过注释', async () => {
    const bytes = new TextEncoder().encode(RAW)
    expect(await collect(streamOf(bytes, []))).toEqual(EXPECTED)
  })

  it('任意位置切块都得到同样结果——包括切在一个汉字的 3 个字节中间', async () => {
    const bytes = new TextEncoder().encode(RAW)
    // 「莉」在 UTF-8 里是 3 个字节，找到它并切在它中间
    const mid = bytes.indexOf(0xe8) + 1
    for (const cuts of [[mid], [1, 2, 3], [mid, mid + 1, 40, 41, 80]]) {
      expect(await collect(streamOf(bytes, cuts))).toEqual(EXPECTED)
    }
    // 极端情况：逐字节到达
    const every = Array.from({ length: bytes.length - 1 }, (_, i) => i + 1)
    expect(await collect(streamOf(bytes, every))).toEqual(EXPECTED)
  })

  it('兼容 \\r\\n 换行和多行 data', async () => {
    const bytes = new TextEncoder().encode('event: x\r\ndata: a\r\ndata: b\r\n\r\n')
    expect(await collect(streamOf(bytes, []))).toEqual([{ event: 'x', data: 'a\nb' }])
  })

  it('没有 event 行时事件名是 message', async () => {
    const bytes = new TextEncoder().encode('data: 1\n\n')
    expect(await collect(streamOf(bytes, []))).toEqual([{ event: 'message', data: '1' }])
  })
})
