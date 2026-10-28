import React, { useEffect, useRef, useState } from 'react';
import Button from '@atlaskit/button/default/button';
import { cssMap } from '@atlaskit/css';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import { token } from '@atlaskit/tokens';
import { operation, OperationError, type HistoryItem, type HistoryChange } from './complaints-operations-transport';
import { Section, displayDate } from './complaints-ui';
import { notify } from './browser-interactions';

const labels: Record<string, string> = { created: 'Complaint recorded', commented: 'HB feedback added', staff_commented: 'Staff comment added', resolved: 'Complaint resolved', reopened: 'Complaint reopened', details_completed: 'Missing details completed' };
const styles = cssMap({
  row: { borderInlineStartStyle: 'solid', borderInlineStartWidth: token('border.width'), borderInlineStartColor: token('color.border'), paddingInlineStart:token('space.150'), paddingBlock: token('space.100') },
  note: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' },
});
function changeValue(value: HistoryChange['new_value']) {
  if (value === null || value === undefined || value === '') return 'Not set';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  return String(value);
}
function RecordedChanges({item}: {item: HistoryItem}) {
  const changes = (item.display_changes || []).filter(change =>
    !(change.previous_recorded === false && (change.new_value === null || change.new_value === undefined || change.new_value === '')) &&
    !(item.note && change.field === 'resolution_details'));
  return changes.length ? <Stack space="space.050" aria-label="Recorded changes">{changes.map(change => <Box key={change.field} xcss={styles.note}>
    <Text weight="medium">{change.label}: </Text><Text>{change.previous_recorded !== false && <>{changeValue(change.old_display ?? change.old_value)} → </>}{changeValue(change.new_display ?? change.new_value)}</Text>
  </Box>)}</Stack> : null;
}
export function Activity({ group, caseKey, initial, next, reported, report = false }: { group: string; caseKey: string; initial: HistoryItem[]; next: string; reported: string; report?: boolean }) {
  const [items, setItems] = useState(initial), [cursor, setCursor] = useState(next), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [expired, setExpired] = useState(false);
  useEffect(()=>{if(error)notify(error,'error');},[error]);
  const request = useRef<AbortController>(), active = useRef(true), inFlight = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; request.current?.abort(); }; }, []);
  const older = async () => {
    if ((!cursor && !expired) || inFlight.current) return;
    inFlight.current = true; setBusy(true); setError('');
    const controller = new AbortController(); request.current = controller;
    const timer = setTimeout(() => controller.abort(), 20000);
    try {
      const page = await operation<{ items: HistoryItem[]; next_cursor: string }>(group, `${report ? 'reports/' : ''}cases/${caseKey}/history/`, controller.signal, { cursor: expired ? '' : cursor });
      if (active.current) { setItems(previous => { if (expired) return page.items; const keys = new Set(previous.map(row => row.id)); return [...previous, ...page.items.filter(row => !keys.has(row.id))]; }); setCursor(page.next_cursor); setExpired(false); }
    } catch (issue) { if (active.current) { setError(issue instanceof OperationError ? issue.message : 'Older activity could not be loaded. Try again.'); if (issue instanceof OperationError && issue.fields.history_cursor) setExpired(true); } }
    finally { clearTimeout(timer); inFlight.current = false; if (active.current) setBusy(false); }
  };
  return <Section title="Activity"><Stack space="space.150">
    {items.map(row => <Box key={row.id} xcss={styles.row}><Stack space="space.050"><Inline shouldWrap spread="space-between" alignBlock="baseline" space="space.100"><Inline shouldWrap space="space.100"><Text weight="medium">{labels[row.action] || 'Complaint updated'}</Text><Text size="small" color="color.text.subtle">{[row.updated_by, row.actor_affiliation].filter(Boolean).join(' · ')}</Text></Inline><Text size="small" color="color.text.subtle">{row.created_at}</Text></Inline>{row.note && row.note !== labels[row.action] && <Box xcss={styles.note}><Text as="p">{row.note}</Text></Box>}<RecordedChanges item={row}/></Stack></Box>)}
    {!cursor && !expired && !items.some(row => row.action === 'created') && <Box xcss={styles.row}><Stack space="space.050"><Text weight="medium">Complaint recorded</Text><Text size="small" color="color.text.subtle">{reported?displayDate(reported):'Creation time not recorded'} · Original actor not recorded</Text></Stack></Box>}
    {error && <Box role="alert"><Text color="color.text.danger">{error}</Text></Box>}
    {(cursor || expired) && <Inline><Button isLoading={busy} onClick={() => { void older(); }}>{expired ? 'Refresh activity' : error ? 'Retry older activity' : 'Load older activity'}</Button></Inline>}
  </Stack></Section>;
}
