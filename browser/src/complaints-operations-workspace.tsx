import React, { useEffect, useId, useRef, useState } from 'react';
import Button from '@atlaskit/button/default/button';
import { IconButton } from '@atlaskit/button/new';
import CheckedIcon from '@atlaskit/icon/core/checkbox-checked';
import UncheckedIcon from '@atlaskit/icon/core/checkbox-unchecked';
import SettingsIcon from '@atlaskit/icon/core/settings';
import Tabs, { Tab, TabList, TabPanel } from '@atlaskit/tabs';
import { Anchor } from '@atlaskit/primitives/compiled/anchor';
import { Reports } from './complaints-operations-reports';
import { EvidenceGallery, VoiceInput } from './complaints-operations-media';
import { WorkspaceSettings } from './complaints-operations-settings';
import { Activity } from './complaints-operations-history';
import { CaseFacts, CaseLocation } from './complaints-case-details';
import { cssMap, cx } from '@atlaskit/css';
import Form, { ErrorMessage, Field, Label, MessageWrapper } from '@atlaskit/form';
import Heading from '@atlaskit/heading';
import { Root } from '@atlaskit/navigation-system/layout/root';
import { Main } from '@atlaskit/navigation-system/layout/main';
import { TopNav, TopNavStart } from '@atlaskit/navigation-system/layout/top-nav';
import { BrowserActions, notify, useViewportPane } from './browser-interactions';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Grid } from '@atlaskit/primitives/compiled/grid';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import SectionMessage from '@atlaskit/section-message';
import { AdaptiveSelect as Select, ActionButton, DialogFooter, DialogStatus, DraftStatus, Section, useValidationFocus } from './complaints-ui';
import CameraIcon from '@atlaskit/icon/core/camera';
import UploadIcon from '@atlaskit/icon/core/upload';
import AttachmentIcon from '@atlaskit/icon/core/attachment';
import CloudIcon from '@atlaskit/icon/core/cloud-arrow-up';
import CopyIcon from '@atlaskit/icon/core/copy';
import NextIcon from '@atlaskit/icon/core/arrow-right';
import AddIcon from '@atlaskit/icon/core/add';
import PersonIcon from '@atlaskit/icon/core/person-avatar';
import SearchIcon from '@atlaskit/icon/core/search';
import PreviousIcon from '@atlaskit/icon/core/arrow-left';
import Textfield from '@atlaskit/textfield';
import { token } from '@atlaskit/tokens';
import { groups as loadGroups, operation, OperationError, type Bootstrap, type Complaint, type Detail, type Group, type Locations, type Queue } from './complaints-operations-transport';
import { readRoute, writeRoute, initialQueuePreferences, historyPosition, type WorkspaceRoute } from './workspace-navigation';
import { TaskDialog, ComplaintStatus, displayDate, complaintCount, confirmAction, ActionMenu, ControlRow, HeaderGutter } from './complaints-ui';
import { TaskSession } from './workspace-task';
import { WorkspaceRecovery, useRetainedValue, type RecoverySlot, type Submission } from './workspace-recovery';
const SessionRecheck = TaskSession;
const LockedForm = React.createContext(false);
const styles = cssMap({
    full: { width: '100%', minWidth: 0 },
    canvas: { minHeight: '100%', backgroundColor: token('elevation.surface.sunken') },

    page: { width: '100%', maxWidth: '120rem', marginInline: 'auto', boxSizing: 'border-box', padding: token('space.200'), '@media (min-width: 64rem)': { padding: token('space.300') } },
    columns: { gridTemplateColumns: 'repeat(1, minmax(0, 1fr))', alignItems: 'start', '@media (min-width: 64rem)': { gridTemplateColumns: 'minmax(16rem, 20rem) minmax(0, 1fr)' } },
    queue: { minHeight: 0, display: 'flex', flexDirection: 'column', gap: token('space.100'), padding: token('space.150'), backgroundColor: token('elevation.surface'), borderWidth: token('border.width'), borderStyle: 'solid', borderColor: token('color.border'), borderRadius: token('radius.medium'), boxSizing: 'border-box' },
    list: { overflowY: 'auto', minHeight: 0, flexGrow: 1, overscrollBehavior: 'contain' },
    detailScroll: { overflowY: 'auto', minHeight: 0, overscrollBehavior: 'contain' },
    search: { minWidth: 0, flexGrow: 1, maxWidth: '23rem' },
    selectedRow: { position: 'relative', backgroundColor: token('color.background.selected'), borderRadius: token('radius.small') },
    selectionMarker: { position: 'absolute', insetInlineStart: 0, insetBlock: 0, width: '3px', pointerEvents: 'none', backgroundColor: token('color.background.selected.bold') },
    age: { whiteSpace: 'nowrap', color: token('color.text.subtle') },
    ageWarning: { color: token('color.text.warning') },
    ageDanger: { color: token('color.text.danger') },
    rowMetadata: { display:'grid', gridTemplateColumns:'minmax(0,1fr) auto', alignItems:'center', gap:token('space.050') },
    sort: { width: '9rem', maxWidth:'100%' },
    mobileList: { display: 'none', '@media (min-width: 64rem)': { display: 'block' } },
    mobileOnly: { '@media (min-width: 64rem)': { display: 'none' } },
    itemLink: { display: 'block', padding: token('space.100'), color: token('color.text'), textDecoration: 'none', borderRadius: token('radius.medium'), '&:hover': { backgroundColor: token('color.background.neutral.subtle.hovered'), textDecoration: 'none' } },
    panel: { minWidth: 0, padding: token('space.200'), borderStyle: 'solid', borderWidth: token('border.width'), borderColor: token('color.border'), borderRadius: token('radius.medium'), overflowWrap: 'anywhere', backgroundColor: token('elevation.surface') },
    row: { minWidth: 0, paddingBlock: token('space.100'), borderBlockEndWidth: token('border.width'), borderBlockEndStyle: 'solid', borderBlockEndColor: token('color.border'), overflowWrap: 'anywhere' },
    fields: { gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 16rem), 1fr))', alignItems: 'start' },
    prewrap: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' },
    textarea: { width: '100%', boxSizing: 'border-box', padding: token('space.100'), borderStyle: 'solid', borderWidth: token('border.width'), borderColor: token('color.border.input'), borderRadius: token('radius.small'), backgroundColor: token('color.background.input'), color: token('color.text'), font: token('font.body.large'), resize: 'vertical' },
    form: { width: '100%', maxWidth: '42rem', marginInline: 'auto' },
    attachmentActions: { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', '@media (min-width: 64rem)': { gridTemplateColumns: 'repeat(1, minmax(0, 1fr))' } },
    attachmentRow: { display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto', alignItems: 'center', gap: token('space.100'), paddingBlock: token('space.100'), borderBlockEnd: `${token('border.width')} solid ${token('color.border')}` },
    syncRow: { display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', alignItems: 'center', gap: token('space.100'), paddingBlock: token('space.100'), borderBlockEnd: `${token('border.width')} solid ${token('color.border')}`, '@media (min-width: 48rem)': { gridTemplateColumns: 'minmax(0, 1fr) auto' } },
    filename: { minWidth: 0, overflowWrap: 'anywhere' },
    tabsBar: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: token('space.100') },
    tabs: { flexGrow: 1, flexBasis: '8rem', minWidth: 0 },
    camera: { '@media (min-width: 64rem)': { display: 'none' } },
});
const statuses = [{ value: 'pending', label: 'Open + Reopened' }, { value: 'resolved', label: 'Closed' }, { value: 'all', label: 'All complaints' }];
const actionLabels: Record<string, string> = { resolve: 'Resolve complaint', comment: 'Add note', reopen: 'Reopen complaint', 'complete-details': 'Complete missing details', 'retry-publication': 'Retry Sheet sync' };
/** Align real wrapped ADS labels per row without shrinking type or reserving blank rows. */
function AlignedFields({children}:{children:React.ReactNode}) {
    const ref=useRef<HTMLDivElement>(null);
    useEffect(()=>{
        const node=ref.current;if(!node)return;
        const align=()=>{
            const children=Array.from(node.children).filter((item):item is HTMLElement=>item instanceof HTMLElement);
            children.forEach(child=>{child.style.paddingBlockStart='';const label=child.querySelector('label');if(label)label.style.minHeight='';});
            const columns=getComputedStyle(node).gridTemplateColumns.split(' ').length;
            for(let i=0;i<children.length;i+=columns){
                const row=children.slice(i,i+columns).map(child=>({child,label:child.querySelector('label')})).filter((item):item is {child:HTMLElement;label:HTMLLabelElement}=>item.label instanceof HTMLLabelElement);
                const labelTop=Math.max(...row.map(item=>item.label.getBoundingClientRect().top)),labelHeight=Math.max(...row.map(item=>item.label.getBoundingClientRect().height));
                row.forEach(({child,label})=>{const adjustment=labelTop-label.getBoundingClientRect().top;if(adjustment>0)child.style.paddingBlockStart=`${adjustment}px`;label.style.minHeight=`${labelHeight}px`;});
            }
        };
        const resize=new ResizeObserver(align),mutation=new MutationObserver(align);resize.observe(node);mutation.observe(node,{childList:true,subtree:true,characterData:true});align();
        return()=>{resize.disconnect();mutation.disconnect();};
    },[]);
    return <Grid ref={ref} xcss={styles.fields} gap="space.150">{children}</Grid>;
}
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
function Feedback({ error, retry }: {
    error?: unknown;
    retry?:()=>void;
}) {
    const recheck = React.useContext(SessionRecheck);
    return error ? <Box role="alert"><SectionMessage appearance="error" title="Action could not be completed" headingLevel="h2"><Text as="p">{failure(error)}</Text>{retry&&<Button onClick={retry}>Retry</Button>}{error instanceof OperationError && error.status === 401 && <Button onClick={recheck}>Sign in again</Button>}</SectionMessage></Box> : null;
}
function Choice({ id, label, value, options, onChange, error, required=false, isDisabled=false, hint }: {
    id: string;
    label: string;
    value: string;
    options: {
        value: string;
        label: string;
    }[];
    onChange: (value: string) => void;
    error?: string;
    required?: boolean;
    isDisabled?: boolean;
    hint?: string;
}) {
    const locked = React.useContext(LockedForm);
    return <Box><Label htmlFor={id}>{label}{required&&<Text as="span" color="color.text.danger"> *</Text>}</Label><Select isDisabled={locked||isDisabled} isRequired={required} validationState={error?'error':'default'} inputId={id} aria-required={required} aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : hint?`${id}-hint`:undefined} options={options} value={options.find(option => option.value === value) || null} onChange={option => onChange(option?.value || '')}/>{hint&&<Text id={`${id}-hint`} size="small" color="color.text.subtle">{hint}</Text>}{error && <Box id={`${id}-error`} role="alert"><Text color="color.text.danger">{error}</Text></Box>}</Box>;
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
    useEffect(()=>{if(error)notify(error,'error');},[error]);
    const add = (items: FileList | null) => {
        const next = [...files, ...Array.from(items || [])];
        if (next.length > 10 || next.some(file => file.size > 10 * 1024 * 1024) || next.reduce((size, file) => size + file.size, 0) > 30 * 1024 * 1024)
            setError('Choose up to 10 files, 10 MB each and 30 MB in total.');
        else {
            setFiles(next);
            setError('');

        }
    };
    return <Section title="Attachments"><Stack space="space.150"><Text size="small" color="color.text.subtle">Images or PDF · up to 10 files · 10 MB each, 30 MB total</Text>
    <Box as="input" type="file" hidden ref={picker} multiple accept=".jpg,.jpeg,.png,.webp,.pdf" aria-label="Choose evidence files" onChange={event => { add(event.currentTarget.files); event.currentTarget.value = ''; }}/>
    <Box as="input" type="file" hidden ref={camera} accept="image/*" capture="environment" aria-label="Capture a photo" onChange={event => { add(event.currentTarget.files); event.currentTarget.value = ''; }}/>
    <Grid xcss={styles.attachmentActions} gap="space.100"><Box xcss={styles.camera}><Button shouldFitContainer iconBefore={CameraIcon} isDisabled={locked} onClick={() => camera.current?.click()}>Take photo</Button></Box><Button shouldFitContainer iconBefore={UploadIcon} isDisabled={locked} onClick={() => picker.current?.click()}>Attach files</Button></Grid>
    {files.length>0&&<Box role="status"><Text size="small">{files.length} {files.length===1?'file selected':'files selected'}. Uploaded when you save the complaint.</Text></Box>}
    {files.map((file, index) => <Box key={`${file.name}-${index}`} xcss={styles.attachmentRow}><Box xcss={styles.filename}><Inline space="space.050" alignBlock="center"><AttachmentIcon label=""/><Text size="small">{file.name}</Text></Inline></Box><ActionButton tone="destructive" isDisabled={locked} onClick={() => setFiles(files.filter((_, item) => item !== index))} aria-label={`Remove ${file.name}`}>Remove</ActionButton></Box>)}
    {error && <Box role="alert"><Text color="color.text.danger">{error}</Text></Box>}
  </Stack></Section>;
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
    return state.uncertain ? <Box ref={message} role="alert" tabIndex={-1}><SectionMessage appearance="warning" title="Check the previous save" headingLevel="h3"><Text as="p">It may already be saved. Retry the same update to confirm before making changes.</Text><Inline shouldWrap space="space.100">{state.error instanceof OperationError && state.error.status === 401 && <Button onClick={recheck}>Sign in again</Button>}<Button isLoading={state.busy} onClick={async () => { void state.retry(); }}>Retry previous save</Button><Button isDisabled={state.busy} appearance="subtle" onClick={async () => { if (await confirmAction('The previous save may already have completed. Leave this form and check the complaint list before submitting again?')) { state.abandon(); leave(); } }}>Leave without checking</Button></Inline></SectionMessage></Box> : null;
}
function CaseActions({ group, item, saved, voiceEnabled, markDirty, slot, categories }: {
    group: string;
    item: Detail;
    saved: (item: Complaint, next?:boolean) => void;
    voiceEnabled: boolean;
    markDirty: (value: boolean, pending?: boolean) => void;
    slot: RecoverySlot;
    categories: string[];
}) {
    const formId=useId();
    const [action, setAction] = useRetainedValue(slot, 'action', ''), [values, setValues] = useRetainedValue<Record<string, string>>(slot, 'values', {}), [files, setFiles] = useRetainedValue<File[]>(slot, 'files', []);
    const [revision, setRevision] = useRetainedValue(slot, 'revision', item.revision), [latest, setLatest] = useState<Detail>();
    const [openNext,setOpenNext]=useRetainedValue(slot,'openNext',false);
    const completionValues: Record<string, string> = { customer_phone: item.customer_phone || '', customer_id: item.customer_id || '', complaint_category: categories.includes(item.category) ? item.category : '', ...values };
    const state = useSave(group, value=>{const next=action==='resolve'&&openNext;setAction('');setValues({});setFiles([]);markDirty(false);saved(value,next);}, slot);
    useEffect(() => { markDirty(Boolean(Object.keys(values).length || files.length || state.busy || state.uncertain), state.busy || state.uncertain); return () => markDirty(false); }, [values, files, state.busy, state.uncertain, markDirty]);
    useValidationFocus(formId,state.errors);
    const available = item.actions.filter(name => name in actionLabels && (name === 'retry-publication' ? ['failed', 'pending'].includes(item.sync_status) : name === 'complete-details' ? item.needs_details : name === 'reopen' ? item.status === 'CLOSED' : item.status !== 'CLOSED' && !item.needs_details));
    const closeAction=async()=>{if(state.busy||state.uncertain)return;if((Object.keys(values).length||files.length)&&!await confirmAction('Discard this unfinished update?'))return;setAction('');setValues({});setFiles([]);};
    return <Stack space="space.150">
    <Inline shouldWrap space="space.100" aria-label="Complaint actions">{available.map(name => <ActionButton tone={name==='resolve'||name==='complete-details'?'positive':'neutral'} key={name} isDisabled={state.busy || state.uncertain} onClick={() => { setRevision(item.revision); setAction(name); setValues({}); setFiles([]);setOpenNext(false); state.setErrors({}); }}>{actionLabels[name]}</ActionButton>)}</Inline>
    {action && <TaskDialog title={actionLabels[action]} compact hasStatus close={closeAction}>
    <Text weight="semibold">{item.reference} · {item.customer_name}</Text>
    <DialogStatus><DraftStatus state={state.busy?'saving':state.error?'error':!navigator.onLine?'offline':'draft'}/></DialogStatus>
    {action && <LockedForm.Provider value={state.busy || state.uncertain}><Form<Record<string, string>> key={action} onSubmit={() => {
                const fields = action === 'complete-details' ? completionValues : values;
                const required = action === 'complete-details' ? ['customer_phone', 'customer_id', 'complaint_category'] : action === 'retry-publication' ? [] : [action === 'comment' ? 'comment_text' : action === 'reopen' ? 'reason' : 'resolution_text'];
                const missing = Object.fromEntries(required.filter(name => !fields[name]?.trim()).map(name => [name, 'Complete this field.']));
                if (Object.keys(missing).length) {
                    state.setErrors(missing);
                    return;
                }
                return state.save(`cases/${item.key}/${action}/`, { ...fields, expected_revision: revision }, files);
            }}>{({ formProps }) => <Box as="form" {...formProps} id={formId} noValidate><Stack space="space.150">
      <Feedback error={state.uncertain ? undefined : state.error}/><PreviousSave state={state} leave={() => { markDirty(false); setAction(''); setValues({}); setFiles([]); }}/>
      {state.error instanceof OperationError && state.error.status === 409 && <Button onClick={() => { void operation<{case: Detail}>(group, `cases/${item.key}/`, new AbortController().signal).then(result => { setRevision(result.case.revision); setLatest(result.case); }).catch(() => {}); }}>Review latest case</Button>}
      {latest && <Box role="status"><Text>Latest update: {latest.history[0]?.note || labelStatus(latest)}. Your entered text is retained. Review it before saving.</Text></Box>}
      {action === 'complete-details' ? <Grid xcss={styles.fields} gap="space.150">{[['customer_phone', 'Primary phone number'], ['customer_id', 'National ID']].map(([name, label]) => <Input key={name} name={name} label={label} values={completionValues} errors={state.errors} change={(key, value) => setValues(previous => ({ ...previous, [key]: value }))} required/>)}<Choice id="complete-category" label="Complaint type" value={completionValues.complaint_category} options={categories.map(value => ({value, label: value}))} onChange={value => setValues(previous => ({...previous, complaint_category: value}))} error={state.errors.complaint_category} required/></Grid> : action !== 'retry-publication' && <Input name={action === 'comment' ? 'comment_text' : action === 'reopen' ? 'reason' : 'resolution_text'} label={action === 'comment' ? 'Feedback note' : action === 'reopen' ? 'Reason for reopening' : 'Resolution note'} values={values} errors={state.errors} change={(key, value) => { setValues(previous => ({ ...previous, [key]: value })); state.setErrors({}); }} required/>}
      {!state.busy && !state.uncertain && voiceEnabled && ['resolve', 'comment', 'reopen'].includes(action) && <VoiceInput group={group} caseKey={item.key} field={action === 'comment' ? 'complaint_resolution_comment' : action === 'reopen' ? 'complaint_reopen_reason' : 'complaint_resolution_note'} accept={(text, id) => setValues(previous => ({ ...previous, [action === 'comment' ? 'comment_text' : action === 'reopen' ? 'reason' : 'resolution_text']: text, voice_transcription_id: id }))} />}
      {action === 'resolve' && <Files files={files} setFiles={setFiles}/>}
      {action==='resolve'&&<Button iconBefore={openNext?CheckedIcon:UncheckedIcon} role="checkbox" aria-checked={openNext} isSelected={openNext} isDisabled={state.busy||state.uncertain} onClick={()=>setOpenNext(value=>!value)}>Open next complaint after resolving</Button>}
      <DialogFooter><Button shouldFitContainer isDisabled={state.busy || state.uncertain} onClick={closeAction}>Cancel</Button><ActionButton tone={action==='resolve'||action==='complete-details'?'positive':'neutral'} shouldFitContainer type="submit" form={formId} isLoading={state.busy} isDisabled={state.uncertain}>{action==='complete-details'?'Save details':action==='resolve'&&openNext?'Resolve and open next':actionLabels[action]}</ActionButton></DialogFooter>
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
    const formId=useId();
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
    const [draftReady, setDraftReady] = useState(false), [draftPaused, setDraftPaused] = useState(false);
    const draftTimer = useRef<ReturnType<typeof setTimeout>>(), draftWork = useRef<Promise<void>>(), submitting = useRef(false);
    const latestValues = useRef(values); latestValues.current = values;
    const locked = state.busy || state.uncertain;
    useEffect(() => { markDirty(Boolean(JSON.stringify(values) !== savedDraftValues || files.length || locked), locked); return () => markDirty(false); }, [values, files, locked, savedDraftValues, markDirty]);
    useEffect(() => () => { clearTimeout(draftTimer.current); submitting.current = true; }, []);
    const [locationRetry, setLocationRetry] = useState(0);
    const [locationChoices, setLocationChoices] = useState<{key: string; data?: Locations; error?: unknown}>({key: ''});
    const locationKey = JSON.stringify([group, values.branch_region || '', values.county || '', locationRetry]);
    const locations = locationChoices.key === locationKey && locationChoices.data ? locationChoices.data : {branches: bootstrap.location_options.branches, counties: [], sub_counties: []};
    const locationsLoading = locationChoices.key !== locationKey || (!locationChoices.data && !locationChoices.error);
    const locationError = locationChoices.key === locationKey ? locationChoices.error : undefined;
    useEffect(() => {
        const controller = new AbortController();
        void operation<{
            draft: {
                key: string;
                fields: Record<string, string>;
                revision: number;
            } | null;
        }>(group, 'draft/', controller.signal).then(result => { if(controller.signal.aborted)return; setDraft(result.draft); setDraftReady(true); if (!slot.read().draftKey) { setDraftRevision(result.draft?.revision || 0); setDraftKey(result.draft?.key || ''); } }).catch(() => {if(!controller.signal.aborted){setDraftPaused(true);setDraftMessage('Saved draft could not be checked. Your current entries are unaffected.');}});
        return () => controller.abort();
    }, [group]);
    useEffect(() => {
        const controller = new AbortController();
        let active = true;
        const timer = setTimeout(() => controller.abort(), 20000);
        setLocationChoices({key: locationKey});
        // POST is unnecessary for non-sensitive catalogue choices; names are sent as codes.
        const params = new URLSearchParams({ branch: values.branch_region || '', county: values.county || '' });
        void fetch(`/api/staff/complaints/operations/v1/groups/${group}/locations/?${params}`, { credentials: 'same-origin', mode: 'same-origin', cache: 'no-store', redirect: 'error', signal: controller.signal }).then(async (response) => { if (!response.ok)
            throw new OperationError(response.status, 'Location choices could not be loaded. Check your connection and retry.'); return response.json() as Promise<Locations>; }).then(data => {if(active)setLocationChoices({key: locationKey, data});}).catch(error => {if(active)setLocationChoices({key: locationKey, error});}).finally(() => clearTimeout(timer));
        return () => {active = false; controller.abort(); clearTimeout(timer);};
    }, [locationKey]);
    const change = (name: string, value: string) => { setValues(previous => ({ ...previous, [name]: value, ...(name === 'branch_region' ? { county: '', sub_county: '' } : name === 'county' ? { sub_county: '' } : {}) })); state.setErrors({}); };
    const saveDraft = async (discard = false) => {
        if (draftPending.current || locked) return;
        const snapshot = {...latestValues.current};
        if (!navigator.onLine) { setDraftPaused(true);setDraftError(new OperationError(0, 'You are offline. Reconnect before saving your draft.')); return; }
        draftPending.current = true; setDraftBusy(true); setDraftError(undefined); setDraftMessage('');
        const request = new AbortController(); draftRequest.current = request;
        const timeout = setTimeout(() => request.abort(), 30000);
        try {
            const current = await operation<{draft: typeof draft}>(group, 'draft/', request.signal);
            if ((current.draft?.key || '') !== draftKey || (current.draft?.revision || 0) !== draftRevision) {
                setDraft(current.draft); setDraftRevision(current.draft?.revision || 0); setDraftKey(current.draft?.key || '');
                const fields = Object.fromEntries(Object.entries(snapshot).filter(([key]) => !['voice_transcription_id', 'category_inference_token'].includes(key)));
                const same = current.draft && JSON.stringify(Object.entries(current.draft.fields).sort()) === JSON.stringify(Object.entries(fields).sort());
                if (discard && !current.draft) setDraftMessage('Saved draft discarded.');
                else if (!discard && same) { setSavedDraftValues(JSON.stringify(snapshot)); setDraft(null); setDraftMessage('Saved'); }
                else {setDraftPaused(true);setDraftMessage('Your saved draft changed. Review it before saving again. Your current entries are still here.');}
                return;
            }
            const result = await operation<{
                draft: {
                    key: string;
                    fields: Record<string, string>;
                    revision: number;
                } | null;
            }>(group, 'draft/', request.signal, discard ? { action: 'discard', key: draftKey, revision: draftRevision } : { fields: snapshot, key: draftKey, revision: draftRevision });
            setDraft(null);
            setDraftRevision(result.draft?.revision || 0); setDraftKey(result.draft?.key || '');
            setDraftMessage(discard ? 'Saved draft discarded.' : 'Saved');
            setDraftPaused(false);
            if (!discard) setSavedDraftValues(JSON.stringify(snapshot));
            else notify('Saved draft discarded.');
        }
        catch (error) {
            setDraftError(error); setDraftPaused(true);
        }
        finally { clearTimeout(timeout); draftPending.current = false; setDraftBusy(false); }
    };
    const runDraft = (discard = false) => { const work = saveDraft(discard); draftWork.current = work; return work; };
    useEffect(() => {
        submitting.current = false;
        if (!draftReady || draft || draftPaused || draftBusy || locked || JSON.stringify(values) === savedDraftValues || !Object.keys(values).length) return;
        setDraftMessage(navigator.onLine ? 'Saving…' : 'Not saved — offline');
        draftTimer.current = setTimeout(() => { if (!submitting.current) void runDraft(); }, 700);
        return () => clearTimeout(draftTimer.current);
    }, [values, savedDraftValues, draftReady, draft, draftPaused, draftBusy, locked]);
    useValidationFocus(formId,state.errors);
    const draftStatus=!navigator.onLine?'offline':draftError||draftPaused?'error':draftBusy?'saving':JSON.stringify(values)===savedDraftValues&&Object.keys(values).length?'saved':'draft';
    return <LockedForm.Provider value={locked}><Box xcss={styles.form}><Stack space="space.200"><DialogStatus><DraftStatus state={draftStatus}/></DialogStatus>
    {draft && <Inline shouldWrap space="space.100" alignBlock="center"><Text>You have a saved draft.</Text><ActionButton isDisabled={locked || draftBusy} onClick={async () => { if (Object.keys(values).length && !await confirmAction('Replace the current entries with your saved draft?')) return; setValues(draft.fields); setSavedDraftValues(JSON.stringify(draft.fields)); setDraft(null); setDraftPaused(false); setDraftMessage('Draft restored.'); notify('Draft restored. Reselect files if needed.', 'information'); }}>Restore</ActionButton><Button appearance="danger" isDisabled={locked || draftBusy} onClick={async () => { if (await confirmAction('Discard the saved draft?')) void runDraft(true); }}>Discard</Button></Inline>}
    {draftPaused && draftMessage && <Box role="status"><Text color="color.text.subtle">{draftMessage}</Text></Box>}
    {draftPaused && !draft && <Button onClick={() => {setDraftPaused(false);setDraftReady(true);void runDraft();}}>Retry draft</Button>}
    <Feedback error={state.uncertain ? undefined : state.error || draftError}/><PreviousSave state={state} leave={() => { markDirty(false); cancel(); }}/>
    <Form<Record<string, string>> onSubmit={async () => {
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
            submitting.current = true; clearTimeout(draftTimer.current); await draftWork.current;
            return state.save('cases/create/', { ...values, browser_draft_revision: String(slot.read().draftRevision || 0), browser_draft_key: String(slot.read().draftKey || '') }, files);
        }}>{({ formProps }) => <Box as="form" {...formProps} id={formId} noValidate><Stack space="space.200">
      <Text size="small" color="color.text.subtle">Required fields are marked *.</Text><Section title="Customer details"><AlignedFields>{[['client_name', 'Customer name'], ['customer_id', 'National ID'], ['customer_phone', 'Primary phone number'], ['secondary_phone', 'Alternative phone number']].map(([name, label]) => <Input key={name} name={name} label={label} values={values} errors={state.errors} change={change} required={name !== 'secondary_phone'} type={name.includes('phone') ? 'tel' : 'text'}/>)}</AlignedFields></Section>
      <Section title="Location">{locationsLoading && <Box role="status"><Text size="small">Loading location choices…</Text></Box>}<Feedback error={locationError} retry={() => setLocationRetry(value => value + 1)}/><AlignedFields>{[['branch_region', 'Branch', locations.branches], ['county', 'County', locations.counties], ['sub_county', 'Constituency', locations.sub_counties]].map(([name, label, options]) => <Stack key={String(name)} space="space.050"><Choice id={`create-${name}`} label={String(label)} value={values[String(name)] || ''} options={(options as Locations['branches']).map(item => ({ value: item.code, label: item.name }))} onChange={value => change(String(name), value)} error={state.errors[String(name)]} required isDisabled={name==='county'?!values.branch_region||locationsLoading||Boolean(locationError):name==='sub_county'?!values.county||locationsLoading||Boolean(locationError):false} hint={name==='county'&&!values.branch_region?'Choose a branch first.':name==='sub_county'&&!values.county?'Choose a county first.':undefined}/></Stack>)}<Input name="village" label="Village/Nearest Landmark" values={values} errors={state.errors} change={change} required/></AlignedFields></Section>
      <Section title="Complaint"><Stack space="space.150"><Choice id="create-category" label="Complaint type" value={values.complaint_category || ''} options={bootstrap.categories.map(value => ({ value, label: value }))} onChange={value => change('complaint_category', value)} error={state.errors.complaint_category} required/>
      <Input name="complaint_description" label="Complaint description" values={values} errors={state.errors} change={change} required/></Stack></Section>
      <Inline shouldWrap space="space.100" alignBlock="center"><Button isDisabled={locked} onClick={() => { navigator.geolocation?.getCurrentPosition(position => { change('latitude', position.coords.latitude.toFixed(6)); change('longitude', position.coords.longitude.toFixed(6)); notify('Location captured.'); }, () => {notify('Location was not shared. You can continue without a map pin.','information');}); }}>Use current location</Button>{values.latitude && <Text size="small">Location captured</Text>}</Inline>
      {!locked && bootstrap.voice_input?.enabled && <VoiceInput group={group} field="complaint_description" maxSeconds={bootstrap.voice_input.max_seconds} accept={(text, id) => { change('complaint_description', text); change('voice_transcription_id', id); }} />}
      <Files files={files} setFiles={setFiles}/>
      <DialogFooter><Button shouldFitContainer isDisabled={locked} onClick={cancel}>Cancel</Button><ActionButton shouldFitContainer type="submit" form={formId} isLoading={state.busy} isDisabled={state.uncertain || locationsLoading || Boolean(locationError)}>Submit complaint</ActionButton></DialogFooter>
    </Stack></Box>}</Form>
  </Stack></Box></LockedForm.Provider>;
}
export function ComplaintsOperationsWorkspace({ signOut, recheck, recovery }: { signOut: () => void; recheck: () => void; recovery: WorkspaceRecovery }) {
  const [route, setRoute] = useState<WorkspaceRoute>(readRoute), [groups, setGroups] = useState<Group[] | null>(null), [groupError, setGroupError] = useState<unknown>(), [refresh, setRefresh] = useState(0);
  const [query, setQuery] = useState(''), [typedQuery, setTypedQuery] = useState(''), [branch, setBranch] = useState(''), [category, setCategory] = useState(''), [notice, setNotice] = useState('');
  const [ownerReady, setOwnerReady] = useState(''), [online, setOnline] = useState(navigator.onLine);
    const [syncOpen, setSyncOpen] = useState(false), [preferencesReady, setPreferencesReady] = useState(false), [filtersOpen, setFiltersOpen] = useState(false);

    const queuePosition = useRef(0);
    const queueList = useRef<HTMLDivElement | null>(null);
    useEffect(()=>{queuePosition.current=0;if(queueList.current)queueList.current.scrollTop=0;},[query,branch,category,route.status,route.page]);
  const entryUrl = useRef(window.location.href), appliedPreferences = useRef(false), detailPanel = useRef<HTMLDivElement>(null), dirty = useRef(false), pendingSave = useRef(false);
  const acceptedPosition = useRef(historyPosition()), undoPop = useRef(false);
  const routeRef = useRef(route); routeRef.current = route;
  const markDirty = React.useCallback((value: boolean, pending = false) => { dirty.current = value; pendingSave.current = pending; }, []);
  useEffect(() => { const update = () => setOnline(navigator.onLine); window.addEventListener('online', update); window.addEventListener('offline', update); return () => { window.removeEventListener('online', update); window.removeEventListener('offline', update); }; }, []);
  const navigationGeneration = useRef(0);
  const leaveDecision = useRef<Promise<boolean> | null>(null);
  const allowLeave = React.useCallback(async () => {
    if (pendingSave.current) { notify('Check the previous save before leaving this form.', 'warning'); return false; }
    if (!dirty.current) return true;
    if (!leaveDecision.current) leaveDecision.current=confirmAction('Your unfinished entries will be discarded.').finally(()=>{leaveDecision.current=null;});
    return leaveDecision.current;
  }, []);
  useEffect(() => { const warn = (event: BeforeUnloadEvent) => { if (dirty.current) { event.preventDefault(); event.returnValue = ''; } }; window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn); }, []);
  const navigate = async (next: WorkspaceRoute, replace = false) => { const generation=++navigationGeneration.current;if (!await allowLeave() || generation!==navigationGeneration.current) return; dirty.current = false; recovery.clear(); writeRoute(next, replace); acceptedPosition.current = historyPosition(); setRoute(next); };
  useEffect(() => {
    const listener = async () => {
      if (undoPop.current) { undoPop.current = false; return; }
      const position = historyPosition();
      if (dirty.current || pendingSave.current) {
        const target=readRoute(), generation=++navigationGeneration.current;
        const delta = acceptedPosition.current - position;
        if (delta) { undoPop.current = true; window.history.go(delta); }
        else writeRoute(routeRef.current, true);
        if (await allowLeave() && generation===navigationGeneration.current) {
          dirty.current=false; recovery.clear();
          if (delta) window.history.go(-delta);
          else {writeRoute(target,true);setRoute(target);}
        }
        return;
      }
      acceptedPosition.current = position; dirty.current = false; recovery.clear(); setRoute(readRoute());
    };
    window.addEventListener('popstate', listener); return () => window.removeEventListener('popstate', listener);
  }, [allowLeave, recovery]);
  useEffect(() => { document.title = 'Complaints - JBL staff workspace'; setGroupError(undefined); const controller = new AbortController(); void loadGroups(controller.signal).then(result => { setGroups(result.groups); setRoute(previous => { const group = result.groups.some(item => item.key === previous.group) ? previous.group : result.groups[0]?.key || ''; const next = { ...previous, group }; if (appliedPreferences.current) writeRoute(next, true); return next; }); }).catch(error => { if (!controller.signal.aborted) setGroupError(error); }); return () => controller.abort(); }, [refresh]);
  const bootstrap = useRead<Bootstrap>(route.group, 'bootstrap/', refresh);
  useEffect(() => { if (bootstrap.data) { recovery.bind(bootstrap.data.continuity_key); setOwnerReady(bootstrap.data.continuity_key); } }, [bootstrap.data, recovery]);
  const slot = recovery.slot(`${route.group}:${route.view === 'queue' ? route.selected : route.view}`);
  useEffect(() => { if (!bootstrap.data || appliedPreferences.current) return; appliedPreferences.current = true; const preferences = bootstrap.data.preferences || { default_filters: {} }; const next = initialQueuePreferences(routeRef.current, preferences, entryUrl.current); setBranch(preferences.default_filters.branch || ''); writeRoute(next, true); setRoute(next); setPreferencesReady(true); }, [bootstrap.data]);
  useEffect(() => { if (typedQuery.trim() === query) return; const timer = setTimeout(() => { setQuery(typedQuery.trim()); const next = { ...routeRef.current, page: 1, selected: '' }; writeRoute(next, true); setRoute(next); }, 350); return () => clearTimeout(timer); }, [typedQuery, query]);
  const order=route.order||(route.status==='pending'?'oldest':'newest');
  const queue = useRead<Queue>(preferencesReady && ['queue', 'new'].includes(route.view) ? route.group : '', 'cases/', refresh, { q: query, status: route.status, branch, category, page: route.page, order, selected:route.selected });
  const detail = useRead<{case: Detail}>(route.view === 'queue' && route.selected ? route.group : '', `cases/${route.selected}/`, refresh);
  const sync = useRead<{counts:{total:number;pending:number;failed:number;suspended:number};issues: {key: string; reference: string; status: string; can_retry: boolean;status_updated_at?:string;last_synced_at?:string}[]}>(route.group, 'recovery/', refresh);
  const queuePane = useViewportPane(Boolean(queue.data?.items.length)), detailPane = useViewportPane(Boolean(detail.data));
  const error = groupError || bootstrap.error || queue.error || detail.error;
  useEffect(() => { if (error instanceof OperationError && error.status === 401) recheck(); else if (error instanceof OperationError && error.status === 403) recovery.clear(); }, [error, recheck]);
  const saved = async (item: Complaint, openNext = false) => {
    const following=openNext?queue.data?.navigation?.next:null, context=routeRef.current;
    dirty.current=false;pendingSave.current=false;recovery.clear();setNotice(`${item.reference}: changes saved.`);
    let target:WorkspaceRoute={...context,view:'queue',selected:item.key};
    if(following){
      const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);
      try {
        const current=await operation<Queue>(context.group,'cases/',controller.signal,{q:query,status:context.status,branch,category,page:1,order,selected:following.key});
        if(current.navigation)target={...target,selected:following.key,page:Math.floor((current.navigation.position-1)/(current.pagination.page_size||10))+1};
        else notify('Changes saved. The next complaint is no longer in this queue.','information');
      }catch{notify('Changes saved. Refresh the queue before opening the next complaint.','warning');}
      finally{clearTimeout(timer);}
    }
    if(routeRef.current===context)void navigate(target);
    setRefresh(value=>value+1);
  };
  const capabilities = bootstrap.data?.actor.capabilities || [];
  const open = (key: string) => navigate({ ...route, view: 'queue', selected: key });
  const facet = (items: {label: string}[] | undefined, value: string) => [{value: '', label: 'All'}, ...Array.from(new Set([...(items || []).map(item => item.label), value].filter(Boolean))).map(label => ({value: label, label}))];
  useEffect(() => { if (notice) { notify(notice); setNotice(''); } }, [notice]);
  const activeFilters = [route.status !== 'pending' ? statuses.find(item => item.value === route.status)?.label : '', branch, category].filter(Boolean);
  const queueView = <Stack xcss={styles.full} space="space.150">
    <Box xcss={route.selected ? styles.mobileList : undefined}><ControlRow><Box xcss={styles.search}><Textfield id="search" aria-label="Search name, ID, phone or branch" placeholder="Search complaints…" elemBeforeInput={<SearchIcon label=""/>} type="search" value={typedQuery} onChange={event => setTypedQuery(event.currentTarget.value)}/></Box><Button onClick={() => setFiltersOpen(true)}>Filters{activeFilters.length ? ` · ${activeFilters.length}` : ""}</Button></ControlRow>
    {activeFilters.length > 0 && <Inline shouldWrap space="space.050">{route.status !== 'pending' && <Button appearance="subtle" onClick={() => navigate({...route,status:'pending',page:1,selected:''})}>{statuses.find(item => item.value === route.status)?.label} ×</Button>}{branch && <Button appearance="subtle" onClick={() => {setBranch('');navigate({...route,page:1,selected:''});}}>Branch: {branch} ×</Button>}{category && <Button appearance="subtle" onClick={() => {setCategory('');navigate({...route,page:1,selected:''});}}>Type: {category} ×</Button>}</Inline>}</Box>
    {filtersOpen && <TaskDialog title="Filter complaints" size="medium" close={() => setFiltersOpen(false)}><Grid xcss={styles.fields} gap="space.150"><Choice id="status" label="Status" value={route.status} options={statuses} onChange={status => navigate({ ...route, status, page: 1, selected: '' })}/><Choice id="branch" label="Branch" value={branch} options={facet(queue.data?.filter_options.branches, branch)} onChange={value => { setBranch(value); navigate({ ...route, page: 1, selected: '' }); }}/><Choice id="category" label="Complaint type" value={category} options={facet(queue.data?.filter_options.categories, category)} onChange={value => { setCategory(value); navigate({ ...route, page: 1, selected: '' }); }}/></Grid><DialogFooter><Button shouldFitContainer onClick={() => {setBranch('');setCategory('');navigate({...route,status:'pending',page:1,selected:''});}}>Reset filters</Button><Button shouldFitContainer appearance="primary" onClick={() => setFiltersOpen(false)}>Done</Button></DialogFooter></TaskDialog>}
    <Grid xcss={route.selected?styles.columns:styles.full} gap="space.250">
      <Box xcss={route.selected ? styles.mobileList : undefined}><Box as="section" aria-label="Complaint queue" ref={queuePane} xcss={styles.queue}>
        <Inline shouldWrap spread="space-between" alignBlock="center"><Text size="small" color="color.text.subtle">{route.status==="pending"?"Open complaints":route.status==="resolved"?"Closed complaints":"All statuses"}</Text><Box xcss={styles.sort}><Select inputId="queue-order" aria-label="Queue order" options={[{value:"oldest",label:"Oldest first"},{value:"newest",label:"Newest first"}]} value={{value:order,label:order==="oldest"?"Oldest first":"Newest first"}} onChange={value=>navigate({...route,order:value?.value||"oldest",page:1,selected:""})}/></Box></Inline>
        <Box as="div" xcss={styles.list} aria-label="Scrollable complaints" ref={(element: HTMLDivElement | null) => { queueList.current=element;if (element) element.scrollTop = queuePosition.current; }} onScroll={(event: React.UIEvent<HTMLDivElement>) => {queuePosition.current = event.currentTarget.scrollTop;}}>{queue.data&&!queue.data.items.length&&<Stack space="space.100"><Text>No complaints match your search and filters.</Text><Inline><Button onClick={()=>{setTypedQuery('');setQuery('');setBranch('');setCategory('');void navigate({...route,status:'pending',page:1,selected:''});}}>Clear search and filters</Button></Inline></Stack>}{queue.data?.items.map(item => <Box key={item.key} xcss={route.selected === item.key ? styles.selectedRow : styles.row}>{route.selected===item.key&&<Box xcss={styles.selectionMarker}/>}<Anchor xcss={styles.itemLink} href={`/staff/app/complaints/cases/${item.key}/?workspace=${route.group}&status=${route.status}&page=${route.page}&order=${order}`} aria-current={route.selected === item.key ? "true" : undefined} onClick={event => { event.preventDefault(); open(item.key); }}><Stack space="space.050"><Inline spread="space-between" space="space.100" alignBlock="start"><Text weight="semibold" maxLines={1}>{item.customer_name || item.reference}</Text><Box xcss={cx(styles.age,item.status!=="CLOSED"&&(item.days_open||0)>=60?styles.ageDanger:item.status!=="CLOSED"&&(item.days_open||0)>=30?styles.ageWarning:undefined)}><Text size="small" weight="semibold" color="inherit">{item.days_open===undefined?item.age_label:item.days_open===0?"Today":`${item.days_open} ${item.days_open===1?"day":"days"}`}</Text></Box></Inline><Box xcss={styles.rowMetadata}><Text size="small" color="color.text.subtle" maxLines={1}>{item.reference} · {item.category||"Type not recorded"} · {item.branch||"Branch not recorded"}</Text><Inline space="space.100" alignBlock="center">{item.hb_comment_count > 0 && <Box as="span" aria-label={`${item.hb_comment_count} HB ${item.hb_comment_count === 1 ? "comment" : "comments"}`}><Text size="small" weight="medium">{item.hb_comment_count} HB {item.hb_comment_count === 1 ? "comment" : "comments"}</Text></Box>}{(route.status!=="pending"||item.status==="REOPENED"||item.needs_details)&&<ComplaintStatus status={item.status} needs={item.needs_details}/>}</Inline></Box></Stack></Anchor></Box>)}</Box>
        {!queue.data && !queue.error && <Box role="status"><Text>Loading complaints…</Text></Box>}
        {queue.data && queue.data.pagination.pages > 1 && <Inline spread="space-between" alignBlock="center" space="space.100"><Text size="small">Page {queue.data.pagination.page} of {queue.data.pagination.pages}</Text><Inline space="space.100"><Button isDisabled={route.page <= 1} onClick={() => navigate({...route, page: route.page - 1, selected: ''})}>Previous</Button><Button isDisabled={route.page >= queue.data.pagination.pages} onClick={() => navigate({...route, page: route.page + 1, selected: ''})}>Next</Button></Inline></Inline>}
      </Box></Box>
      {route.selected&&<Box><Box ref={detailPane} xcss={styles.detailScroll}><Box as="section" aria-label="Complaint detail" xcss={styles.panel} ref={detailPanel} tabIndex={-1}>{detail.data ? <Stack space="space.250">
        <Box xcss={styles.mobileOnly}><Button appearance="subtle" onClick={() => navigate({...route, selected: ''})}>← Back to complaints</Button></Box>
        <Stack space="space.050"><Inline shouldWrap alignBlock="center" space="space.100"><Heading as="h2" size="medium">{detail.data.case.customer_name || detail.data.case.reference}</Heading><ComplaintStatus status={detail.data.case.status} needs={detail.data.case.needs_details}/></Inline><Text size="small" color="color.text.subtle">{detail.data.case.reference}</Text></Stack>
        <Inline shouldWrap spread="space-between" alignBlock="center" space="space.100"><Button iconBefore={CopyIcon} appearance="subtle" onClick={() => { const link=new URL(`/staff/app/complaints/cases/${detail.data!.case.key}/`,window.location.origin);link.searchParams.set("workspace",route.group);void navigator.clipboard.writeText(link.href).then(() => notify("Complaint link copied.","success",{dedupeKey:"copy-link:"+detail.data!.case.key})).catch(() => notify("Copy the link from your address bar.","warning")); }}>Copy link</Button>{queue.data?.navigation&&<Inline alignBlock="center" space="space.050"><IconButton appearance="subtle" label="Previous complaint" icon={PreviousIcon} isDisabled={!queue.data.navigation.previous} onClick={()=>{const item=queue.data!.navigation!.previous;if(item)navigate({...route,selected:item.key,page:item.page});}}/><Text size="small">{queue.data.navigation.position} of {queue.data.navigation.total}</Text><IconButton appearance="subtle" label="Next complaint" icon={NextIcon} isDisabled={!queue.data.navigation.next} onClick={()=>{const item=queue.data!.navigation!.next;if(item)navigate({...route,selected:item.key,page:item.page});}}/></Inline>}</Inline>
        <CaseFacts item={detail.data.case}/>
        {route.view !== 'new' && ownerReady && recovery.bound(bootstrap.data?.continuity_key || '') && <CaseActions slot={slot} key={`${detail.data.case.key}-${detail.data.case.revision}`} group={route.group} item={detail.data.case} categories={bootstrap.data?.categories || []} saved={saved} voiceEnabled={Boolean(bootstrap.data?.voice_input?.enabled)} markDirty={markDirty}/>}
        <Stack xcss={styles.full} space="space.250">
        <Section title="Description"><Box xcss={styles.prewrap}><Text as="p">{detail.data.case.description}</Text></Box></Section>
        <CaseLocation item={detail.data.case}/>
        <Section title="Attachments">{detail.data.case.evidence.length === 0 ? <Text size="small" color="color.text.subtle">No attachments. Files can be added when creating or resolving a complaint.</Text> : <EvidenceGallery key={detail.data.case.key} group={route.group} items={detail.data.case.evidence}/>}</Section>
        <Activity key={`${detail.data.case.key}-${detail.data.case.revision}`} group={route.group} caseKey={detail.data.case.key} initial={detail.data.case.history} next={detail.data.case.history_next_cursor} reported={detail.data.case.recorded_at||''}/>
        </Stack>
      </Stack> : <Text>{route.selected ? 'Loading complaint…' : 'Select a complaint to read its details and activity.'}</Text>}</Box></Box></Box>}
    </Grid>
  </Stack>;
  return <SessionRecheck.Provider value={recheck}><Root><TopNav><TopNavStart sideNavToggleButton={null}><HeaderGutter side="start"/><Text weight="bold" maxLines={1}>JBL workspace</Text></TopNavStart><BrowserActions aligned><ActionMenu label="Workspace tools" icon={SettingsIcon} items={[{label:"Settings",run:()=>navigate({...route,view:"settings"})},{label:"Refresh workspace",run:()=>{if(!pendingSave.current)setRefresh(value=>value+1);}},{label:sync.error?"Sheet sync unavailable":`Sheet sync (${sync.data?.counts.total||0} waiting)`,run:()=>setSyncOpen(true)}]}/><ActionMenu label="Account" heading={bootstrap.data?.actor.name||'Staff account'} icon={PersonIcon} items={[{label:"Sign out",run:async()=>{if(await allowLeave())signOut();}}]}/></BrowserActions></TopNav>
    <Main><Box xcss={styles.canvas}><Box xcss={styles.page} testId="complaints-operations-content"><Stack space="space.200">
      <Inline alignBlock="center" spread="space-between" shouldWrap space="space.150"><Stack space="space.050"><Heading as="h1" size="medium">{route.view === 'settings' ? 'Complaint settings' : 'Complaints'}</Heading></Stack><Inline shouldWrap alignBlock="center" space="space.100">{capabilities.includes('complaint.case.create') && route.view !== 'settings' && <ActionButton aria-label="Create complaint" iconBefore={AddIcon} onClick={() => navigate({...route, view: 'new'})}>New complaint</ActionButton>}</Inline></Inline>
      {groups && groups.length > 1 && <Choice id="workspace" label="Workspace" value={route.group} options={groups.map(item => ({value: item.key, label: item.label}))} onChange={group => navigate({...route, group, selected: '', page: 1})}/>}
      {!online && <Box role="status"><SectionMessage title="You are offline" headingLevel="h2"><Text as="p">You can keep editing. Reconnect before saving; nothing will be submitted automatically.</Text></SectionMessage></Box>}
      {notice && <Box role="status"><Inline spread="space-between" alignBlock="center" space="space.150"><Text weight="medium">{notice}</Text><Button appearance="subtle" onClick={() => setNotice('')}>Dismiss</Button></Inline></Box>}<Feedback error={error} retry={()=>setRefresh(value=>value+1)}/>
      {!bootstrap.data && !error && <Box role="status"><Text>Loading workspace…</Text></Box>}
      {groups?.length === 0 && <SectionMessage title="No Complaints access" headingLevel="h2"><Text>Contact your administrator if you need access.</Text></SectionMessage>}
      {bootstrap.data && preferencesReady && (route.view === 'settings' ? <Stack space="space.250"><Inline><Button appearance="subtle" onClick={() => navigate({...route, view: 'queue'})}>← Back to complaints</Button></Inline><WorkspaceSettings slot={slot} markDirty={markDirty} group={route.group} branches={bootstrap.data.location_options.branches.map(row => row.name)} reports={capabilities.includes('complaint.reports.view')}/></Stack> :
        route.view === 'reports' && !capabilities.includes('complaint.reports.view') ? <SectionMessage title="Reports access required" appearance="warning" headingLevel="h2"><Text>Your current Complaints role does not include reports.</Text><Button onClick={() => navigate({...route, view: 'queue'})}>Back to complaints</Button></SectionMessage> :
        <Tabs id="complaints-destinations" selected={route.view === 'reports' ? 1 : 0} onChange={index => navigate({...route, view: index ? 'reports' : 'queue'})}><Box xcss={styles.tabsBar}><Box xcss={styles.tabs}><TabList><Tab>Queue{queue.data?` · ${queue.data.pagination.total}`:""}</Tab>{capabilities.includes('complaint.reports.view') && <Tab>Reports</Tab>}</TabList></Box>{Boolean(sync.data?.counts.failed)&&<Button iconBefore={CloudIcon} onClick={()=>setSyncOpen(true)}>{sync.data!.counts.failed} sync issues</Button>}</Box><TabPanel>{route.view !== 'reports' && queueView}</TabPanel>{capabilities.includes('complaint.reports.view') && <TabPanel>{route.view === 'reports' && <Reports slot={slot} markDirty={markDirty} group={route.group} refresh={refresh} open={open} location={route.report} change={report => { const next = {...routeRef.current, report}; writeRoute(next, true); setRoute(next); }}/>}</TabPanel>}</Tabs>)}
      {bootstrap.data && ownerReady && recovery.bound(bootstrap.data.continuity_key) && route.view === 'new' && <TaskDialog title="Create complaint" hasStatus close={() => navigate({...route, view: 'queue'})}><Create slot={slot} key={route.group} group={route.group} bootstrap={bootstrap.data} onSaved={saved} cancel={() => navigate({...route, view: 'queue'})} markDirty={markDirty}/></TaskDialog>}
      {syncOpen && <TaskDialog title="Google Sheets sync" size="medium" close={() => setSyncOpen(false)}><Text color="color.text.subtle">Changes are saved in Complaints. Google Sheets updates separately.</Text>{sync.error?<Stack space="space.100"><Text color="color.text.danger">Sheet sync status could not be loaded.</Text><Button onClick={()=>setRefresh(value=>value+1)}>Retry sync status</Button></Stack>:<><Text>{sync.data?.counts.total||0} complaints awaiting sync · {sync.data?.counts.failed||0} need attention</Text>{sync.data?.issues.map(item=><Box key={item.key} xcss={styles.syncRow}><Stack space="space.050"><Text weight="medium">{item.reference} · {item.status==='failed'?'Needs attention':item.status==='suspended'?'Paused':'Waiting'}</Text><Text size="small">{item.status==='failed'?'Open the complaint to review recovery actions.':item.status==='suspended'?'Ask IT to review the Sheet configuration.':'Queued for publication. The complaint is already saved.'}</Text>{item.status_updated_at&&<Text size="small" color="color.text.subtle">Record updated {new Intl.DateTimeFormat('en-GB',{dateStyle:'medium',timeStyle:'short',timeZone:'Africa/Nairobi'}).format(new Date(item.status_updated_at))}</Text>}{item.last_synced_at&&<Text size="small" color="color.text.subtle">Last successful sync {displayDate(item.last_synced_at)}</Text>}</Stack><Button onClick={()=>{setSyncOpen(false);open(item.key);}}>Review complaint</Button></Box>)}{sync.data&&sync.data.counts.total>sync.data.issues.length&&<Text size="small" color="color.text.subtle">Showing the first {sync.data.issues.length} complaints.</Text>}</>}</TaskDialog>}
    </Stack></Box></Box></Main>
  </Root></SessionRecheck.Provider>;
}
