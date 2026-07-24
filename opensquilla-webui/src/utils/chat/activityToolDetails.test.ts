import { describe, expect, it } from 'vitest'
import type { ChatToolCallRenderItem } from '@/types/chat'
import {
  activityDisplayPath,
  projectActivityToolDetail,
  redactActivityDetail,
} from './activityToolDetails'

function call(
  overrides: Partial<ChatToolCallRenderItem> = {},
): ChatToolCallRenderItem {
  return {
    toolId: 'tool-1',
    renderKey: 'tool-1',
    name: 'write_file',
    displayName: 'write_file',
    inputRaw: '{}',
    inputPreview: '{}',
    isRunning: false,
    status: 'success',
    isError: false,
    result: '',
    resultPreview: '',
    isOpen: false,
    ...overrides,
  }
}

describe('activity tool detail projection', () => {
  it('shows workspace-relative file details without putting raw paths in lines', () => {
    const projection = projectActivityToolDetail(call({
      inputRaw: JSON.stringify({
        path: '/private/tmp/opensquilla-test/workspace/games/index.html',
        content: '<html>private body</html>',
      }),
      inputPreview: '{"path":"…"}',
      result: 'Written 35726 bytes to /private/tmp/opensquilla-test/workspace/games/index.html',
      resultPreview: 'Written 35726 bytes to /private/tmp/opensquilla-test/workspace/games/index.html',
    }), 'file.write')

    expect(projection.lines).toEqual([
      { kind: 'target', text: 'games/index.html' },
      { kind: 'bytes', bytes: 35726 },
    ])
    expect(JSON.stringify(projection.lines)).not.toContain('/private/')
    expect(JSON.stringify(projection.lines)).not.toContain('private body')
    expect(projection.rawContent).toContain('/private/tmp/opensquilla-test')
  })

  it('uses artifact names and status instead of raw artifact payloads', () => {
    const projection = projectActivityToolDetail(call({
      name: 'publish_artifact',
      inputRaw: JSON.stringify({
        path: '/private/tmp/opensquilla-test/workspace/games/index.html',
        name: '小游戏合集.html',
      }),
      result: JSON.stringify({
        status: 'published',
        artifact: { id: 'internal-id', download_url: 'https://example.test/private' },
      }),
    }), 'artifact.create')

    expect(projection.lines).toEqual([
      { kind: 'target', text: '小游戏合集.html' },
      { kind: 'published' },
    ])
    expect(JSON.stringify(projection.lines)).not.toContain('internal-id')
  })

  it('reduces path-shaped artifact and unknown-tool names to safe targets', () => {
    expect(projectActivityToolDetail(call({
      name: 'publish_artifact',
      inputRaw: JSON.stringify({
        name: '/Users/example/private/report.html',
      }),
    }), 'artifact.create').lines).toEqual([
      { kind: 'target', text: '…/report.html' },
    ])

    expect(projectActivityToolDetail(call({
      inputRaw: JSON.stringify({
        title: 'C:\\Users\\example\\private\\report.txt',
      }),
    }), 'tool.unknown').lines).toEqual([
      { kind: 'target', text: '…/report.txt' },
    ])
  })

  it('only exposes safe HTTP locations and file basenames for URL-shaped targets', () => {
    expect(projectActivityToolDetail(call({
      inputRaw: JSON.stringify({
        url: 'https://example.test/docs/page?access_token=secret',
      }),
    }), 'web.read').lines).toEqual([
      { kind: 'target', text: 'example.test/docs/page' },
    ])

    expect(projectActivityToolDetail(call({
      inputRaw: JSON.stringify({
        url: 'file:///Users/example/private/report.txt',
      }),
    }), 'web.read').lines).toEqual([
      { kind: 'target', text: '…/report.txt' },
    ])

    expect(projectActivityToolDetail(call({
      inputRaw: JSON.stringify({
        url: 'mailto:private@example.test',
      }),
    }), 'web.read').lines).toEqual([])
    expect(projectActivityToolDetail(call({
      inputRaw: JSON.stringify({
        url: 'data:text/plain,private-payload',
      }),
    }), 'web.read').lines).toEqual([])
  })

  it('keeps raw commands behind the explicit detail viewer', () => {
    const projection = projectActivityToolDetail(call({
      name: 'shell',
      inputRaw: JSON.stringify({
        command: 'OPENAI_API_KEY=sk-secret npm test --password hidden',
      }),
    }), 'command.run')

    expect(projection.lines).toEqual([])
    expect(projection.rawContent).toContain('OPENAI_API_KEY=sk-secret')
  })

  it('reduces absolute error paths to a basename', () => {
    const projection = projectActivityToolDetail(call({
      status: 'error',
      isError: true,
      result: 'Unable to open /Users/example/private/project/file.txt: permission denied',
      resultPreview: 'Unable to open /Users/example/private/project/file.txt: permission denied',
    }), 'file.inspect')

    expect(projection.lines).toEqual([
      { kind: 'error', text: 'Unable to open …/file.txt: permission denied' },
    ])
  })

  it('keeps relative paths and hides external directory structure', () => {
    expect(activityDisplayPath('src/components/App.vue')).toBe('src/components/App.vue')
    expect(activityDisplayPath('C:\\Users\\example\\secret\\App.vue')).toBe('…/App.vue')
    expect(activityDisplayPath('/Users/example/secret/App.vue')).toBe('…/App.vue')
    expect(activityDisplayPath(
      '/tmp/workspace/../../Users/example/secret/key.txt',
    )).toBe('…/key.txt')
  })

  it('only derives written-byte metadata for file mutations', () => {
    expect(projectActivityToolDetail(call({
      name: 'shell',
      result: 'Written 2048 bytes',
      resultPreview: 'Written 2048 bytes',
    }), 'command.run').lines).toEqual([])
    expect(projectActivityToolDetail(call({
      name: 'inspect_file',
      result: 'Written 2048 bytes',
      resultPreview: 'Written 2048 bytes',
    }), 'file.inspect').lines).toEqual([])
  })

  it('keeps file mutation errors visible even when output mentions written bytes', () => {
    expect(projectActivityToolDetail(call({
      status: 'error',
      isError: true,
      inputRaw: '{"path":"src/App.vue"}',
      result: 'Written 2048 bytes before verification failed',
      resultPreview: 'Written 2048 bytes before verification failed',
    }), 'file.write').lines).toEqual([
      { kind: 'target', text: 'src/App.vue' },
      { kind: 'error', text: 'Written 2048 bytes before verification failed' },
    ])
  })

  it('classifies raw input-only and mixed details without result highlighting', () => {
    expect(projectActivityToolDetail(call({
      inputRaw: '{"path":"src/App.vue"}',
    }), 'file.inspect').rawSection).toBe('input')

    expect(projectActivityToolDetail(call({
      inputRaw: '{"path":"src/App.vue"}',
      result: 'file contents',
    }), 'file.inspect').rawSection).toBeUndefined()
  })

  it('redacts sensitive structured values', () => {
    expect(redactActivityDetail(
      '{"password":"secret","apiKey":"hidden"} token=private',
    )).toBe(
      '{"password":"[redacted]","apiKey":"[redacted]"} token=[redacted]',
    )
  })

  it('redacts common environment, flag, bearer, and URL credentials', () => {
    expect(redactActivityDetail([
      'OPENAI_API_KEY=sk-environment-secret',
      '--password flag-secret',
      'Authorization: Bearer bearer-secret-value',
      'https://user:basic-secret@example.test/path?access_token=query-secret',
      'ghp_abcdefghijklmnopqrstuvwxyz',
    ].join('\n'))).toBe([
      'OPENAI_API_KEY=[redacted]',
      '--password [redacted]',
      'Authorization: Bearer [redacted]',
      'https://[redacted]@example.test/path?access_token=[redacted]',
      '[redacted]',
    ].join('\n'))
  })
})
