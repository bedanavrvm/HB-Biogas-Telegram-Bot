import React, { useEffect, useId, useRef } from 'react';
import Button from '@atlaskit/button/default/button';
import { cssMap, cx } from '@atlaskit/css';
import Lozenge from '@atlaskit/lozenge';
import Heading from '@atlaskit/heading';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { token } from '@atlaskit/tokens';

export const statusLabel = (status: string, needs = false) => needs ? 'Needs details' : /^(closed|resolved)$/i.test(status) ? 'Closed' : /^reopened$/i.test(status) ? 'Reopened' : 'Open';
export const complaintCount = (value: number) => `${value} ${value === 1 ? 'complaint' : 'complaints'}`;
export function ComplaintStatus({ status, needs = false }: { status: string; needs?: boolean }) {
  const label = statusLabel(status, needs);
  return <Lozenge appearance={label === 'Closed' ? 'success' : label === 'Open' ? 'inprogress' : 'moved'}>{label}</Lozenge>;
}
export function displayDate(value: string, month = false) {
  if (!value) return 'Not recorded';
  const stamp = /^\d{4}(?:-\d{2})?$/.test(value) ? value.length === 4 ? value + '-01-01' : value + '-01' : value;
  const parsed = /^\d{4}-\d{2}-\d{2}/.test(stamp) ? new Date(stamp.slice(0, 10) + 'T12:00:00Z') : new Date(stamp);
  return Number.isNaN(parsed.valueOf()) ? value : new Intl.DateTimeFormat('en-GB', { ...(month ? {} : { day: 'numeric' }), month: 'short', year: 'numeric', timeZone: 'Africa/Nairobi' }).format(parsed);
}
const styles = cssMap({
  dialog: { font: token('font.body'), width: '94vw', maxWidth: '60rem', maxHeight: '90vh', boxSizing: 'border-box', padding: token('space.300'), borderWidth: token('border.width'), borderStyle: 'solid', borderColor: token('color.border'), borderRadius: token('radius.large'), backgroundColor: token('elevation.surface.overlay'), color: token('color.text'), boxShadow: token('elevation.shadow.overlay'), overflowY: 'auto' },
  compact: { maxWidth: '32rem' },
  wide: { width: '98vw', maxWidth: '90rem', maxHeight: '96vh', padding: token('space.150') },
});
/** Native modal focus/inert/Escape semantics with the existing ADS content. */
export function TaskDialog({ title, close, children, compact = false, wide = false }: { title: string; close: () => void; children: React.ReactNode; compact?: boolean; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null), heading = useId();
  const closeRef = useRef(close); closeRef.current = close;
  useEffect(() => { const dialog = ref.current!; const opener = document.activeElement as HTMLElement | null; dialog.showModal(); const cancel = (event: Event) => { event.preventDefault(); closeRef.current(); }; dialog.addEventListener('cancel', cancel); return () => { dialog.removeEventListener('cancel', cancel); dialog.close(); opener?.focus(); }; }, []);
  return <Box as="dialog" ref={ref} aria-labelledby={heading} xcss={cx(styles.dialog, compact && styles.compact, wide && styles.wide)}><Stack space="space.250"><Inline spread="space-between" alignBlock="center" space="space.150"><Heading id={heading} as="h2" size="medium">{title}</Heading><Button appearance="subtle" onClick={close}>Close</Button></Inline>{children}</Stack></Box>;
}
