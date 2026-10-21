// 一次工具调用在对话里的样子。讲解见 docs/10-frontend.md「工具过程可视化」
import { useState } from 'react'
import type { ToolPart } from '../chat/model'
import { describeArgs, describeResult, toolLabel } from '../chat/tools'

export function ToolStep({ part }: { part: ToolPart }) {
  const [open, setOpen] = useState(false)
  const label = toolLabel(part.name)
  const args = describeArgs(part)

  let summary = ''
  let tone: string = part.status
  if (part.status === 'ok') {
    const r = describeResult(part)
    summary = r.text
    if (r.warn) tone = 'warn'
  } else if (part.status === 'error') {
    summary = part.error ?? '失败'
  }

  return (
    <div className={`tool-step tone-${tone}`}>
      <button type="button" className="tool-head" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="tool-icon" aria-hidden>
          {part.status === 'running' ? <span className="spinner" /> : tone === 'ok' ? '✓' : '!'}
        </span>
        <span className="tool-label">{part.status === 'running' ? `正在${label}…` : label}</span>
        {args && <span className="tool-args">{args}</span>}
        {summary && <span className="tool-summary">→ {summary}</span>}
        <span className="tool-caret" aria-hidden>{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        // 展开后看原始数据：这正是 LLM 拿到的东西，排查「它为什么这么回答」时很有用
        <div className="tool-detail">
          <div className="muted">
            {part.name} · {part.id}
          </div>
          <pre>参数 {JSON.stringify(part.args, null, 2)}</pre>
          {part.status !== 'running' && (
            <pre>
              结果 {part.status === 'error' ? part.error : JSON.stringify(part.data, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}
