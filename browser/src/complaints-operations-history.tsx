import React, { useEffect, useRef, useState } from 'react';
import Button from '@atlaskit/button/default/button';
import { cssMap } from '@atlaskit/css';
import Heading from '@atlaskit/heading';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import { token } from '@atlaskit/tokens';
import { operation, OperationError, type HistoryItem } from './complaints-operations-transport';

const labels: Record<string, string> = { created: 'Complaint recorded', commented: 'Resolution comment', resolved: 'Complaint resolved', reopened: 'Complaint reopened', details_completed: 'Missing details completed' };
const styles = cssMap({
  row: { borderBlockEndStyle: 'solid', borderBlockEndWidth: token('border.width'), borderBlockEndColor: token('color.border'), paddingBlock: token('space.100') },
  note: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' },
});
export function Activity({ group, caseKey, initial, next, reported }: { group: string; caseKey: string; initial: HistoryItem[]; next: string; reported: string }) {
  const [items, setItems] = useState(initial), [cursor, setCursor] = useState(next), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [expired, setExpired] = useState(false);
  const request = useRef<AbortController>(), active = useRef(true), inFlight = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; request.current?.abort(); }; }, []);
  const older = async () => {
    if ((!cursor && !expired) || inFlight.current) return;
    inFlight.current = true; setBusy(true); setError('');
    const controller = new AbortController(); request.current = controller;
    const timer = setTimeout(() => controller.abort(), 20000);
    try {
      const page = await operation<{ items: HistoryItem[]; next_cursor: string }>(group, `cases/${caseKey}/history/`, controller.signal, { cursor: expired ? '' : cursor });
      if (active.current) { setItems(previous => { if (expired) return page.items; const keys = new Set(previous.map(row => row.id)); return [...previous, ...page.items.filter(row => !keys.has(row.id))]; }); setCursor(page.next_cursor); setExpired(false); }
    } catch (issue) { if (active.current) { setError(issue instanceof OperationError ? issue.message : 'Older activity could not be loaded. Try again.'); if (issue instanceof OperationError && issue.fields.history_cursor) setExpired(true); } }
    finally { clearTimeout(timer); inFlight.current = false; if (active.current) setBusy(false); }
  };
  return <Stack space="space.150"><Heading as="h3" size="small">Activity</Heading>
    {items.map(row => <Box key={row.id} xcss={styles.row}><Stack space="space.050"><Text weight="medium">{labels[row.action] || 'Complaint updated'}</Text><Text size="small" color="color.text.subtle">{[row.updated_by, row.actor_affiliation, row.created_at].filter(Boolean).join(' · ')}</Text>{row.note && <Box xcss={styles.note}><Text as="p">{row.note}</Text></Box>}</Stack></Box>)}
    {!cursor && !expired && !items.some(row => row.action === 'created') && <Box xcss={styles.row}><Stack space="space.050"><Text weight="medium">Complaint recorded</Text><Text size="small" color="color.text.subtle">{reported}</Text></Stack></Box>}
    {error && <Box role="alert"><Text color="color.text.danger">{error}</Text></Box>}
    {(cursor || expired) && <Inline><Button isLoading={busy} onClick={() => { void older(); }}>{expired ? 'Refresh activity' : error ? 'Retry older activity' : 'Load older activity'}</Button></Inline>}
  </Stack>;
}
