import React, { useEffect, useRef, useState } from 'react';
import Button from '@atlaskit/button/default/button';
import { IconButton } from '@atlaskit/button/new';
import SettingsIcon from '@atlaskit/icon/core/settings';
import RefreshIcon from '@atlaskit/icon/core/refresh';
import Tabs, { Tab, TabList, TabPanel } from '@atlaskit/tabs';
import { Anchor } from '@atlaskit/primitives/compiled/anchor';
import { Reports } from './complaints-operations-reports';
import { EvidencePreview, VoiceInput } from './complaints-operations-media';
import { WorkspaceSettings } from './complaints-operations-settings';
import { Activity } from './complaints-operations-history';
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
import { readRoute, writeRoute, initialQueuePreferences, historyPosition, type WorkspaceRoute } from './workspace-navigation';
import { TaskDialog, ComplaintStatus, displayDate, complaintCount } from './complaints-ui';
import { WorkspaceRecovery, useRetainedValue, type RecoverySlot, type Submission } from './workspace-recovery';
const SessionRecheck = React.createContext<() => void>(() => {});
const LockedForm = React.createContext(false);
const styles = cssMap({
    full: { width: '100%', minWidth: 0 },
    page: { width: '100%', maxWidth: '80rem', marginInline: 'auto', boxSizing: 'border-box', padding: token('space.200'), '@media (min-width: 64rem)': { padding: token('space.300') } },
    columns: { gridTemplateColumns: 'repeat(1, minmax(0, 1fr))', alignItems: 'start', '@media (min-width: 64rem)': { gridTemplateColumns: 'minmax(20rem, 24rem) minmax(0, 1fr)' } },
    selectedRow: { backgroundColor: token('color.background.selected'), borderRadius: token('radius.medium') },
    mobileList: { display: 'none', '@media (min-width: 64rem)': { display: 'block' } },
    mobileOnly: { '@media (min-width: 64rem)': { display: 'none' } },
    itemLink: { display: 'block', padding: token('space.150'), color: token('color.text'), textDecoration: 'none', borderRadius: token('radius.medium'), '&:hover': { backgroundColor: token('color.background.neutral.subtle.hovered'), textDecoration: 'none' } },
    panel: { minWidth: 0, padding: token('space.200'), borderStyle: 'solid', borderWidth: token('border.width'), borderColor: token('color.border'), borderRadius: token('radius.medium'), overflowWrap: 'anywhere' },
    row: { minWidth: 0, paddingBlock: token('space.100'), borderBlockEndWidth: token('border.width'), borderBlockEndStyle: 'solid', borderBlockEndColor: token('color.border'), overflowWrap: 'anywhere' },
    fields: { gridTemplateColumns: 'repeat(1, minmax(0, 1fr))', '@media (min-width: 48rem)': { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' } },
    filters: { gridTemplateColumns: 'repeat(1, minmax(0, 1fr))', alignItems: 'end', '@media (min-width: 48rem)': { gridTemplateColumns: 'minmax(15rem, 2fr) repeat(3, minmax(8rem, 1fr))' } },
    prewrap: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' },
    textarea: { width: '100%', boxSizing: 'border-box', padding: token('space.100'), borderStyle: 'solid', borderWidth: token('border.width'), borderColor: token('color.border.input'), borderRadius: token('radius.small'), backgroundColor: token('color.background.input'), color: token('color.text'), font: token('font.body'), resize: 'vertical' },
    form: { width: '100%', maxWidth: '42rem', marginInline: 'auto' },
    camera: { '@media (min-width: 64rem)': { display: 'none' } },
});
const statuses = [{ value: 'pending', label: 'Open + Reopened' }, { value: 'resolved', label: 'Closed' }, { value: 'all', label: 'All complaints' }];
const actionLabels: Record<string, string> = { resolve: 'Resolve complaint', comment: 'Add resolution comment', reopen: 'Reopen complaint', 'complete-details': 'Complete missing details', 'retry-publication': 'Retry publication' };
function labelStatus(item: Complaint) { return item.needs_details ? 'Needs details' : item.status === 'CLOSED' ? 'Closed' : item.status === 'REOPENED' ? 'Reopened' : 'Open'; }
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
}) {
    const recheck = React.useContext(SessionRecheck);
    return error ? <Box role="alert"><SectionMessage appearance="error" title="Action could not be completed" headingLevel="h2"><Text as="p">{failure(error)}</Text>{error instanceof OperationError && error.status === 401 && <Button onClick={recheck}>Sign in again</Button>}</SectionMessage></Box> : null;
}
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
    const locked = React.useContext(LockedForm);
    return <Box><Label htmlFor={id}>{label}</Label><Select isDisabled={locked} inputId={id} aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : undefined} options={options} value={options.find(option => option.value === value) || null} onChange={option => onChange(option?.value || '')}/>{error && <Box id={`${id}-error`} role="alert"><Text color="color.text.danger">{error}</Text></Box>}</Box>;
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
    const locked = React.useContext(LockedForm);
    if (name.includes('description') || name.includes('text') || name === 'reason') return <Field<string, HTMLTextAreaElement> name={name} label={label} isRequired={required} defaultValue={values[name] || ''}>{({ fieldProps }) => <><Box as="textarea" readOnly={locked} {...fieldProps} xcss={styles.textarea} rows={4} value={values[name] || ''} aria-invalid={Boolean(errors[name])} aria-describedby={errors[name] ? `${fieldProps.id}-server-error` : fieldProps['aria-describedby']} onChange={event => { fieldProps.onChange(event); change(name, event.currentTarget.value); }} /><MessageWrapper>{errors[name] && <Box id={`${fieldProps.id}-server-error`}><ErrorMessage>{errors[name]}</ErrorMessage></Box>}</MessageWrapper></>}</Field>;
    // eslint-disable-next-line @atlaskit/design-system/no-readonly-or-disabled-inputs -- Briefly freeze the exact uncertain submission; the visible retry message explains recovery.
    return <Field<string> name={name} label={label} isRequired={required} defaultValue={values[name] || ''}>{({ fieldProps }) => <><Textfield isReadOnly={locked} {...fieldProps} aria-describedby={errors[name] ? `${fieldProps.id}-server-error` : fieldProps['aria-describedby']} value={values[name] || ''} type={type} isInvalid={Boolean(errors[name])} onChange={event => { fieldProps.onChange(event); change(name, event.currentTarget.value); }} autoComplete={name.includes('phone') ? 'tel' : name === 'client_name' ? 'name' : 'off'}/><MessageWrapper>{errors[name] && <Box id={`${fieldProps.id}-server-error`}><ErrorMessage>{errors[name]}</ErrorMessage></Box>}</MessageWrapper></>}</Field>;
}
function Files({ files, setFiles }: {
    files: File[];
    setFiles: (value: File[]) => void;
}) {
    const locked = React.useContext(LockedForm);
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
    return <Stack space="space.100"><Text weight="medium">Attachments</Text><Text size="small" color="color.text.subtle">Images or PDF · up to 10 files · 10 MB each, 30 MB total</Text>
    <Box as="input" type="file" hidden ref={picker} multiple accept=".jpg,.jpeg,.png,.webp,.pdf" aria-label="Choose evidence files" onChange={event => { add(event.currentTarget.files); event.currentTarget.value = ''; }}/>
    <Box as="input" type="file" hidden ref={camera} accept="image/*" capture="environment" aria-label="Capture a photo" onChange={event => { add(event.currentTarget.files); event.currentTarget.value = ''; }}/>
    <Inline shouldWrap space="space.100"><Box xcss={styles.camera}><Button isDisabled={locked} onClick={() => camera.current?.click()}>Take photo</Button></Box><Button isDisabled={locked} onClick={() => picker.current?.click()}>Attach files</Button></Inline>
    {files.map((file, index) => <Inline key={`${file.name}-${index}`} spread="space-between" alignBlock="center" shouldWrap space="space.100"><Text size="small">{file.name}</Text><Button isDisabled={locked} appearance="subtle" onClick={() => setFiles(files.filter((_, item) => item !== index))} aria-label={`Remove ${file.name}`}>Remove</Button></Inline>)}
    {error && <Box role="alert"><Text color="color.text.danger">{error}</Text></Box>}
  </Stack>;
}
function useSave(group: string, onSaved: (item: Complaint) => void, slot: RecoverySlot) {
    const [busy, setBusy] = useState(false), [error, setError] = useState<unknown>(), [errors, setErrors] = useState<Record<string, string>>({});
    const [uncertain, setUncertain] = useState(Boolean(slot.read().submission));
    const pending = useRef(false), controller = useRef<AbortController | null>(null), active = useRef(true);
    const onSavedRef = useRef(onSaved); onSavedRef.current = onSaved;
    useEffect(() => {
        active.current = true;
        const confirmed = slot.read().confirmed as Complaint | undefined;
        if (confirmed) { slot.patch({ confirmed: undefined }); onSavedRef.current(confirmed); }
        return () => { active.current = false; controller.current?.abort(); };
    }, []);
    const execute = async (submission: Submission) => {
        if (pending.current) return;
        if (!navigator.onLine) { setError(new OperationError(0, 'You are offline. Your entries are still here. Reconnect before saving.')); return; }
        const previousAttempt = Boolean(slot.read().submission);
        pending.current = true; setBusy(true); setError(undefined); setErrors({});
        // Record before dispatch. Unmount/expiry can race a committed response.
        slot.patch({ submission });
        const body = new FormData();
        Object.entries({ ...submission.values, client_request_id: submission.key }).forEach(([key, value]) => body.set(key, String(value)));
        submission.files.forEach(file => body.append('evidence', file));
        const request = new AbortController();
        controller.current = request;
        const timer = setTimeout(() => request.abort(), 30000);
        try {
            const result = await operation<{
                case: Complaint;
                publication_deferred?: boolean;
            }>(group, submission.path, request.signal, body);
            // Canonical save is successful even if the follow-up publication fails.
            // Do not replay creation after a failed external projection.
            if (submission.path === 'cases/create/' && result.publication_deferred) {
                const finish = new AbortController(), timeout = setTimeout(() => finish.abort(), 30000);
                void operation(group, `cases/${result.case.key}/finish-created/`, finish.signal, { client_request_id: submission.key, creation_request_id: submission.key }).catch(() => {}).finally(() => clearTimeout(timeout));
            }
            slot.patch({ submission: undefined, confirmed: result.case });
            if (active.current) { setUncertain(false); onSaved(result.case); }
        }
        catch (issue) {
            const rejected = !previousAttempt && issue instanceof OperationError && [400, 401, 403, 409, 413, 422, 429].includes(issue.status);
            if (rejected) slot.patch({ submission: undefined });
            if (active.current) { setUncertain(!rejected); setError(issue); if (issue instanceof OperationError) setErrors(issue.fields); }
        }
        finally {
            clearTimeout(timer);
            pending.current = false;
            if (active.current) setBusy(false);
        }
    };
    const save = (path: string, values: Record<string, unknown>, files: File[] = []) => {
        if (slot.read().submission) return;
        return execute({ path, values: { ...values }, files: [...files], key: crypto.randomUUID() });
    };
    const retry = () => { const submission = slot.read().submission as Submission | undefined; if (submission) return execute(submission); };
    const abandon = () => { slot.patch({ submission: undefined }); setUncertain(false); setError(undefined); };
    return { save, retry, abandon, busy, uncertain, error, errors, setErrors };
}
function PreviousSave({ state, leave }: { state: ReturnType<typeof useSave>; leave: () => void }) {
    const recheck = React.useContext(SessionRecheck), message = useRef<HTMLDivElement>(null);
    useEffect(() => { if (state.uncertain) { message.current?.scrollIntoView({ block: 'nearest' }); message.current?.focus({ preventScroll: true }); } }, [state.uncertain]);
    return state.uncertain ? <Box ref={message} role="alert" tabIndex={-1}><SectionMessage appearance="warning" title="Check the previous save" headingLevel="h3"><Text as="p">It may already be saved. Retry the same update to confirm before making changes.</Text><Inline shouldWrap space="space.100">{state.error instanceof OperationError && state.error.status === 401 && <Button onClick={recheck}>Sign in again</Button>}<Button isLoading={state.busy} onClick={() => { void state.retry(); }}>Retry previous save</Button><Button isDisabled={state.busy} appearance="subtle" onClick={() => { if (window.confirm('The previous save may already have completed. Leave this form and check the complaint list before submitting again?')) { state.abandon(); leave(); } }}>Leave without checking</Button></Inline></SectionMessage></Box> : null;
}
function CaseActions({ group, item, saved, voiceEnabled, markDirty, slot }: {
    group: string;
    item: Detail;
    saved: (item: Complaint) => void;
    voiceEnabled: boolean;
    markDirty: (value: boolean, pending?: boolean) => void;
    slot: RecoverySlot;
}) {
    const [action, setAction] = useRetainedValue(slot, 'action', ''), [values, setValues] = useRetainedValue<Record<string, string>>(slot, 'values', {}), [files, setFiles] = useRetainedValue<File[]>(slot, 'files', []);
    const [revision, setRevision] = useRetainedValue(slot, 'revision', item.revision), [latest, setLatest] = useState<Detail>();
    const state = useSave(group, saved, slot);
    useEffect(() => { markDirty(Boolean(Object.keys(values).length || files.length || state.busy || state.uncertain), state.busy || state.uncertain); return () => markDirty(false); }, [values, files, state.busy, state.uncertain, markDirty]);
    const available = item.actions.filter(name => name in actionLabels && (name === 'retry-publication' ? ['failed', 'pending'].includes(item.sync_status) : name === 'complete-details' ? item.needs_details : name === 'reopen' ? item.status === 'CLOSED' : item.status !== 'CLOSED' && !item.needs_details));
    return <Stack space="space.150">
    <Inline shouldWrap space="space.100">{available.map(name => <Button key={name} isDisabled={state.busy || state.uncertain} onClick={() => { setRevision(item.revision); setAction(name); setValues({}); setFiles([]); state.setErrors({}); }}>{actionLabels[name]}</Button>)}</Inline>
    {action && <TaskDialog title={actionLabels[action]} compact close={() => { if (!state.busy && !state.uncertain && (!(Object.keys(values).length || files.length) || window.confirm('Discard this unfinished update?'))) { setAction(''); setValues({}); setFiles([]); } }}>
    {action && <LockedForm.Provider value={state.busy || state.uncertain}><Form<Record<string, string>> key={action} onSubmit={() => {
                const required = action === 'complete-details' ? ['customer_phone', 'customer_id'] : action === 'retry-publication' ? [] : [action === 'comment' ? 'comment_text' : action === 'reopen' ? 'reason' : 'resolution_text'];
                const missing = Object.fromEntries(required.filter(name => !(values[name] || (name === 'customer_phone' ? item.customer_phone : name === 'customer_id' ? item.customer_id : '')).trim()).map(name => [name, 'Complete this field.']));
                if (Object.keys(missing).length) {
                    state.setErrors(missing);
                    return;
                }
                return state.save(`cases/${item.key}/${action}/`, { ...values, expected_revision: revision }, files);
            }}>{({ formProps }) => <Box as="form" {...formProps} noValidate><Stack space="space.150">
      <Feedback error={state.uncertain ? undefined : state.error}/><PreviousSave state={state} leave={() => { markDirty(false); setAction(''); setValues({}); setFiles([]); }}/>
      {state.error instanceof OperationError && state.error.status === 409 && <Button onClick={() => { void operation<{case: Detail}>(group, `cases/${item.key}/`, new AbortController().signal).then(result => { setRevision(result.case.revision); setLatest(result.case); }).catch(() => {}); }}>Review latest case</Button>}
      {latest && <Box role="status"><Text>Latest update: {latest.history[0]?.note || labelStatus(latest)}. Your entered text is retained. Review it before saving.</Text></Box>}
      {action === 'complete-details' ? <Grid xcss={styles.fields} gap="space.150">{[['customer_phone', 'Primary phone number'], ['customer_id', 'National ID']].map(([name, label]) => <Input key={name} name={name} label={label} values={{ customer_phone: item.customer_phone || '', customer_id: item.customer_id || '', ...values }} errors={state.errors} change={(key, value) => setValues(previous => ({ ...previous, [key]: value }))} required/>)}</Grid> : action !== 'retry-publication' && <Input name={action === 'comment' ? 'comment_text' : action === 'reopen' ? 'reason' : 'resolution_text'} label={action === 'comment' ? 'Resolution comment' : action === 'reopen' ? 'Reason for reopening' : 'Resolution note'} values={values} errors={state.errors} change={(key, value) => { setValues(previous => ({ ...previous, [key]: value })); state.setErrors({}); }} required/>}
      {!state.busy && !state.uncertain && voiceEnabled && ['resolve', 'comment', 'reopen'].includes(action) && <VoiceInput group={group} caseKey={item.key} field={action === 'comment' ? 'complaint_resolution_comment' : action === 'reopen' ? 'complaint_reopen_reason' : 'complaint_resolution_note'} accept={(text, id) => setValues(previous => ({ ...previous, [action === 'comment' ? 'comment_text' : action === 'reopen' ? 'reason' : 'resolution_text']: text, voice_transcription_id: id }))} />}
      {action === 'resolve' && <Files files={files} setFiles={setFiles}/>}
      <Inline shouldWrap space="space.100"><Button appearance="primary" type="submit" isLoading={state.busy} isDisabled={state.uncertain}>{actionLabels[action]}</Button><Button isDisabled={state.busy || state.uncertain} onClick={() => { setAction(''); setValues({}); setFiles([]); }}>Cancel</Button></Inline>
    </Stack></Box>}</Form></LockedForm.Provider>}</TaskDialog>}
  </Stack>;
}
function Create({ group, bootstrap, onSaved, cancel, markDirty, slot }: {
    group: string;
    bootstrap: Bootstrap;
    onSaved: (item: Complaint) => void;
    cancel: () => void;
    markDirty: (value: boolean, pending?: boolean) => void;
    slot: RecoverySlot;
}) {
    const [values, setValues] = useRetainedValue<Record<string, string>>(slot, 'values', {}), [files, setFiles] = useRetainedValue<File[]>(slot, 'files', []), [draftRevision, setDraftRevision] = useRetainedValue(slot, 'draftRevision', 0), [draftKey, setDraftKey] = useRetainedValue(slot, 'draftKey', ''), [draftMessage, setDraftMessage] = useState('');
    const [draft, setDraft] = useState<{
        key: string;
        fields: Record<string, string>;
        revision: number;
    } | null>(null);
    const state = useSave(group, onSaved, slot);
    const [draftBusy, setDraftBusy] = useState(false);
    const [draftError, setDraftError] = useState<unknown>();
    const [savedDraftValues, setSavedDraftValues] = useRetainedValue(slot, 'savedDraftValues', '{}');
    const draftPending = useRef(false);
    const draftRequest = useRef<AbortController | null>(null);
    useEffect(() => () => draftRequest.current?.abort(), []);
    const locked = state.busy || state.uncertain || draftBusy;
    useEffect(() => { markDirty(Boolean(JSON.stringify(values) !== savedDraftValues || files.length || locked), locked); return () => markDirty(false); }, [values, files, locked, savedDraftValues, markDirty]);
    const [locations, setLocations] = useState(bootstrap.location_options);
    useEffect(() => {
        const controller = new AbortController();
        void operation<{
            draft: {
                key: string;
                fields: Record<string, string>;
                revision: number;
            } | null;
        }>(group, 'draft/', controller.signal).then(result => { setDraft(result.draft); if (!slot.read().draftKey) { setDraftRevision(result.draft?.revision || 0); setDraftKey(result.draft?.key || ''); } }).catch(() => setDraftMessage('Saved draft could not be checked. Your current entries are unaffected.'));
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
        if (draftPending.current || locked) return;
        if (!navigator.onLine) { setDraftError(new OperationError(0, 'You are offline. Reconnect before saving your draft.')); return; }
        draftPending.current = true; setDraftBusy(true); setDraftError(undefined); setDraftMessage('');
        const request = new AbortController(); draftRequest.current = request;
        const timeout = setTimeout(() => request.abort(), 30000);
        try {
            const current = await operation<{draft: typeof draft}>(group, 'draft/', request.signal);
            if ((current.draft?.key || '') !== draftKey || (current.draft?.revision || 0) !== draftRevision) {
                setDraft(current.draft); setDraftRevision(current.draft?.revision || 0); setDraftKey(current.draft?.key || '');
                const fields = Object.fromEntries(Object.entries(values).filter(([key]) => !['voice_transcription_id', 'category_inference_token'].includes(key)));
                const same = current.draft && JSON.stringify(Object.entries(current.draft.fields).sort()) === JSON.stringify(Object.entries(fields).sort());
                if (discard && !current.draft) setDraftMessage('Saved draft discarded.');
                else if (!discard && same) { setSavedDraftValues(JSON.stringify(values)); setDraftMessage('Draft saved.'); }
                else setDraftMessage('Your saved draft changed. Review it before saving again. Your current entries are still here.');
                return;
            }
            const result = await operation<{
                draft: {
                    key: string;
                    fields: Record<string, string>;
                    revision: number;
                } | null;
            }>(group, 'draft/', request.signal, discard ? { action: 'discard', key: draftKey, revision: draftRevision } : { fields: values, key: draftKey, revision: draftRevision });
            setDraft(result.draft);
            setDraftRevision(result.draft?.revision || 0); setDraftKey(result.draft?.key || '');
            setDraftMessage(discard ? 'Saved draft discarded.' : 'Draft saved.');
            if (!discard) setSavedDraftValues(JSON.stringify(values));
        }
        catch (error) {
            setDraftError(error);
        }
        finally { clearTimeout(timeout); draftPending.current = false; setDraftBusy(false); }
    };
    return <LockedForm.Provider value={locked}><Box xcss={styles.form}><Stack space="space.200">
    {draft && <Inline shouldWrap space="space.100" alignBlock="center"><Text>A saved draft is available.</Text><Button isDisabled={locked} onClick={() => { if (Object.keys(values).length && !window.confirm('Replace the current entries with your saved draft?')) return; setValues(draft.fields); setSavedDraftValues(JSON.stringify(draft.fields)); setDraft(null); setDraftMessage('Draft restored.'); }}>Restore</Button><Button appearance="danger" isDisabled={locked} onClick={() => { if (window.confirm('Discard the saved draft?')) void saveDraft(true); }}>Discard</Button></Inline>}
    {draftMessage && <Box role="status"><Text>{draftMessage}</Text></Box>}
    <Feedback error={state.uncertain ? undefined : state.error || draftError}/><PreviousSave state={state} leave={() => { markDirty(false); cancel(); }}/>
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
      <Inline shouldWrap space="space.100" alignBlock="center"><Button isDisabled={locked} onClick={() => { navigator.geolocation?.getCurrentPosition(position => { change('latitude', position.coords.latitude.toFixed(6)); change('longitude', position.coords.longitude.toFixed(6)); setDraftMessage('Location captured.'); }, () => setDraftMessage('Location was not shared. You can continue without a map pin.')); }}>Use current location</Button>{values.latitude && <Text size="small">Location captured</Text>}</Inline>
      {!locked && bootstrap.voice_input?.enabled && <VoiceInput group={group} field="complaint_description" maxSeconds={bootstrap.voice_input.max_seconds} accept={(text, id) => { change('complaint_description', text); change('voice_transcription_id', id); }} />}
      <Files files={files} setFiles={setFiles}/>
      <Inline shouldWrap space="space.100"><Button appearance="primary" type="submit" isLoading={state.busy} isDisabled={state.uncertain || draftBusy}>Submit complaint</Button><Button isLoading={draftBusy} isDisabled={locked} onClick={() => { void saveDraft(); }}>Save draft</Button><Button isDisabled={locked} onClick={cancel}>Cancel</Button></Inline>
    </Stack></Box>}</Form>
  </Stack></Box></LockedForm.Provider>;
}
export function ComplaintsOperationsWorkspace({ signOut, recheck, recovery }: { signOut: () => void; recheck: () => void; recovery: WorkspaceRecovery }) {
  const [route, setRoute] = useState<WorkspaceRoute>(readRoute), [groups, setGroups] = useState<Group[] | null>(null), [groupError, setGroupError] = useState<unknown>(), [refresh, setRefresh] = useState(0);
  const [query, setQuery] = useState(''), [typedQuery, setTypedQuery] = useState(''), [branch, setBranch] = useState(''), [category, setCategory] = useState(''), [notice, setNotice] = useState('');
  const [ownerReady, setOwnerReady] = useState(''), [online, setOnline] = useState(navigator.onLine);
  const [syncOpen, setSyncOpen] = useState(false), [preferencesReady, setPreferencesReady] = useState(false);
  const entryUrl = useRef(window.location.href), appliedPreferences = useRef(false), detailPanel = useRef<HTMLDivElement>(null), dirty = useRef(false), pendingSave = useRef(false);
  const acceptedPosition = useRef(historyPosition()), undoPop = useRef(false);
  const routeRef = useRef(route); routeRef.current = route;
  const markDirty = React.useCallback((value: boolean, pending = false) => { dirty.current = value; pendingSave.current = pending; }, []);
  useEffect(() => { const update = () => setOnline(navigator.onLine); window.addEventListener('online', update); window.addEventListener('offline', update); return () => { window.removeEventListener('online', update); window.removeEventListener('offline', update); }; }, []);
  const allowLeave = React.useCallback(() => { if (pendingSave.current) { window.alert('Check the previous save before leaving this form.'); return false; } return !dirty.current || window.confirm('Leave this form? Unsaved entries will be lost.'); }, []);
  useEffect(() => { const warn = (event: BeforeUnloadEvent) => { if (dirty.current) { event.preventDefault(); event.returnValue = ''; } }; window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn); }, []);
  const navigate = (next: WorkspaceRoute, replace = false) => { if (!allowLeave()) return; dirty.current = false; recovery.clear(); writeRoute(next, replace); acceptedPosition.current = historyPosition(); setRoute(next); };
  useEffect(() => {
    const listener = () => {
      if (undoPop.current) { undoPop.current = false; return; }
      const position = historyPosition();
      if (!allowLeave()) {
        const delta = acceptedPosition.current - position;
        if (delta) { undoPop.current = true; window.history.go(delta); }
        else writeRoute(routeRef.current, true);
        return;
      }
      acceptedPosition.current = position; dirty.current = false; recovery.clear(); setRoute(readRoute());
    };
    window.addEventListener('popstate', listener); return () => window.removeEventListener('popstate', listener);
  }, [allowLeave, recovery]);
  useEffect(() => { document.title = 'Complaints - JBL staff workspace'; setGroupError(undefined); const controller = new AbortController(); void loadGroups(controller.signal).then(result => { setGroups(result.groups); setRoute(previous => { const group = result.groups.some(item => item.key === previous.group) ? previous.group : result.groups[0]?.key || ''; const next = { ...previous, group }; if (appliedPreferences.current) writeRoute(next, true); return next; }); }).catch(error => { if (!controller.signal.aborted) setGroupError(error); }); return () => controller.abort(); }, [refresh]);
  const bootstrap = useRead<Bootstrap>(route.group, 'bootstrap/', refresh);
  useEffect(() => { if (bootstrap.data) { recovery.bind(bootstrap.data.continuity_key); setOwnerReady(bootstrap.data.continuity_key); } }, [bootstrap.data, recovery]);
  const slot = recovery.slot(`${route.group}:${route.view === 'new' ? 'new' : route.selected}`);
  useEffect(() => { if (!bootstrap.data || appliedPreferences.current) return; appliedPreferences.current = true; const preferences = bootstrap.data.preferences || { default_filters: {} }; const next = initialQueuePreferences(routeRef.current, preferences, entryUrl.current); setBranch(preferences.default_filters.branch || ''); writeRoute(next, true); setRoute(next); setPreferencesReady(true); }, [bootstrap.data]);
  useEffect(() => { if (typedQuery.trim() === query) return; const timer = setTimeout(() => { setQuery(typedQuery.trim()); const next = { ...routeRef.current, page: 1, selected: '' }; writeRoute(next, true); setRoute(next); }, 350); return () => clearTimeout(timer); }, [typedQuery, query]);
  const queue = useRead<Queue>(preferencesReady && ['queue', 'new'].includes(route.view) ? route.group : '', 'cases/', refresh, { q: query, status: route.status, branch, category, page: route.page });
  const detail = useRead<{case: Detail}>(route.view === 'queue' && route.selected ? route.group : '', `cases/${route.selected}/`, refresh);
  const sync = useRead<{issues: {key: string; reference: string; status: string; can_retry: boolean}[]}>(route.view === 'queue' ? route.group : '', 'recovery/', refresh);
  const error = groupError || bootstrap.error || queue.error || detail.error;
  useEffect(() => { if (error instanceof OperationError && error.status === 401) recheck(); else if (error instanceof OperationError && error.status === 403) recovery.clear(); }, [error, recheck]);
  const saved = (item: Complaint) => { dirty.current = false; pendingSave.current = false; recovery.clear(); setNotice(`${item.reference}: changes saved.`); navigate({ ...route, view: 'queue', selected: item.key }); setRefresh(value => value + 1); };
  const capabilities = bootstrap.data?.actor.capabilities || [];
  const open = (key: string) => navigate({ ...route, view: 'queue', selected: key });
  const facet = (items: {label: string}[] | undefined, value: string) => [{value: '', label: 'All'}, ...Array.from(new Set([...(items || []).map(item => item.label), value].filter(Boolean))).map(label => ({value: label, label}))];
  const queueView = <Stack xcss={styles.full} space="space.250">
    {<Box xcss={route.selected ? styles.mobileList : undefined}><Grid xcss={styles.filters} gap="space.150"><Box><Label htmlFor="search">Search name, ID, phone or branch</Label><Textfield id="search" type="search" value={typedQuery} onChange={event => setTypedQuery(event.currentTarget.value)}/></Box><Choice id="status" label="Status" value={route.status} options={statuses} onChange={status => navigate({ ...route, status, page: 1, selected: '' })}/><Choice id="branch" label="Branch" value={branch} options={facet(queue.data?.filter_options.branches, branch)} onChange={value => { setBranch(value); navigate({ ...route, page: 1, selected: '' }); }}/><Choice id="category" label="Complaint type" value={category} options={facet(queue.data?.filter_options.categories, category)} onChange={value => { setCategory(value); navigate({ ...route, page: 1, selected: '' }); }}/></Grid></Box>}
    {Boolean(sync.data?.issues.length) && <Inline alignBlock="center" shouldWrap space="space.100"><Text size="small" color="color.text.subtle">{sync.data!.issues.length} saved updates awaiting Google Sheets sync</Text><Button appearance="subtle" onClick={() => setSyncOpen(true)}>Sync details</Button></Inline>}
    <Grid xcss={styles.columns} gap="space.250">
      <Box as="section" aria-label="Complaint queue" xcss={route.selected ? styles.mobileList : undefined}><Stack space="space.100">
        <Inline spread="space-between" alignBlock="center"><Heading as="h2" size="small">{queue.data ? complaintCount(queue.data.pagination.total) : 'Complaints'}</Heading><Text size="small" color="color.text.subtle">{route.status === 'resolved' ? 'Recently closed' : 'Oldest first'}</Text></Inline>
        {queue.data?.items.map(item => <Box key={item.key} xcss={route.selected === item.key ? styles.selectedRow : styles.row}><Anchor xcss={styles.itemLink} href={`/staff/app/complaints/cases/${item.key}/?workspace=${route.group}&status=${route.status}&page=${route.page}`} aria-current={route.selected === item.key ? 'true' : undefined} onClick={event => { event.preventDefault(); open(item.key); }}><Stack space="space.100"><Inline spread="space-between" space="space.100" alignBlock="center"><Text weight="semibold">{item.customer_name || item.reference}</Text><ComplaintStatus status={item.status} needs={item.needs_details}/></Inline><Text size="small" color="color.text.subtle">{item.reference} · {item.branch || 'Branch not recorded'}</Text><Inline shouldWrap spread="space-between" space="space.100"><Text size="small">{item.category}</Text><Text size="small" weight="medium">{item.age_label}</Text></Inline></Stack></Anchor></Box>)}
        {queue.data?.items.length === 0 && <Text>No complaints match these filters.</Text>}{!queue.data && !queue.error && <Box role="status"><Text>Loading complaints…</Text></Box>}
        {queue.data && queue.data.pagination.pages > 1 && <Inline spread="space-between" alignBlock="center" space="space.100"><Text size="small">Page {queue.data.pagination.page} of {queue.data.pagination.pages}</Text><Inline space="space.100"><Button isDisabled={route.page <= 1} onClick={() => navigate({...route, page: route.page - 1, selected: ''})}>Previous</Button><Button isDisabled={route.page >= queue.data.pagination.pages} onClick={() => navigate({...route, page: route.page + 1, selected: ''})}>Next</Button></Inline></Inline>}
      </Stack></Box>
      <Box as="section" aria-label="Complaint detail" xcss={styles.panel} ref={detailPanel} tabIndex={-1}>{detail.data ? <Stack space="space.250">
        <Box xcss={styles.mobileOnly}><Button appearance="subtle" onClick={() => navigate({...route, selected: ''})}>← Back to complaints</Button></Box>
        <Inline shouldWrap spread="space-between" alignBlock="center" space="space.100"><Stack space="space.050"><Heading as="h2" size="medium">{detail.data.case.customer_name || detail.data.case.reference}</Heading><Text color="color.text.subtle">{detail.data.case.reference}</Text></Stack><ComplaintStatus status={detail.data.case.status} needs={detail.data.case.needs_details}/></Inline>
        <Grid xcss={styles.fields} gap="space.250"><Stack space="space.150"><Heading as="h3" size="small">Customer</Heading><Stack space="space.050"><Text size="small" color="color.text.subtle">National ID</Text><Text>{detail.data.case.customer_id || 'Not provided'}</Text></Stack><Stack space="space.050"><Text size="small" color="color.text.subtle">Phone</Text>{detail.data.case.customer_phone ? <Anchor href={`tel:${detail.data.case.customer_phone}`}>{detail.data.case.customer_phone}</Anchor> : <Text>Not provided</Text>}</Stack></Stack><Stack space="space.150"><Heading as="h3" size="small">Complaint</Heading><Text>{detail.data.case.branch || 'Branch not recorded'}</Text><Text>{detail.data.case.category || 'Type not recorded'}</Text><Text size="small" color="color.text.subtle">Reported {displayDate(detail.data.case.reported_at)}</Text><Text size="small">{detail.data.case.age_label}</Text></Stack></Grid>
        <Stack space="space.100"><Heading as="h3" size="small">Description</Heading><Box xcss={styles.prewrap}><Text as="p">{detail.data.case.description}</Text></Box></Stack>
        <Activity key={`${detail.data.case.key}-${detail.data.case.revision}`} group={route.group} caseKey={detail.data.case.key} initial={detail.data.case.history} next={detail.data.case.history_next_cursor} reported={detail.data.case.reported_at}/>
        <Stack space="space.100"><Heading as="h3" size="small">Attachments</Heading>{detail.data.case.evidence.length === 0 ? <Text size="small" color="color.text.subtle">No attachments.</Text> : detail.data.case.evidence.map(item => <Inline key={item.id} shouldWrap space="space.100"><EvidencePreview group={route.group} id={item.id} name={item.name} type={item.mime_type}/><Button onClick={() => { void download(route.group, `evidence/${item.id}/?download=1`).catch(error => setNotice(failure(error))); }}>Download</Button></Inline>)}</Stack>
        {route.view !== 'new' && ownerReady && recovery.bound(bootstrap.data?.continuity_key || '') && <CaseActions slot={slot} key={`${detail.data.case.key}-${detail.data.case.revision}`} group={route.group} item={detail.data.case} saved={saved} voiceEnabled={Boolean(bootstrap.data?.voice_input?.enabled)} markDirty={markDirty}/>}
        <Inline shouldWrap space="space.100"><Button appearance="subtle" onClick={() => { void navigator.clipboard.writeText(window.location.href).then(() => setNotice('Complaint link copied.')).catch(() => setNotice('Copy the link from your address bar.')); }}>Copy link</Button>{queue.data?.items.some(item => item.key !== route.selected) && <Button appearance="subtle" onClick={() => { const items = queue.data!.items; open(items[(items.findIndex(item => item.key === route.selected) + 1) % items.length].key); }}>Next complaint</Button>}</Inline>
      </Stack> : <Text>{route.selected ? 'Loading complaint…' : 'Select a complaint to read its details and activity.'}</Text>}</Box>
    </Grid>
  </Stack>;
  return <SessionRecheck.Provider value={recheck}><Root><TopNav><TopNavStart sideNavToggleButton={null}><Text weight="bold">JBL workspace</Text></TopNavStart><TopNavMiddle>{null}</TopNavMiddle><TopNavEnd><Button appearance="subtle" onClick={() => { if (!dirty.current || window.confirm('Sign out? Unsaved entries will be lost.')) signOut(); }}>Sign out</Button></TopNavEnd></TopNav>
    <Main><Box xcss={styles.page} testId="complaints-operations-content"><Stack space="space.300">
      <Inline alignBlock="center" spread="space-between" shouldWrap space="space.150"><Stack space="space.050"><Heading as="h1" size="large">{route.view === 'settings' ? 'Complaint settings' : 'Complaints'}</Heading><Text color="color.text.subtle">{groups?.find(item => item.key === route.group)?.label || 'Manage complaints and follow up'}</Text></Stack><Inline shouldWrap space="space.100" alignBlock="center">{capabilities.includes('complaint.case.create') && route.view !== 'settings' && <Button appearance="primary" onClick={() => navigate({...route, view: 'new'})}>Create complaint</Button>}<IconButton appearance="subtle" label="Settings" icon={SettingsIcon} onClick={() => navigate({...route, view: 'settings'})}/><IconButton appearance="subtle" label="Refresh workspace" icon={RefreshIcon} onClick={() => { if (!pendingSave.current) setRefresh(value => value + 1); }}/></Inline></Inline>
      {groups && groups.length > 1 && <Choice id="workspace" label="Workspace" value={route.group} options={groups.map(item => ({value: item.key, label: item.label}))} onChange={group => navigate({...route, group, selected: '', page: 1})}/>}
      {!online && <Box role="status"><SectionMessage title="You are offline" headingLevel="h2"><Text as="p">You can keep editing. Reconnect before saving; nothing will be submitted automatically.</Text></SectionMessage></Box>}
      {notice && <Box role="status"><Inline spread="space-between" alignBlock="center" space="space.150"><Text weight="medium">{notice}</Text><Button appearance="subtle" onClick={() => setNotice('')}>Dismiss</Button></Inline></Box>}<Feedback error={error}/>
      {!bootstrap.data && !error && <Box role="status"><Text>Loading workspace…</Text></Box>}
      {groups?.length === 0 && <SectionMessage title="No Complaints access" headingLevel="h2"><Text>Contact your administrator if you need access.</Text></SectionMessage>}
      {bootstrap.data && preferencesReady && (route.view === 'settings' ? <Stack space="space.250"><Inline><Button appearance="subtle" onClick={() => navigate({...route, view: 'queue'})}>← Back to complaints</Button></Inline><WorkspaceSettings group={route.group} branches={bootstrap.data.location_options.branches.map(row => row.name)} reports={capabilities.includes('complaint.reports.view')}/></Stack> :
        <Tabs id="complaints-destinations" selected={route.view === 'reports' ? 1 : 0} onChange={index => navigate({...route, view: index ? 'reports' : 'queue'})}><TabList><Tab>Complaints</Tab>{capabilities.includes('complaint.reports.view') && <Tab>Reports</Tab>}</TabList><TabPanel>{route.view !== 'reports' && queueView}</TabPanel>{capabilities.includes('complaint.reports.view') && <TabPanel>{route.view === 'reports' && <Reports group={route.group} refresh={refresh} open={open} location={route.report} change={report => { const next = {...routeRef.current, report}; writeRoute(next, true); setRoute(next); }}/>}</TabPanel>}</Tabs>)}
      {bootstrap.data && ownerReady && recovery.bound(bootstrap.data.continuity_key) && route.view === 'new' && <TaskDialog title="Create complaint" close={() => navigate({...route, view: 'queue'})}><Create slot={slot} key={route.group} group={route.group} bootstrap={bootstrap.data} onSaved={saved} cancel={() => navigate({...route, view: 'queue'})} markDirty={markDirty}/></TaskDialog>}
      {syncOpen && <TaskDialog title="Google Sheets sync" compact close={() => setSyncOpen(false)}><Text>Changes are saved in Complaints. Google Sheets updates separately.</Text>{sync.data?.issues.filter(item => item.status === 'failed').map(item => <Inline key={item.key} spread="space-between" space="space.100"><Text>{item.reference}: sync needs attention</Text><Button onClick={() => { setSyncOpen(false); open(item.key); }}>Review complaint</Button></Inline>)}{!sync.data?.issues.some(item => item.status === 'failed') && <Text>No failed updates need action.</Text>}</TaskDialog>}
    </Stack></Box></Main>
  </Root></SessionRecheck.Provider>;
}
