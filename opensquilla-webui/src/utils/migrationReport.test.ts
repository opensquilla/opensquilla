import { describe, expect, it } from 'vitest'

import { formatByteSize, summarizeMigrationReport } from './migrationReport'

// Miniature report following docs/self-migration-report-contract.md (synthetic
// public-dummy data only).
const dryRunReport = {
  source: '/tmp/legacy-home',
  source_kind: 'windows-portable',
  target: '/tmp/target-home',
  output_dir: '',
  apply: false,
  items: [
    { kind: 'preflight/disk', source: '/tmp/legacy-home', destination: '/tmp/target-home', status: 'skipped', reason: 'ok', details: {} },
    {
      kind: 'preflight/target',
      source: null,
      destination: '/tmp/target-home',
      status: 'error',
      reason: 'target home already contains session data; pass --overwrite to replace it (timestamped backups are taken)',
      details: {},
    },
    { kind: 'state/sessions', source: 'a', destination: 'b', status: 'planned', reason: '', details: {} },
    { kind: 'state/memory', source: 'c', destination: 'd', status: 'planned', reason: '', details: {} },
    { kind: 'config', source: 'e', destination: 'f', status: 'planned', reason: '', details: {} },
  ],
  candidates: [],
  config_transforms: [],
  secret_relocations: [],
  paused_jobs: [
    { id: '1', name: 'daily-digest', cron_expr: '0 9 * * *' },
    { id: '2', name: 'weekly-report', cron_expr: '0 8 * * 1' },
  ],
  preflight: {
    source_gateway_running: false,
    target_gateway_running: false,
    schema_ahead: false,
    disk_required_bytes: 5 * 1024 * 1024,
    disk_free_bytes: 40 * 1024 * 1024 * 1024,
  },
  notes: ['source home is left untouched at its original path'],
}

describe('summarizeMigrationReport', () => {
  it('condenses a dry-run report into counts, disk figures, and overwrite need', () => {
    const summary = summarizeMigrationReport(dryRunReport)
    expect(summary.itemCounts).toEqual({ migrated: 0, planned: 3, skipped: 1, error: 1 })
    expect(summary.pausedJobs).toBe(2)
    expect(summary.diskRequiredBytes).toBe(5 * 1024 * 1024)
    expect(summary.diskFreeBytes).toBe(40 * 1024 * 1024 * 1024)
    expect(summary.needsOverwrite).toBe(true)
    expect(summary.errorNotes).toHaveLength(1)
    expect(summary.errorNotes[0]).toContain('preflight/target')
    expect(summary.notes).toEqual(['source home is left untouched at its original path'])
  })

  it('does not require overwrite when only non-target items errored', () => {
    const summary = summarizeMigrationReport({
      items: [
        { kind: 'preflight/disk', status: 'error', reason: 'not enough free disk space' },
      ],
    })
    expect(summary.needsOverwrite).toBe(false)
    expect(summary.itemCounts.error).toBe(1)
    expect(summary.errorNotes).toEqual(['preflight/disk: not enough free disk space'])
  })

  it('degrades absent or malformed reports to an empty summary instead of throwing', () => {
    for (const report of [null, undefined, 'oops', 42, [], { items: 'nope', preflight: [] }]) {
      const summary = summarizeMigrationReport(report)
      expect(summary.itemCounts).toEqual({ migrated: 0, planned: 0, skipped: 0, error: 0 })
      expect(summary.pausedJobs).toBe(0)
      expect(summary.diskRequiredBytes).toBeNull()
      expect(summary.diskFreeBytes).toBeNull()
      expect(summary.needsOverwrite).toBe(false)
      expect(summary.errorNotes).toEqual([])
      expect(summary.notes).toEqual([])
    }
  })
})

describe('formatByteSize', () => {
  it('formats binary sizes with a compact unit', () => {
    expect(formatByteSize(0)).toBe('0 B')
    expect(formatByteSize(512)).toBe('512 B')
    expect(formatByteSize(2048)).toBe('2 KiB')
    expect(formatByteSize(5 * 1024 * 1024)).toBe('5 MiB')
    expect(formatByteSize(1.5 * 1024 * 1024 * 1024)).toBe('1.5 GiB')
    expect(formatByteSize(40 * 1024 * 1024 * 1024)).toBe('40 GiB')
  })

  it('renders unknown values as an em dash', () => {
    expect(formatByteSize(null)).toBe('—')
    expect(formatByteSize(Number.NaN)).toBe('—')
    expect(formatByteSize(-1)).toBe('—')
  })
})
