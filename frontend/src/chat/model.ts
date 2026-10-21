// 界面上的对话模型，以及两条构建它的路径。讲解见 docs/10-frontend.md「两条路径，一个模型」
//
//   实时：SSE 事件 ──applyEvent()──┐
//                                 ├──▶ ChatItem[] ──▶ 渲染
//   恢复：StoredMessage[] ──historyToItems()──┘
//
// 这里全是纯函数（不碰 React、不发请求），所以能直接写单元测试
import type { ChatEvent, StoredMessage, Usage } from '../api/types'

export type ToolStatus = 'running' | 'ok' | 'error'

export interface ToolPart {
  kind: 'tool'
  id: string // tool_call_id，tool_call 与 tool_result 靠它配对
  name: string
  args: Record<string, unknown>
  status: ToolStatus
  data?: unknown
  error?: string
}

export interface TextPart {
  kind: 'text'
  text: string
}

export type Part = TextPart | ToolPart

export interface UserItem {
  role: 'user'
  id: string
  text: string
}

/**
 * 一轮 agent 回复。为什么是 parts 数组而不是一个字符串？
 * 因为文字和工具调用是交替出现的：「我来查一下」→ 调工具 → 「查到了 5 个地点…」。
 * 按到达顺序存成片段，界面就能在文字中间插入工具步骤
 */
export interface AssistantItem {
  role: 'assistant'
  id: string
  parts: Part[]
  status: 'streaming' | 'done' | 'error' | 'stopped'
  error?: string
  usage?: Usage
  iterations?: number
}

export type ChatItem = UserItem | AssistantItem

let seq = 0
export const newId = (prefix: string) => `${prefix}-${Date.now()}-${seq++}`

export function emptyAssistant(): AssistantItem {
  return { role: 'assistant', id: newId('a'), parts: [], status: 'streaming' }
}

/** 把一个实时事件合并进正在生成的回复。返回新对象，不修改入参（React 靠引用变化判断要不要重渲染） */
export function applyEvent(item: AssistantItem, ev: ChatEvent): AssistantItem {
  switch (ev.type) {
    case 'token':
      return { ...item, parts: appendText(item.parts, ev.content) }
    case 'tool_call':
      return {
        ...item,
        parts: [
          ...item.parts,
          { kind: 'tool', id: ev.tool_call_id, name: ev.tool_name, args: ev.payload ?? {}, status: 'running' },
        ],
      }
    case 'tool_result':
      return {
        ...item,
        parts: item.parts.map((p) =>
          p.kind === 'tool' && p.id === ev.tool_call_id
            ? {
                ...p,
                status: ev.payload.is_error ? 'error' : 'ok',
                data: ev.payload.data,
                error: ev.payload.error,
              }
            : p,
        ),
      }
    case 'done':
      return { ...item, status: 'done', usage: ev.payload.usage, iterations: ev.payload.iterations }
    case 'error':
      return { ...item, status: 'error', error: ev.message, parts: settleRunning(item.parts) }
    case 'session':
      return item
  }
}

/** 用户点了停止：还在转圈的工具不会再有结果了 */
export function stopItem(item: AssistantItem): AssistantItem {
  return { ...item, status: 'stopped', parts: settleRunning(item.parts) }
}

function appendText(parts: Part[], text: string): Part[] {
  const last = parts[parts.length - 1]
  if (last?.kind === 'text') {
    return [...parts.slice(0, -1), { kind: 'text', text: last.text + text }]
  }
  // 上一个片段是工具调用（或还没有片段）：开一个新的文字片段
  return [...parts, { kind: 'text', text }]
}

function settleRunning(parts: Part[]): Part[] {
  return parts.map((p) =>
    p.kind === 'tool' && p.status === 'running' ? { ...p, status: 'error', error: '未完成' } : p,
  )
}

/**
 * 把存储的消息还原成界面模型（刷新页面、切换会话时用）。
 *
 * 存储格式按 LLM 的协议组织：user → assistant(带 tool_calls) → tool → tool → assistant → …
 * 界面按「轮」组织：一条 user，一个 AssistantItem（里面是文字与工具交替的 parts）。
 * 所以这里把两条 user 之间的所有 assistant / tool 消息折叠进同一个 AssistantItem
 */
export function historyToItems(messages: StoredMessage[]): ChatItem[] {
  const items: ChatItem[] = []
  let current: AssistantItem | null = null

  for (const [i, m] of messages.entries()) {
    if (m.role === 'user') {
      current = null
      items.push({ role: 'user', id: `h-${i}`, text: m.content ?? '' })
      continue
    }
    if (!current) {
      current = { role: 'assistant', id: `h-${i}`, parts: [], status: 'done' }
      items.push(current)
    }
    if (m.role === 'assistant') {
      if (m.content) current.parts = appendText(current.parts, m.content)
      for (const tc of m.tool_calls ?? []) {
        current.parts.push({
          kind: 'tool',
          id: tc.id,
          name: tc.function.name,
          args: parseArgs(tc.function.arguments),
          status: 'running', // 下面遇到对应的 tool 消息时改成最终状态
        })
      }
    } else {
      // role === 'tool'：按 tool_call_id 找回发起它的那个调用
      const part = current.parts.find((p): p is ToolPart => p.kind === 'tool' && p.id === m.tool_call_id)
      if (part) {
        part.status = m.is_error ? 'error' : 'ok'
        part.data = m.data
        if (m.is_error) part.error = m.content ?? undefined
      }
    }
  }
  return items
}

function parseArgs(raw: string): Record<string, unknown> {
  try {
    const v = JSON.parse(raw)
    return v && typeof v === 'object' ? v : {}
  } catch {
    return { _raw: raw } // LLM 生成了不合法的 JSON：原样展示，方便看出它错在哪
  }
}
