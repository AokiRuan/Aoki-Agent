// 手写的 SSE 解析器。讲解见 docs/10-frontend.md「为什么不用 EventSource」
//
// 浏览器自带的 EventSource 只能发 GET、不能带请求体，而 /api/chat 是 POST + JSON。
// 所以用 fetch 拿到响应的字节流，自己按 SSE 规则切分：
//
//   event: token          ← 字段名: 值
//   data: {"content":"我"}
//                          ← 空行 = 一个事件结束
//   : ping                 ← 冒号开头 = 注释（后端的保活），忽略

export interface SSEMessage {
  event: string
  data: string
}

export async function* readSSE(body: ReadableStream<Uint8Array<ArrayBuffer>>): AsyncGenerator<SSEMessage> {
  // TextDecoderStream 负责把字节解码成字符串。不能对每个 chunk 单独 new TextDecoder().decode()：
  // 一个汉字在 UTF-8 里占 3 字节，网络分块可能正好切在一个字的中间
  const reader = body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  let event = 'message'
  let data: string[] = []

  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += value

      const lines = buffer.split('\n')
      // 最后一段可能是半行（还没收到换行符），留到下次拼接
      buffer = lines.pop() ?? ''

      for (const rawLine of lines) {
        const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine // 兼容 \r\n
        if (line === '') {
          if (data.length > 0) yield { event, data: data.join('\n') }
          event = 'message'
          data = []
          continue
        }
        if (line.startsWith(':')) continue

        const colon = line.indexOf(':')
        const field = colon === -1 ? line : line.slice(0, colon)
        let value = colon === -1 ? '' : line.slice(colon + 1)
        if (value.startsWith(' ')) value = value.slice(1) // 规范：冒号后的一个空格不算值
        if (field === 'event') event = value
        else if (field === 'data') data.push(value) // 多行 data 用 \n 拼接
      }
    }
  } finally {
    reader.releaseLock()
  }
}
