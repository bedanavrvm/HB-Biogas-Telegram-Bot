import React from 'react';
import { IconButton } from '@atlaskit/button/new';
import CopyIcon from '@atlaskit/icon/core/copy';
import { Anchor } from '@atlaskit/primitives/compiled/anchor';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import { cssMap } from '@atlaskit/css';
import { token } from '@atlaskit/tokens';
import { notify } from './browser-interactions';
import { Section, displayDate } from './complaints-ui';
import type { Detail } from './complaints-operations-transport';

const styles = cssMap({
  facts: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 7rem), 1fr))', gap: token('space.150'), paddingBlock: token('space.150'), overflowWrap: 'anywhere', '@media (min-width: 64rem)': {gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 12rem), 1fr))'} },
});

export function CaseFacts({ item }: { item: Detail }) {
  return <Box xcss={styles.facts} aria-label="Case information">
    <Stack space="space.050"><Text size="small" color="color.text.subtle">National ID</Text><Inline shouldWrap alignBlock="center" space="space.050"><Text>{item.customer_id || 'Not provided'}</Text>{item.customer_id && <IconButton appearance="subtle" label="Copy National ID" icon={CopyIcon} onClick={() => { void navigator.clipboard.writeText(item.customer_id).then(() => notify('National ID copied.')).catch(() => notify('Copy is unavailable. Select the value and copy it.', 'warning')); }}/>}</Inline></Stack>
    {[['Primary phone', item.customer_phone], ...(item.secondary_phone ? [['Alternative phone', item.secondary_phone]] : [])].map(([label, phone]) => <Stack key={label} space="space.050"><Text size="small" color="color.text.subtle">{label}</Text>{phone ? <Anchor href={`tel:${phone}`}>{phone}</Anchor> : <Text>Not provided</Text>}</Stack>)}
    {[["Branch", item.branch], ["Complaint type", item.category], ["Reported", displayDate(item.reported_at)], ["Age", item.age_label]].map(([label, value]) => <Stack key={label} space="space.050"><Text size="small" color="color.text.subtle">{label}</Text><Text>{value || 'Not recorded'}</Text></Stack>)}
  </Box>;
}

export function CaseLocation({ item }: { item: Detail }) {
  let map = '';
  try {
    const url = new URL(item.location?.url || '');
    if (['http:', 'https:'].includes(url.protocol)) map = url.href;
  } catch { /* Legacy records can have an incomplete map reference. */ }
  return <Section title="Location"><Box xcss={styles.facts}>
    {[["County", item.county], ["Constituency", item.constituency], ["Village/Nearest Landmark", item.village]].map(([label, value]) => <Stack key={label} space="space.050"><Text size="small" color="color.text.subtle">{label}</Text><Text>{value || 'Not recorded'}</Text></Stack>)}
    {map && <Stack space="space.050"><Text size="small" color="color.text.subtle">Map pin</Text><Anchor href={map} target="_blank" rel="noopener noreferrer">Open map pin</Anchor></Stack>}
  </Box></Section>;
}
