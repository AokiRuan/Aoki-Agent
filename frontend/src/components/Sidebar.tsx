// 会话侧栏。讲解见 docs/10-frontend.md
import type { SessionOut } from '../api/types'

interface Props {
  sessions: SessionOut[]
  currentId: string | null
  onNew: () => void
  onOpen: (id: string) => void
}

function relativeTime(iso: string) {
  // 后端存的是 UTC 时间；不带时区后缀时按 UTC 解析，否则浏览器会当成本地时间
  const t = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`).getTime()
  const min = Math.round((Date.now() - t) / 60000)
  if (min < 1) return '刚刚'
  if (min < 60) return `${min} 分钟前`
  if (min < 60 * 24) return `${Math.round(min / 60)} 小时前`
  return new Date(t).toLocaleDateString()
}

export function Sidebar({ sessions, currentId, onNew, onOpen }: Props) {
  return (
    <aside className="sidebar">
      <div className="brand">聖地巡礼</div>
      <button type="button" className="btn-new" onClick={onNew}>
        + 新对话
      </button>
      <nav className="session-list">
        {sessions.length === 0 && <div className="muted small">还没有会话</div>}
        {sessions.map((s) => (
          <button
            type="button"
            key={s.id}
            className={s.id === currentId ? 'session active' : 'session'}
            onClick={() => onOpen(s.id)}
            title={s.title}
          >
            <span className="session-title">{s.title || '新对话'}</span>
            <span className="session-time">{relativeTime(s.updated_at)}</span>
          </button>
        ))}
      </nav>
    </aside>
  )
}
