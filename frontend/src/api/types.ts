// 后端接口的数据形状。讲解见 docs/10-frontend.md
// 与 backend/app/schemas.py、backend/store/base.py、backend/app/routes/chat.py 一一对应，
// 后端改了字段这里要跟着改（没有代码生成，靠人对齐——demo 规模下够用）

export interface SessionOut {
  id: string
  title: string
  created_at: string
  updated_at: string
}

/** OpenAI 格式的工具调用。arguments 是 LLM 生成的原始 JSON 字符串，可能不合法 */
export interface StoredToolCall {
  id: string
  type: 'function'
  function: { name: string; arguments: string }
}

/** 会话里存的一条消息：OpenAI 消息格式的超集（tool_name / is_error / data 只给前端用） */
export interface StoredMessage {
  role: 'user' | 'assistant' | 'tool'
  content: string | null
  tool_calls?: StoredToolCall[] | null
  tool_call_id?: string | null
  tool_name?: string | null
  is_error?: boolean | null
  data?: unknown
  created_at: string
}

export interface SessionDetail extends SessionOut {
  messages: StoredMessage[]
}

export interface Usage {
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
}

/** POST /api/chat 的 SSE 事件。type 来自 SSE 的 event: 行，其余字段来自 data: 行的 JSON */
export type ChatEvent =
  | { type: 'session'; session_id: string; title: string }
  | { type: 'token'; content: string }
  | { type: 'tool_call'; tool_name: string; tool_call_id: string; payload: Record<string, unknown> }
  | {
      type: 'tool_result'
      tool_name: string
      tool_call_id: string
      payload: { is_error: boolean; data: unknown; error?: string }
    }
  | { type: 'done'; payload: { iterations: number; usage: Usage } }
  | { type: 'error'; message: string }
