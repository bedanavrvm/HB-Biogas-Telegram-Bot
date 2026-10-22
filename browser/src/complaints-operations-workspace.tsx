import React, { useEffect, useRef, useState } from 'react';
import Button from '@atlaskit/button/default/button';
import { Anchor } from '@atlaskit/primitives/compiled/anchor';
import { Reports } from './complaints-operations-reports';
import { EvidencePreview, VoiceInput } from './complaints-operations-media';
import { WorkspaceSettings } from './complaints-operations-settings';
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
import { groups as loadGroups, operation, OperationError, download, type Bootstrap, type Complaint, type Detail, type Group, type Locations, type Queue } from './complaints-operations-transport';
import { readRoute, writeRoute, type WorkspaceRoute } from './workspace-navigation';
const styles = cssMap({
    page: { width: '100%', boxSizing: 'border-box', padding: token('space.200'), '@media (min-width: 64rem)': { padding: token('space.300') } },
    columns: { gridTemplateColumns: 'repeat(1, minmax(0, 1fr))', alignItems: 'start', '@media (min-width: 64rem)': { gridTemplateColumns: 'minmax(20rem, 2fr) minmax(0, 3fr)' } },
    panel: { minWidth: 0, padding: token('space.200'), borderStyle: 'solid', borderWidth: token('border.width'), borderColor: token('color.border'), borderRadius: token('radius.medium'), overflowWrap: 'anywhere' },
    row: { minWidth: 0, paddingBlock: token('space.100'), borderBlockEndWidth: token('border.width'), borderBlockEndStyle: 'solid', borderBlockEndColor: token('color.border'), overflowWrap: 'anywhere' },
    fields: { gridTemplateColumns: 'repeat(1, minmax(0, 1fr))', '@media (min-width: 48rem)': { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' } },
    filters: { gridTemplateColumns: 'repeat(1, minmax(0, 1fr))', alignItems: 'end', '@media (min-width: 48rem)': { gridTemplateColumns: 'minmax(0, 2fr) repeat(3, minmax(0, 1fr)) auto' } },
    facts: { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', minWidth: 0 },
    prewrap: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' },
    textarea: { width: '100%', boxSizing: 'border-box', padding: token('space.100'), borderStyle: 'solid', borderWidth: token('border.width'), borderColor: token('color.border.input'), borderRadius: token('radius.small'), backgroundColor: token('color.background.input'), color: token('color.text'), font: token('font.body'), resize: 'vertical' },
    form: { width: '100%', maxWidth: '60rem', marginInline: 'auto' },
});
const statuses = [{ value: 'pending', label: 'Not resolved' }, { value: 'resolved', label: 'Resolved' }, { value: 'all', label: 'All complaints' }];
const actionLabels: Record<string, string> = { resolve: 'Resolve complaint', comment: 'Add resolution comment', reopen: 'Reopen complaint', 'complete-details': 'Complete missing details', 'retry-publication': 'Retry publication' };
const historyLabels: Record<string, string> = { created: 'Complaint recorded', commented: 'Resolution comment', resolved: 'Complaint resolved', reopened: 'Complaint reopened', details_completed: 'Missing details completed' };
function labelStatus(item: Complaint) { return item.needs_details ? 'Needs details' : item.status === 'CLOSED' ? 'Resolved' : 'Not resolved'; }
function failure(error: unknown) { return error instanceof OperationError ? error.message : 'The request could not be confirmed. Your entries are retained. Check your connection and try again.'; }
function useRead<T>(group: string, path: string, refresh: number, body?: Record<string, unknown>) {
    const [state, setState] = useState<{
        key?: string;
        data?: T;
        error?: unknown;
    }>({});
    const bodyKey = JSON.stringify(body);
    const key = JSON.stringify([group, path, refresh, bodyKey]);
    useEffect(() => {
        setState({});
        if (!group || !path)
            return;
        const controller = new AbortController();
        let active = true;
        const timer = setTimeout(() => controller.abort(), 20000);
        void operation<T>(group, path, controller.signal, bodyKey ? JSON.parse(bodyKey) : undefined)
            .then(data => { if (active)
            setState({ key, data }); }).catch(error => { if (active)
            setState({ key, error }); }).finally(() => clearTimeout(timer));
        return () => { active = false; controller.abort(); clearTimeout(timer); };
    }, [group, path, refresh, bodyKey]);
    return state.key === key ? state : {};
}
function Feedback({ error }: {
    error?: unknown;
}) { return error ? <Box role="alert"><SectionMessage appearance="error" title="Action could not be completed" headingLevel="h2"><Text as="p">{failure(error)}</Text></SectionMessage></Box> : null; }
function Choice({ id, label, value, options, onChange, error }: {
    id: string;
    label: string;
    value: string;
    options: {
        value: string;
        label: string;
    }[];
    onChange: (value: string) => void;
    error?: string;
}) {
    return <Box><Label htmlFor={id}>{label}</Label><Select inputId={id} aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : undefined} options={options} value={options.find(option => option.value === value) || null} onChange={option => onChange(option?.value || '')}/>{error && <Box id={`${id}-error`} role="alert"><Text color="color.text.danger">{error}</Text></Box>}</Box>;
}
function Input({ name, label, values, change, errors, required = false, type = 'text' }: {
    name: string;
    label: string;
    values: Record<string, string>;
    change: (name: string, value: string) => void;
    errors: Record<string, string>;
    required?: boolean;
    type?: string;
}) {
    if (name.includes('description') || name.includes('text') || name === 'reason') return <Field<string, HTMLTextAreaElement> name={name} label={label} isRequired={required} defaultValue={values[name] || ''}>{({ fieldProps }) => <><Box as="textarea" {...fieldProps} xcss={styles.textarea} rows={4} value={values[name] || ''} aria-invalid={Boolean(errors[name])} aria-describedby={errors[name] ? `${fieldProps.id}-server-error` : fieldProps['aria-describedby']} onChange={event => { fieldProps.onChange(event); change(name, event.currentTarget.value); }} /><MessageWrapper>{errors[name] && <Box id={`${fieldProps.id}-server-error`}><ErrorMessage>{errors[name]}</ErrorMessage></Box>}</MessageWrapper></>}</Field>;
    return <Field<string> name={name} label={label} isRequired={required} defaultValue={values[name] || ''}>{({ fieldProps }) => <><Textfield {...fieldProps} aria-describedby={errors[name] ? `${fieldProps.id}-server-error` : fieldProps['aria-describedby']} value={values[name] || ''} type={type} isInvalid={Boolean(errors[name])} onChange={event => { fieldProps.onChange(event); change(name, event.currentTarget.value); }} autoComplete={name.includes('phone') ? 'tel' : name === 'client_name' ? 'name' : 'off'}/><MessageWrapper>{errors[name] && <Box id={`${fieldProps.id}-server-error`}><ErrorMessage>{errors[name]}</ErrorMessage></Box>}</MessageWrapper></>}</Field>;
}
function Files({ files, setFiles }: {
    files: File[];
    setFiles: (value: File[]) => void;
}) {
    const picker = useRef<HTMLInputElement>(null), camera = useRef<HTMLInputElement>(null);
    const [error, setError] = useState('');
    const add = (items: FileList | null) => {
        const next = [...files, ...Array.from(items || [])];
        if (next.length > 10 || next.some(file => file.size > 10 * 1024 * 1024) || next.reduce((size, file) => size + file.size, 0) > 30 * 1024 * 1024)
            setError('Choose up to 10 files, 10 MB each and 30 MB in total.');
        else {
            setFiles(next);
            setError('');
        }
    };
    return <Stack space="space.100"><Text weight="medium">Photos and documents</Text>
    <Box as="input" type="file" hidden ref={picker} multiple accept=".jpg,.jpeg,.png,.webp,.pdf" aria-label="Choose evidence files" onChange={event => { add(event.currentTarget.files); event.currentTarget.value = ''; }}/>
    <Box as="input" type="file" hidden ref={camera} accept="image/*" capture="environment" aria-label="Capture a photo" onChange={event => { add(event.currentTarget.files); event.currentTarget.value = ''; }}/>
    <Inline shouldWrap space="space.100"><Button onClick={() => camera.current?.click()}>Take photo</Button><Button onClick={() => picker.current?.click()}>Choose files</Button></Inline>
    {files.map((file, index) => <Inline key={`${file.name}-${index}`} spread="space-between" alignBlock="center" shouldWrap space="space.100"><Text size="small">{file.name}</Text><Button appearance="subtle" onClick={() => setFiles(files.filter((_, item) => item !== index))} aria-label={`Remove ${file.name}`}>Remove</Button></Inline>)}
    {error && <Box role="alert"><Text color="color.text.danger">{error}</Text></Box>}
  </Stack>;
}
function useSave(group: string, onSaved: (item: Complaint) => void) {
    const [busy, setBusy] = useState(false), [error, setError] = useState<unknown>(), [errors, setErrors] = useState<Record<string, string>>({});
    const pending = useRef(false), retry = useRef({ fingerprint: '', key: '' }), controller = useRef<AbortController | null>(null);
    useEffect(() => () => controller.current?.abort(), []);
    const save = async (path: string, values: Record<string, unknown>, files: File[] = []) => {
        if (pending.current)
            return;
        pending.current = true;
        setBusy(true);
        setError(undefined);
        setErrors({});
        const fingerprint = JSON.stringify([path, values, files.map(file => [file.name, file.size, file.lastModified])]);
        if (retry.current.fingerprint !== fingerprint)
            retry.current = { fingerprint, key: crypto.randomUUID() };
        const body = new FormData();
        Object.entries({ ...values, client_request_id: retry.current.key }).forEach(([key, value]) => body.set(key, String(value)));
        files.forEach(file => body.append('evidence', file));
        const request = new AbortController();
        controller.current = request;
        const timer = setTimeout(() => request.abort(), 30000);
        try {
            const result = await operation<{
                case: Complaint;
                publication_deferred?: boolean;
            }>(group, path, request.signal, body);
            // Canonical save is successful even if the follow-up publication fails.
            // Do not replay creation after a failed external projection.
            if (path === 'cases/create/' && result.publication_deferred) {
                void operation(group, `cases/${result.case.key}/finish-created/`, new AbortController().signal, { client_request_id: crypto.randomUUID(), creation_request_id: retry.current.key }).catch(() => { });
            }
            retry.current = { fingerprint: '', key: '' };
            if (!request.signal.aborted) onSaved(result.case);
        }
        catch (issue) {
            setError(issue);
            if (issue instanceof OperationError)
                setErrors(issue.fields);
        }
        finally {
            clearTimeout(timer);
            pending.current = false;
            setBusy(false);
        }
    };
    return { save, busy, error, errors, setErrors };
}
function CaseActions({ group, item, saved, voiceEnabled, markDirty }: {
    group: string;
    item: Detail;
    saved: (item: Complaint) => void;
    voiceEnabled: boolean;
    markDirty: (value: boolean) => void;
}) {
    const [action, setAction] = useState(''), [values, setValues] = useState<Record<string, string>>({}), [files, setFiles] = useState<File[]>([]);
    const [revision, setRevision] = useState(item.revision), [latest, setLatest] = useState<Detail>();
    useEffect(() => { markDirty(Boolean(Object.keys(values).length || files.length)); return () => markDirty(false); }, [values, files, markDirty]);
    const state = useSave(group, saved);
    const available = item.actions.filter(name => name in actionLabels && (name === 'retry-publication' ? ['failed', 'pending'].includes(item.sync_status) : name === 'complete-details' ? item.needs_details : name === 'reopen' ? item.status === 'CLOSED' : item.status !== 'CLOSED' && !item.needs_details));
    return <Stack space="space.150">
    {available.length > 0 && <Choice id="complaint-action" label="Update complaint" value={action} options={available.map(value => ({ value, label: actionLabels[value] }))} onChange={value => { if (!state.busy) {
        setAction(value);
        setValues({});
        setFiles([]);
        state.setErrors({});
    } }}/>}
    {action && <Form<Record<string, string>> key={action} onSubmit={() => {
                const required = action === 'complete-details' ? ['customer_phone', 'customer_id'] : action === 'retry-publication' ? [] : [action === 'comment' ? 'comment_text' : action === 'reopen' ? 'reason' : 'resolution_text'];
                const missing = Object.fromEntries(required.filter(name => !(values[name] || (name === 'customer_phone' ? item.customer_phone : name === 'customer_id' ? item.customer_id : '')).trim()).map(name => [name, 'Complete this field.']));
                if (Object.keys(missing).length) {
                    state.setErrors(missing);
                    return;
                }
                return state.save(`cases/${item.key}/${action}/`, { ...values, expected_revision: revision }, files);
            }}>{({ formProps }) => <Box as="form" {...formProps} noValidate><Stack space="space.150">
      <Feedback error={state.error}/>
      {state.error instanceof OperationError && state.error.status === 409 && <Button onClick={() => { void operation<{case: Detail}>(group, `cases/${item.key}/`, new AbortController().signal).then(result => { setRevision(result.case.revision); setLatest(result.case); }).catch(() => {}); }}>Review latest case</Button>}
      {latest && <Box role="status"><Text>Latest update: {latest.history[0]?.note || labelStatus(latest)}. Your entered text is retained. Review it before saving.</Text></Box>}
      {action === 'complete-details' ? <Grid xcss={styles.fields} gap="space.150">{[['customer_phone', 'Primary phone number'], ['customer_id', 'National ID']].map(([name, label]) => <Input key={name} name={name} label={label} values={{ customer_phone: item.customer_phone || '', customer_id: item.customer_id || '', ...values }} errors={state.errors} change={(key, value) => setValues(previous => ({ ...previous, [key]: value }))} required/>)}</Grid> : action !== 'retry-publication' && <Input name={action === 'comment' ? 'comment_text' : action === 'reopen' ? 'reason' : 'resolution_text'} label={action === 'comment' ? 'Resolution comment' : action === 'reopen' ? 'Reason for reopening' : 'Resolution note'} values={values} errors={state.errors} change={(key, value) => { setValues(previous => ({ ...previous, [key]: value })); state.setErrors({}); }} required/>}
      {voiceEnabled && ['resolve', 'comment', 'reopen'].includes(action) && <VoiceInput group={group} caseKey={item.key} field={action === 'comment' ? 'complaint_resolution_comment' : action === 'reopen' ? 'complaint_reopen_reason' : 'complaint_resolution_note'} accept={(text, id) => setValues(previous => ({ ...previous, [action === 'comment' ? 'comment_text' : action === 'reopen' ? 'reason' : 'resolution_text']: text, voice_transcription_id: id }))} />}
      {action === 'resolve' && <Files files={files} setFiles={setFiles}/>}
      <Inline shouldWrap space="space.100"><Button appearance="primary" type="submit" isLoading={state.busy}>{actionLabels[action]}</Button><Button isDisabled={state.busy} onClick={() => setAction('')}>Cancel</Button></Inline>
    </Stack></Box>}</Form>}
  </Stack>;
}
function Create({ group, bootstrap, onSaved, cancel, markDirty }: {
    group: string;
    bootstrap: Bootstrap;
    onSaved: (item: Complaint) => void;
    cancel: () => void;
    markDirty: (value: boolean) => void;
}) {
    const [values, setValues] = useState<Record<string, string>>({}), [files, setFiles] = useState<File[]>([]), [draftRevision, setDraftRevision] = useState(0), [draftKey, setDraftKey] = useState(''), [draftMessage, setDraftMessage] = useState('');
    const [draft, setDraft] = useState<{
        key: string;
        fields: Record<string, string>;
        revision: number;
    } | null>(null);
    useEffect(() => { markDirty(Boolean(Object.keys(values).length || files.length)); return () => markDirty(false); }, [values, files, markDirty]);
    const state = useSave(group, onSaved);
    const [locations, setLocations] = useState(bootstrap.location_options);
    useEffect(() => {
        const controller = new AbortController();
        void operation<{
            draft: {
                key: string;
                fields: Record<string, string>;
                revision: number;
            } | null;
        }>(group, 'draft/', controller.signal).then(result => { setDraft(result.draft); setDraftRevision(result.draft?.revision || 0); setDraftKey(result.draft?.key || ''); }).catch(() => setDraftMessage('Saved draft could not be checked. Your current entries are unaffected.'));
        return () => controller.abort();
    }, [group]);
    useEffect(() => {
        const controller = new AbortController();
        // POST is unnecessary for non-sensitive catalogue choices; names are sent as codes.
        const params = new URLSearchParams({ branch: values.branch_region || '', county: values.county || '' });
        void fetch(`/api/staff/complaints/operations/v1/groups/${group}/locations/?${params}`, { credentials: 'same-origin', mode: 'same-origin', cache: 'no-store', redirect: 'error', signal: controller.signal }).then(async (response) => { if (!response.ok)
            throw new Error(); return response.json() as Promise<Locations>; }).then(setLocations).catch(() => { });
        return () => controller.abort();
    }, [group, values.branch_region, values.county]);
    const change = (name: string, value: string) => { setValues(previous => ({ ...previous, [name]: value, ...(name === 'branch_region' ? { county: '', sub_county: '' } : name === 'county' ? { sub_county: '' } : {}) })); state.setErrors({}); };
    const saveDraft = async (discard = false) => {
        try {
            const result = await operation<{
                draft: {
                    key: string;
                    fields: Record<string, string>;
                    revision: number;
                } | null;
            }>(group, 'draft/', new AbortController().signal, discard ? { action: 'discard', key: draftKey, revision: draftRevision } : { fields: values, key: draftKey, revision: draftRevision });
            setDraft(result.draft);
            setDraftRevision(result.draft?.revision || 0); setDraftKey(result.draft?.key || '');
            setDraftMessage(discard ? 'Saved draft discarded.' : 'Draft saved.');
            if (!files.length) markDirty(false);
        }
        catch (error) {
            setDraftMessage(failure(error));
        }
    };
    return <Box xcss={styles.form}><Stack space="space.200"><Heading as="h2" size="medium">New complaint</Heading>
    {draft && <Inline shouldWrap space="space.100" alignBlock="center"><Text>A saved draft is available.</Text><Button onClick={() => { setValues(draft.fields); setDraft(null); setDraftMessage(files.length ? 'Draft restored.' : 'Draft restored. Select any photos or documents again if needed.'); }}>Restore</Button><Button appearance="danger" onClick={() => { void saveDraft(true); }}>Discard</Button></Inline>}
    {draftMessage && <Box role="status"><Text>{draftMessage}</Text></Box>}
    <Feedback error={state.error}/>
    <Form<Record<string, string>> onSubmit={() => {
            const required = ['client_name', 'customer_phone', 'customer_id', 'branch_region', 'county', 'sub_county', 'village', 'complaint_category', 'complaint_description'];
            const errors = Object.fromEntries(required.filter(name => !values[name]?.trim()).map(name => [name, 'Complete this field.']));
            if (values.customer_id && !/^\d+$/.test(values.customer_id))
                errors.customer_id = 'Use digits only.';
            if (values.customer_phone && !/^(?:\+?254|0)[17]\d{8}$/.test(values.customer_phone.replace(/[\s()-]/g, '')))
                errors.customer_phone = 'Enter a valid Kenyan mobile number.';
            if (Object.keys(errors).length) {
                state.setErrors(errors);
                return;
            }
            return state.save('cases/create/', { ...values, browser_draft_revision: String(draftRevision), browser_draft_key: draftKey }, files);
        }}>{({ formProps }) => <Box as="form" {...formProps} noValidate><Stack space="space.200">
      <Grid xcss={styles.fields} gap="space.150">{[['client_name', 'Customer name'], ['customer_id', 'National ID'], ['customer_phone', 'Primary phone number'], ['secondary_phone', 'Alternative phone number']].map(([name, label]) => <Input key={name} name={name} label={label} values={values} errors={state.errors} change={change} required={name !== 'secondary_phone'} type={name.includes('phone') ? 'tel' : 'text'}/>)}</Grid>
      <Grid xcss={styles.fields} gap="space.150">{[['branch_region', 'Branch', locations.branches], ['county', 'County', locations.counties], ['sub_county', 'Constituency', locations.sub_counties]].map(([name, label, options]) => <Stack key={String(name)} space="space.050"><Choice id={`create-${name}`} label={String(label)} value={values[String(name)] || ''} options={(options as Locations['branches']).map(item => ({ value: item.code, label: item.name }))} onChange={value => change(String(name), value)} error={state.errors[String(name)]}/></Stack>)}<Input name="village" label="Village/Nearest Landmark" values={values} errors={state.errors} change={change} required/></Grid>
      <Choice id="create-category" label="Complaint type" value={values.complaint_category || ''} options={bootstrap.categories.map(value => ({ value, label: value }))} onChange={value => change('complaint_category', value)} error={state.errors.complaint_category}/>
      <Input name="complaint_description" label="Complaint description" values={values} errors={state.errors} change={change} required/>
      <Inline shouldWrap space="space.100" alignBlock="center"><Button onClick={() => { navigator.geolocation?.getCurrentPosition(position => { change('latitude', position.coords.latitude.toFixed(6)); change('longitude', position.coords.longitude.toFixed(6)); setDraftMessage('Location captured.'); }, () => setDraftMessage('Location was not shared. You can continue without a map pin.')); }}>Use current location</Button>{values.latitude && <Text size="small">Location captured</Text>}</Inline>
      {bootstrap.voice_input?.enabled && <VoiceInput group={group} field="complaint_description" maxSeconds={bootstrap.voice_input.max_seconds} accept={(text, id) => { change('complaint_description', text); change('voice_transcription_id', id); }} />}
      <Files files={files} setFiles={setFiles}/>
      <Inline shouldWrap space="space.100"><Button appearance="primary" type="submit" isLoading={state.busy}>Submit complaint</Button><Button isDisabled={state.busy} onClick={() => { void saveDraft(); }}>Save draft</Button><Button isDisabled={state.busy} onClick={cancel}>Cancel</Button></Inline>
    </Stack></Box>}</Form>
  </Stack></Box>;
}
export function ComplaintsOperationsWorkspace({ signOut, recheck }: {
    signOut: () => void;
    recheck: () => void;
}) {
    const [route, setRoute] = useState<WorkspaceRoute>(readRoute), [groups, setGroups] = useState<Group[] | null>(null), [groupError, setGroupError] = useState<unknown>(), [refresh, setRefresh] = useState(0), [query, setQuery] = useState(''), [typedQuery, setTypedQuery] = useState(''), [branch, setBranch] = useState(''), [category, setCategory] = useState(''), [notice, setNotice] = useState('');
    const [settingsOpen, setSettingsOpen] = useState(false);
    const detailPanel = useRef<HTMLDivElement>(null);
    const dirty = useRef(false);
    const routeRef = useRef(route); routeRef.current = route;
    const markDirty = React.useCallback((value: boolean) => { dirty.current = value; }, []);
    useEffect(() => { const warn = (event: BeforeUnloadEvent) => { if (dirty.current) { event.preventDefault(); event.returnValue = ''; } }; window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn); }, []);
    const callbacks = useRef({ recheck });
    callbacks.current = { recheck };
    const navigate = (next: WorkspaceRoute, replace = false) => { if (dirty.current && !window.confirm('Leave this form? Unsaved entries will be lost.')) return; dirty.current = false; writeRoute(next, replace); setRoute(next); };
    useEffect(() => { const listener = () => { if (dirty.current && !window.confirm('Leave this form? Unsaved entries will be lost.')) { writeRoute(routeRef.current, true); return; } dirty.current = false; setRoute(readRoute()); }; window.addEventListener('popstate', listener); return () => window.removeEventListener('popstate', listener); }, []);
    useEffect(() => { document.title = 'Complaints - JBL staff workspace'; setGroupError(undefined); const controller = new AbortController(); void loadGroups(controller.signal).then(result => { setGroups(result.groups); setRoute(previous => { const group = result.groups.some(item => item.key === previous.group) ? previous.group : result.groups[0]?.key || ''; const next = { ...previous, group }; writeRoute(next, true); return next; }); }).catch(error => { if (!controller.signal.aborted)
        setGroupError(error); }); return () => controller.abort(); }, [refresh]);
    const bootstrap = useRead<Bootstrap>(route.group, 'bootstrap/', refresh);
    const queue = useRead<Queue>(route.view === 'queue' ? route.group : '', 'cases/', refresh, { q: query, status: route.status, branch, category, page: route.page });
    const detail = useRead<{
        case: Detail;
    }>(route.view === 'queue' && route.selected ? route.group : '', `cases/${route.selected}/`, refresh);
    useEffect(() => { if (detail.data && window.matchMedia('(max-width: 63.99rem)').matches) requestAnimationFrame(() => { detailPanel.current?.scrollIntoView({ block: 'start' }); detailPanel.current?.focus({ preventScroll: true }); }); }, [detail.data]);
    const error = groupError || bootstrap.error || queue.error || detail.error;
    useEffect(() => { if (error instanceof OperationError && error.status === 401)
        callbacks.current.recheck(); }, [error]);
    const saved = (item: Complaint) => { dirty.current = false; setNotice(`${item.reference}: changes saved.`); navigate({ ...route, view: 'queue', selected: item.key }); setRefresh(value => value + 1); };
    const capabilities = bootstrap.data?.actor.capabilities || [];
    return <Root><TopNav><TopNavStart sideNavToggleButton={null}><Text weight="bold">JBL Staff workspace</Text></TopNavStart><TopNavMiddle>{null}</TopNavMiddle><TopNavEnd><Button appearance="subtle" onClick={signOut}>Sign out</Button></TopNavEnd></TopNav>
    <Main><Box xcss={styles.page} testId="complaints-operations-content"><Stack space="space.200">
      <Inline alignBlock="center" spread="space-between" shouldWrap space="space.100"><Heading as="h1" size="large">Complaints</Heading><Inline shouldWrap space="space.100"><Button isSelected={route.view === 'queue'} onClick={() => navigate({ ...route, view: 'queue' })}>Cases</Button>{capabilities.includes('complaint.reports.view') && <Button isSelected={route.view === 'reports'} onClick={() => navigate({ ...route, view: 'reports' })}>Reports</Button>}{capabilities.includes('complaint.case.create') && <Button appearance="primary" onClick={() => navigate({ ...route, view: 'new' })}>New complaint</Button>}<Button onClick={() => setSettingsOpen(value => !value)}>Settings</Button><Button onClick={() => { if (!dirty.current || window.confirm('Refresh this workspace? Unsaved entries will be lost.')) { dirty.current = false; setRefresh(value => value + 1); } }}>Refresh</Button></Inline></Inline>
      {groups && groups.length > 1 && <Choice id="workspace" label="Workspace" value={route.group} options={groups.map(item => ({ value: item.key, label: item.label }))} onChange={group => { setQuery(''); setTypedQuery(''); setBranch(''); setCategory(''); navigate({ ...route, group, page: 1, selected: '' }); }}/>}
      {groups?.length === 0 && <SectionMessage title="No Complaints access" headingLevel="h2"><Text as="p">Contact your administrator if you need access to this workspace.</Text></SectionMessage>}
      {notice && <Box role="status"><Text weight="medium">{notice}</Text></Box>}<Feedback error={error}/>
      {!bootstrap.data && !error && groups?.length !== 0 && <Box role="status"><Text>Loading workspace...</Text></Box>}
      {bootstrap.data && settingsOpen && <Box xcss={styles.panel}><WorkspaceSettings group={route.group} close={() => setSettingsOpen(false)} select={selected => { setSettingsOpen(false); navigate({ ...route, view: 'queue', selected }); }} /></Box>}
      {bootstrap.data && route.view === 'new' && <Create key={route.group} group={route.group} bootstrap={bootstrap.data} onSaved={saved} cancel={() => navigate({ ...route, view: 'queue' })} markDirty={markDirty}/>}
      {bootstrap.data && route.view === 'reports' && <Reports group={route.group} refresh={refresh}/>}
      {bootstrap.data && route.view === 'queue' && <>
        <Form onSubmit={() => { setQuery(typedQuery.trim()); navigate({ ...route, page: 1, selected: '' }); }}>{({ formProps }) => <Box as="form" {...formProps} noValidate><Grid xcss={styles.filters} gap="space.150"><Box><Label htmlFor="search">Search name, ID, phone or branch</Label><Textfield id="search" value={typedQuery} onChange={event => setTypedQuery(event.currentTarget.value)}/></Box><Choice id="status" label="Status" value={route.status} options={statuses} onChange={status => navigate({ ...route, status, page: 1, selected: '' })}/>{[['branch', 'Branch', queue.data?.filter_options.branches, branch, setBranch], ['category', 'Complaint type', queue.data?.filter_options.categories, category, setCategory]].map(([id, label, options, value, setter]) => <Choice key={String(id)} id={String(id)} label={String(label)} value={String(value)} options={[{ value: '', label: 'All' }, ...((options || []) as {
                label: string;
            }[]).map(item => ({ value: item.label, label: item.label }))]} onChange={value => { (setter as (value: string) => void)(value); navigate({ ...route, page: 1, selected: '' }); }}/>)}<Button type="submit">Search</Button></Grid></Box>}</Form>
        <Grid xcss={styles.columns} gap="space.200"><Box as="section" aria-label="Complaint queue" xcss={styles.panel}><Stack space="space.100"><Heading as="h2" size="small">{queue.data ? `${queue.data.pagination.total} cases` : 'Cases'}</Heading>{queue.data?.items.map((item, index) => <Box key={item.key} xcss={styles.row}><Stack space="space.050"><Inline alignBlock="center" shouldWrap space="space.100"><Text size="small" color="color.text.subtle">{(queue.data!.pagination.page - 1) * 10 + index + 1}.</Text><Button appearance="subtle" isSelected={route.selected === item.key} onClick={() => navigate({ ...route, selected: item.key })}>{item.customer_name || item.reference}</Button><Text size="small">{labelStatus(item)}</Text></Inline><Text size="small" color="color.text.subtle">{[item.reference, item.branch, item.category, item.age_label].filter(Boolean).join(' · ')}</Text></Stack></Box>)}{queue.data?.items.length === 0 && <Text>No complaints match these filters.</Text>}{!queue.data && !queue.error && <Box role="status"><Text>Loading complaints...</Text></Box>}{queue.data && <Inline spread="space-between" shouldWrap space="space.100"><Text size="small">Page {queue.data.pagination.page} of {queue.data.pagination.pages}</Text><Inline space="space.050"><Button isDisabled={queue.data.pagination.page <= 1} onClick={() => navigate({ ...route, page: route.page - 1, selected: '' })}>Previous</Button><Button isDisabled={queue.data.pagination.page >= queue.data.pagination.pages} onClick={() => navigate({ ...route, page: route.page + 1, selected: '' })}>Next</Button></Inline></Inline>}</Stack></Box>
        <Box as="section" aria-label="Case detail" xcss={styles.panel} ref={detailPanel} tabIndex={-1}>{detail.data ? <Stack space="space.200"><Inline shouldWrap spread="space-between" space="space.100"><Heading as="h2" size="medium">{detail.data.case.customer_name || detail.data.case.reference}</Heading><Text weight="medium">{labelStatus(detail.data.case)}</Text></Inline><Grid xcss={styles.facts} gap="space.150">{[['Reference', detail.data.case.reference], ['National ID', detail.data.case.customer_id], ['Phone', detail.data.case.customer_phone], ['Branch', detail.data.case.branch], ['Complaint type', detail.data.case.category], ['Reported (Nairobi)', detail.data.case.reported_at]].map(([label, value]) => <Stack key={label} space="space.050"><Text size="small" color="color.text.subtle">{label}</Text>{label === 'Phone' && value ? <Anchor href={`tel:${value}`}>{value}</Anchor> : <Text>{value || 'Not provided'}</Text>}</Stack>)}</Grid><Box xcss={styles.prewrap}><Text as="p">{detail.data.case.description}</Text></Box><CaseActions key={`${detail.data.case.key}-${detail.data.case.revision}`} group={route.group} item={detail.data.case} saved={saved} voiceEnabled={Boolean(bootstrap.data.voice_input?.enabled)} markDirty={markDirty}/><Stack space="space.100"><Heading as="h3" size="small">Photos and documents</Heading>{detail.data.case.evidence.length === 0 && <Text size="small" color="color.text.subtle">No documents available.</Text>}{detail.data.case.evidence.map(item => <Inline key={item.id} shouldWrap space="space.100"><EvidencePreview group={route.group} id={item.id} name={item.name} type={item.mime_type} /><Button onClick={() => { void download(route.group, `evidence/${item.id}/?download=1`).catch(error => setNotice(failure(error))); }}>Download</Button></Inline>)}</Stack><Stack space="space.150"><Heading as="h3" size="small">Activity</Heading>{detail.data.case.history.map((row, index) => <Box key={index} xcss={styles.row}><Stack space="space.050"><Text weight="medium">{historyLabels[row.action] || 'Complaint updated'}</Text><Text size="small" color="color.text.subtle">{[row.updated_by, row.actor_affiliation, row.created_at].filter(Boolean).join(' · ')}</Text>{row.note && <Box xcss={styles.prewrap}><Text as="p">{row.note}</Text></Box>}</Stack></Box>)}</Stack></Stack> : <Text>{route.selected ? 'Loading complaint...' : 'Select a complaint to view its details.'}</Text>}</Box></Grid>
      </>}
    </Stack></Box></Main></Root>;
}
