import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { $pinnedSessionIds } from '@/store/layout'
import { $sessions } from '@/store/session'
import { $projectTree } from '@/store/projects'
import type { SessionInfo } from '@/types/hermes'

import { toggleTilePin, tileStoredRow } from './session-tile'

const STORED = 'session-1'
const LINEAGE_ROOT = 'lineage-root-1'

function row(overrides: Partial<SessionInfo> = {}): SessionInfo {
  return {
    cwd: null,
    ended_at: null,
    id: STORED,
    input_tokens: 0,
    is_active: true,
    last_active: 1,
    message_count: 1,
    model: null,
    output_tokens: 0,
    parent_session_id: null,
    preview: null,
    source: 'desktop',
    started_at: 1,
    title: null,
    tool_call_count: 0,
    ...overrides
  }
}

describe('toggleTilePin', () => {
  beforeEach(() => {
    $sessions.set([])
    $projectTree.set([])
    $pinnedSessionIds.set([])
  })

  afterEach(() => {
    $sessions.set([])
    $projectTree.set([])
    $pinnedSessionIds.set([])
  })

  it('pins on the lineage-root id when the row is loaded', () => {
    $sessions.set([row({ _lineage_root_id: LINEAGE_ROOT })])

    toggleTilePin(STORED)

    expect($pinnedSessionIds.get()).toContain(LINEAGE_ROOT)
    expect($pinnedSessionIds.get()).not.toContain(STORED)
  })

  it('toggles back off (unpins) on a second call', () => {
    $sessions.set([row({ _lineage_root_id: LINEAGE_ROOT })])

    toggleTilePin(STORED)
    expect($pinnedSessionIds.get()).toContain(LINEAGE_ROOT)

    toggleTilePin(STORED)
    expect($pinnedSessionIds.get()).not.toContain(LINEAGE_ROOT)
  })

  it('falls back to the stored id when the row has not loaded yet', () => {
    // Session not in $sessions or $projectTree — a brand-new tile whose
    // first turn hasn't persisted a row yet.
    expect(tileStoredRow(STORED)).toBeUndefined()

    toggleTilePin(STORED)

    expect($pinnedSessionIds.get()).toContain(STORED)
  })

  it('leaves unrelated pins untouched', () => {
    $sessions.set([row({ _lineage_root_id: LINEAGE_ROOT })])
    $pinnedSessionIds.set(['other-session'])

    toggleTilePin(STORED)

    expect($pinnedSessionIds.get()).toContain('other-session')
    expect($pinnedSessionIds.get()).toContain(LINEAGE_ROOT)

    // Unpinning our session does not remove the unrelated pin.
    toggleTilePin(STORED)
    expect($pinnedSessionIds.get()).toContain('other-session')
    expect($pinnedSessionIds.get()).not.toContain(LINEAGE_ROOT)
  })
})
