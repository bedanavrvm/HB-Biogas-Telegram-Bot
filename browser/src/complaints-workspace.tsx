import React, { useEffect, useRef, useState } from 'react';
import Button from '@atlaskit/button/default/button';
import { cssMap } from '@atlaskit/css';
import Form, { ErrorMessage, Field, Label, MessageWrapper } from '@atlaskit/form';
import Heading from '@atlaskit/heading';
import { Root } from '@atlaskit/navigation-system/layout/root';
import { Main } from '@atlaskit/navigation-system/layout/main';
import { TopNav, TopNavStart, TopNavMiddle, TopNavEnd } from '@atlaskit/navigation-system/layout/top-nav';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Grid } from '@atlaskit/primitives/compiled/grid';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import SectionMessage from '@atlaskit/section-message';
import Select from '@atlaskit/select';
import Textfield from '@atlaskit/textfield';
import { token } from '@atlaskit/tokens';
import { ComplaintReadError, groupPath, readComplaints, type CaseDetail, type CasePage, type Group } from './complaints-transport';

// Current official ADS guidance and deliberate application choices: DESIGN.md / ADR 0070.
const styles = cssMap({
  page: { width: '100%', maxWidth: '81rem', marginInline: 'auto', padding: token('space.200'), boxSizing: 'border-box', '@media (min-width: 64rem)': { paddingInline: token('space.400') } },
  // Distinct from Root's base atomic class: late development style insertion
  // must not override Root's desktop grid while keeping its four named areas.
  columns: { gridTemplateColumns: 'repeat(1, minmax(0, 1fr))', alignItems: 'start', '@media (min-width: 64rem)': { gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)' } },
  filters: { gridTemplateColumns: 'repeat(1, minmax(0, 1fr))', alignItems: 'end', '@media (min-width: 48rem)': { gridTemplateColumns: 'minmax(0, 1fr) 10rem auto' } },
  panel: { minWidth: 0, padding: token('space.200'), borderStyle: 'solid', borderWidth: token('border.width'), borderColor: token('color.border'), borderRadius: token('radius.medium'), overflowWrap: 'anywhere' },
  row: { paddingBlock: token('space.050'), borderBlockEndStyle: 'solid', borderBlockEndWidth: token('border.width'), borderBlockEndColor: token('color.border'), minWidth: 0, overflowWrap: 'anywhere' },
  group: { minWidth: '12rem', maxWidth: '100%' },
  facts: { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' },
  description: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' },
});
const statuses = [{ value: 'pending', label: 'Pending' }, { value: 'resolved', label: 'Resolved' }, { value: 'all', label: 'All statuses' }];
const actions: Record<string, string> = { created: 'Complaint recorded', updated: 'Complaint updated', commented: 'Resolution comment added', resolved: 'Complaint resolved', reopened: 'Complaint reopened', review_completed: 'Details completed', details_completed: 'Missing details completed', evidence_uploaded: 'Evidence uploaded' };

export function ComplaintsWorkspace({ signOut, recheck, demo = false, read = readComplaints, toolbar, detailExtension, initialQuery = '', initialStatus = 'pending', initialGroup = '' }: { signOut: () => void; recheck: () => void; demo?: boolean; read?: typeof readComplaints; toolbar?: React.ReactNode; detailExtension?: (detail: CaseDetail, group: string) => React.ReactNode; initialQuery?: string; initialStatus?: string; initialGroup?: string }) {
  const [groups, setGroups] = useState<Group[] | null>(null);
  const [group, setGroup] = useState(initialGroup);
  const [query, setQuery] = useState(initialQuery);
  const [status, setStatus] = useState(initialStatus);
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [list, setList] = useState<{ key: string; data: CasePage } | null>(null);
  const [selected, setSelected] = useState('');
  const [detail, setDetail] = useState<{ key: string; data: CaseDetail } | null>(null);
  const [error, setError] = useState<{ scope: 'groups' | 'list' | 'detail'; key: string; status: number } | null>(null);
  const callbacks = useRef({ recheck }); callbacks.current = { recheck };
  const listKey = JSON.stringify([group, query, status, page, refresh]);
  const detailKey = JSON.stringify([listKey, selected]);
  const currentList = list?.key === listKey ? list.data : null;
  const currentDetail = detail?.key === detailKey ? detail.data : null;
  const currentError = error && (error.scope === 'groups' || error.key === listKey || error.key === detailKey) ? error : null;

  useEffect(() => { document.title = demo ? 'Complaints demo - JBL staff workspace' : 'Complaints - JBL staff workspace'; }, [demo]);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const timeout = setTimeout(() => controller.abort(), 15000);
    setGroups(null); setError(null);
    void read<{ groups: Group[] }>('groups/', controller.signal).then(result => {
      if (active) { setGroups(result.groups); setGroup(previous => result.groups.some(item => item.key === previous) ? previous : result.groups[0]?.key || ''); }
    }).catch(failure => {
      if (!active) return;
      const code = failure instanceof ComplaintReadError ? failure.status : 0;
      if (code === 401) callbacks.current.recheck();
      else setError({ scope: 'groups', key: '', status: code });
    }).finally(() => clearTimeout(timeout));
    return () => { active = false; controller.abort(); clearTimeout(timeout); };
  }, [refresh, read]);

  useEffect(() => {
    if (!group || !groups?.some(item => item.key === group)) return;
    const controller = new AbortController();
    let active = true;
    const timeout = setTimeout(() => controller.abort(), 15000);
    setSelected(''); setDetail(null); setError(null);
    const params = new URLSearchParams({ q: query, status, page: String(page) });
    void read<CasePage>(groupPath(group) + '?' + params, controller.signal).then(data => {
      if (active) { setList({ key: listKey, data }); setSelected(data.items[0]?.key || ''); }
    }).catch(failure => {
      if (!active) return;
      const code = failure instanceof ComplaintReadError ? failure.status : 0;
      setList(null); setDetail(null); setSelected('');
      if (code === 401) callbacks.current.recheck();
      else setError({ scope: 'list', key: listKey, status: code });
    }).finally(() => clearTimeout(timeout));
    return () => { active = false; controller.abort(); clearTimeout(timeout); };
  }, [group, groups, query, status, page, listKey, read]);

  useEffect(() => {
    if (!selected || !currentList?.items.some(item => item.key === selected)) return;
    const controller = new AbortController();
    let active = true;
    const timeout = setTimeout(() => controller.abort(), 15000);
    setDetail(null); setError(null);
    void read<{ case: CaseDetail }>(groupPath(group) + encodeURIComponent(selected) + '/', controller.signal).then(result => {
      if (active) setDetail({ key: detailKey, data: result.case });
    }).catch(failure => {
      if (!active) return;
      const code = failure instanceof ComplaintReadError ? failure.status : 0;
      setDetail(null);
      if (code === 401) callbacks.current.recheck();
      else setError({ scope: 'detail', key: detailKey, status: code });
    }).finally(() => clearTimeout(timeout));
    return () => { active = false; controller.abort(); clearTimeout(timeout); };
  }, [selected, currentList, group, detailKey, read]);

  const denied = currentError?.status === 403;
  return <Root>
    <TopNav><TopNavStart sideNavToggleButton={null}><Text weight="bold">JBL Staff workspace</Text></TopNavStart><TopNavMiddle>{null}</TopNavMiddle><TopNavEnd><Button appearance="subtle" onClick={signOut}>{demo ? 'Exit demo' : 'Sign out'}</Button></TopNavEnd></TopNav>
    <Main><Box xcss={styles.page} testId="complaints-content"><Stack space={demo ? 'space.150' : 'space.200'}>
      <Inline alignBlock="center" spread="space-between" shouldWrap space="space.100">
        <Stack space="space.050"><Heading as="h1" size="large">Complaints</Heading><Text color="color.text.subtle">{demo ? 'Local demo · Synthetic cases' : 'Review cases and their history.'}</Text></Stack>
        <Inline space="space.150" alignBlock="center" shouldWrap>
          {groups && groups.length === 1 && <Text weight="medium">{groups[0].label}</Text>}
          {groups && groups.length > 1 && <Box xcss={styles.group}><Label htmlFor="complaint-group">Workspace</Label><Select inputId="complaint-group" options={groups.map(item => ({ value: item.key, label: item.label }))} value={groups.filter(item => item.key === group).map(item => ({ value: item.key, label: item.label }))} onChange={option => { setGroup(option?.value || ''); setPage(1); }} /></Box>}
          <Button onClick={() => setRefresh(value => value + 1)}>Refresh</Button>
        </Inline>
      </Inline>
      {toolbar}
      {currentError && <Box role="alert"><SectionMessage appearance="error" title={denied ? 'Complaint access unavailable' : 'Could not load complaints'} headingLevel="h2"><Text as="p">{denied ? 'Your current permissions do not allow this view. Contact your administrator if you need access.' : 'Check your connection, then refresh to try again.'}</Text></SectionMessage></Box>}
      {!groups && !currentError && <Box role="status"><Text>Loading your workspaces…</Text></Box>}
      {groups?.length === 0 && <SectionMessage title="No Complaints workspace available" headingLevel="h2"><Text as="p">Your account has no current Complaints read access. Contact your administrator if you need it.</Text></SectionMessage>}
      {Boolean(groups?.length) && <>
        <Form<{ search: string }> onSubmit={values => { setQuery(values.search.trim()); setPage(1); }}>{({ formProps }) => <Box as="form" {...formProps}>
          <Grid xcss={styles.filters} gap="space.150">
            <Field<string> name="search" label="Search name or reference" defaultValue={query} validate={value => (value?.length || 0) > 150 ? 'Use 150 characters or fewer.' : undefined}>{({ fieldProps, error: fieldError }) => <><Textfield {...fieldProps} autoComplete="off" isInvalid={Boolean(fieldError)} /><MessageWrapper>{fieldError && <ErrorMessage>{fieldError}</ErrorMessage>}</MessageWrapper></>}</Field>
            <Box><Label htmlFor="complaint-status">Status</Label><Select inputId="complaint-status" options={statuses} value={statuses.find(option => option.value === status)} onChange={option => { setStatus(option?.value || 'pending'); setPage(1); }} /></Box>
            <Button type="submit" appearance="primary">Search</Button>
          </Grid>
        </Box>}</Form>
        <Grid xcss={styles.columns} gap="space.200">
          <Box as="section" aria-label="Complaint queue" xcss={styles.panel}><Stack space="space.100">
            <Heading as="h2" size="small">{currentList ? `${currentList.pagination.total} ${currentList.pagination.total === 1 ? 'case' : 'cases'}` : 'Cases'}</Heading>
            {!currentList && !currentError && <Box role="status"><Text>Loading cases…</Text></Box>}
            {currentList?.items.length === 0 && <Text as="p">No cases match these filters. Try another name, reference or status.</Text>}
            {currentList?.items.map(item => <Box key={item.key} xcss={styles.row}><Stack space="space.050">
              <Inline alignBlock="center" shouldWrap space="space.100"><Button appearance="subtle" isSelected={selected === item.key} onClick={() => setSelected(item.key)}>{item.reference}</Button><Text weight="medium">{item.customer_name || 'Unnamed customer'}</Text></Inline>
              <Text size="small" color="color.text.subtle">{[item.status, item.branch, item.category].filter(Boolean).join(' · ')}</Text>
            </Stack></Box>)}
            {currentList && <Inline spread="space-between" alignBlock="center" shouldWrap space="space.100">
              <Text size="small">Page {currentList.pagination.page} of {currentList.pagination.pages}</Text>
              <Inline space="space.050"><Button isDisabled={currentList.pagination.page <= 1} onClick={() => setPage(currentList.pagination.page - 1)}>Previous</Button><Button isDisabled={currentList.pagination.page >= currentList.pagination.pages} onClick={() => setPage(currentList.pagination.page + 1)}>Next</Button></Inline>
            </Inline>}
          </Stack></Box>
          <Box as="section" aria-label="Case detail" xcss={styles.panel}>
            {currentDetail ? <Stack space="space.150">
              <Inline spread="space-between" alignBlock="center" shouldWrap space="space.100"><Heading as="h2" size="medium">{currentDetail.reference}</Heading><Text weight="medium">{currentDetail.status}</Text></Inline>
              <Heading as="h3" size="small">{currentDetail.customer_name || 'Unnamed customer'}</Heading>
              <Grid xcss={styles.facts} gap="space.150">{[['Branch', currentDetail.branch], ['Category', currentDetail.category], ['Reported (Nairobi)', currentDetail.reported_at]].map(([label, value]) => <Stack key={label} space="space.050"><Text size="small" color="color.text.subtle">{label}</Text><Text>{value || 'Not recorded'}</Text></Stack>)}</Grid>
              <Stack space="space.050"><Heading as="h3" size="small">Complaint</Heading><Box xcss={styles.description}><Text as="p">{currentDetail.description || 'No description recorded.'}</Text></Box></Stack>
              {detailExtension?.(currentDetail, group)}
              <Stack space="space.100"><Heading as="h3" size="small">History</Heading>
                {currentDetail.history.length === 0 && <Text color="color.text.subtle">No recorded updates yet.</Text>}
                {currentDetail.history.map((item, index) => <Stack key={index} space="space.050"><Text weight="medium">{actions[item.action] || 'Complaint updated'}</Text><Text size="small" color="color.text.subtle">{[item.created_at, item.updated_by, item.actor_affiliation, item.status].filter(Boolean).join(' · ')}</Text>{item.note && <Text as="p">{item.note}</Text>}</Stack>)}
                {currentDetail.history_truncated && <Text color="color.text.subtle">Showing the latest 100 updates.</Text>}
              </Stack>
            </Stack> : <Stack space="space.100"><Heading as="h2" size="small">Case detail</Heading><Box role="status"><Text>{selected && !currentError ? 'Loading case…' : 'Choose a case to review its details and history.'}</Text></Box></Stack>}
          </Box>
        </Grid>
      </>}
    </Stack></Box></Main>
  </Root>;
}
