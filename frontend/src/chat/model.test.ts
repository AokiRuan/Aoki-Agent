import { describe, expect, it } from 'vitest'
import type { ChatEvent, StoredMessage } from '../api/types'
import { type AssistantItem, type ChatItem, applyEvent, emptyAssistant, historyToItems, stopItem } from './model'

const run = (events: ChatEvent[]): AssistantItem => events.reduce(applyEvent, emptyAssistant())

// 一轮真实对话的事件序列：文字 → 工具 → 文字
const EVENTS: ChatEvent[] = [
  { type: 'token', content: '我来' },
  { type: 'token', content: '查一下' },
  { type: 'tool_call', tool_name: 'search_anime', tool_call_id: 'c1', payload: { title: '莉可丽丝' } },
  {
    type: 'tool_result',
    tool_name: 'search_anime',
    tool_call_id: 'c1',
    payload: { is_error: false, data: [{ anime_id: 1 }] },
  },
  { type: 'token', content: '找到了' },
  { type: 'done', payload: { iterations: 2, usage: { total_tokens: 100 } } },
]

describe('applyEvent', () => {
  it('文字与工具按到达顺序交替成片段，相邻 token 合并', () => {
    const item = run(EVENTS)
    expect(item.status).toBe('done')
    expect(item.parts).toEqual([
      { kind: 'text', text: '我来查一下' },
      {
        kind: 'tool',
        id: 'c1',
        name: 'search_anime',
        args: { title: '莉可丽丝' },
        status: 'ok',
        data: [{ anime_id: 1 }],
        error: undefined,
      },
      { kind: 'text', text: '找到了' },
    ])
    expect(item.usage?.total_tokens).toBe(100)
  })

  it('并行的两个调用按 id 各自配对结果，与结果到达顺序无关', () => {
    const item = run([
      { type: 'tool_call', tool_name: 'get_weather_forecast', tool_call_id: 'a', payload: {} },
      { type: 'tool_call', tool_name: 'get_weather_forecast', tool_call_id: 'b', payload: {} },
      { type: 'tool_result', tool_name: 'get_weather_forecast', tool_call_id: 'b', payload: { is_error: true, data: null, error: '超时' } },
      { type: 'tool_result', tool_name: 'get_weather_forecast', tool_call_id: 'a', payload: { is_error: false, data: 1 } },
    ])
    expect(item.parts.map((p) => p.kind === 'tool' && [p.id, p.status, p.error])).toEqual([
      ['a', 'ok', undefined],
      ['b', 'error', '超时'],
    ])
  })

  it('不修改传入的对象', () => {
    const before = emptyAssistant()
    const after = applyEvent(before, { type: 'token', content: 'x' })
    expect(before.parts).toEqual([])
    expect(after).not.toBe(before)
  })

  it('出错或停止时，还在运行的工具标记为未完成', () => {
    const started = run([{ type: 'tool_call', tool_name: 'plan_route', tool_call_id: 'r', payload: {} }])
    for (const item of [applyEvent(started, { type: 'error', message: 'LLM 调用失败' }), stopItem(started)]) {
      expect(item.parts[0]).toMatchObject({ status: 'error', error: '未完成' })
    }
  })
})

describe('historyToItems', () => {
  // 与后端 GET /api/sessions/{id} 的返回一致：LLM 协议顺序，tool 消息带 tool_name / is_error / data
  const t = '2026-10-21T00:00:00Z'
  const HISTORY: StoredMessage[] = [
    { role: 'user', content: '莉可丽丝的圣地', created_at: t },
    {
      role: 'assistant',
      content: '我来查一下',
      tool_calls: [{ id: 'c1', type: 'function', function: { name: 'search_anime', arguments: '{"title":"莉可丽丝"}' } }],
      created_at: t,
    },
    { role: 'tool', content: '[...]', tool_call_id: 'c1', tool_name: 'search_anime', is_error: false, data: [{ anime_id: 1 }], created_at: t },
    { role: 'assistant', content: '找到了', created_at: t },
    { role: 'user', content: '天气呢', created_at: t },
    {
      role: 'assistant',
      content: null,
      tool_calls: [{ id: 'w', type: 'function', function: { name: 'get_weather_forecast', arguments: '{oops' } }],
      created_at: t,
    },
    { role: 'tool', content: '服务不可用', tool_call_id: 'w', tool_name: 'get_weather_forecast', is_error: true, data: null, created_at: t },
    { role: 'assistant', content: '抱歉', created_at: t },
  ]

  it('两条 user 之间的 assistant / tool 折叠成一个回复，与实时路径得到相同的片段', () => {
    const items = historyToItems(HISTORY)
    expect(items.map((i) => i.role)).toEqual(['user', 'assistant', 'user', 'assistant'])

    const live = run(EVENTS)
    const restored = items[1] as AssistantItem
    // 实时路径有 error: undefined 字段，toEqual 视同不存在
    expect(restored.parts).toEqual(live.parts)
  })

  it('失败的调用带错误信息；不合法的参数 JSON 原样保留', () => {
    const second = historyToItems(HISTORY)[3] as AssistantItem
    expect(second.parts[0]).toMatchObject({
      kind: 'tool',
      status: 'error',
      error: '服务不可用',
      args: { _raw: '{oops' },
    })
  })

  it('空历史得到空列表', () => {
    expect(historyToItems([])).toEqual([] as ChatItem[])
  })
})
