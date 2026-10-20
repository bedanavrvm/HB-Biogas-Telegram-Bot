import React, { useEffect, useRef, useState } from 'react';
import Button from '@atlaskit/button/default/button';
import { cssMap } from '@atlaskit/css';
import Form, { ErrorMessage, Field, FormFooter, Label, MessageWrapper } from '@atlaskit/form';
import Heading from '@atlaskit/heading';
import { Root } from '@atlaskit/navigation-system/layout/root';
import { Main } from '@atlaskit/navigation-system/layout/main';
import { TopNav, TopNavStart } from '@atlaskit/navigation-system/layout/top-nav';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Grid } from '@atlaskit/primitives/compiled/grid';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import SectionMessage from '@atlaskit/section-message';
import Select from '@atlaskit/select';
import Textfield from '@atlaskit/textfield';
import { token } from '@atlaskit/tokens';
import { demoJSON, DemoError, encodeFiles, evidenceBlob, exampleFile, type DemoCase, type DemoContext, type Evidence, type Saved } from './complaints-demo-api';

const styles = cssMap({
  page: { width: '100%', maxWidth: '81rem', marginInline: 'auto', boxSizing: 'border-box', padding: token('space.200'), '@media (min-width: 64rem)': { paddingInline: token('space.400') } },
  columns: { gridTemplateColumns: 'repeat(1, minmax(0, 1fr))', alignItems: 'start', '@media (min-width: 64rem)': { gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)' } },
  panel: { padding: token('space.200'), borderStyle: 'solid', borderWidth: token('border.width'), borderColor: token('color.border'), borderRadius: token('radius.medium'), minWidth: 0, overflowWrap: 'anywhere' },
  image: { maxWidth: '100%', maxHeight: '16rem', objectFit: 'contain' },
});

function Input({ name, label, value = '', error: serverError, numeric = false, onValue }: { name: string; label: string; value?: string; error?: string; numeric?: boolean; onValue?: (value: string) => void }) {
  return <Field<string> name={name} label={label} defaultValue={value} isRequired validate={input => !input?.trim() ? 'Complete this field.' : input.length > 5000 ? 'Use 5,000 characters or fewer.' : name === 'customer_id' && !/^\d+$/.test(input.trim()) ? 'Use digits only.' : name === 'customer_phone' && !/^(?:\+?254|0)[17]\d{8}$/.test(input.replace(/[\s()-]/g, '')) ? 'Enter a valid Kenyan mobile number.' : undefined}>
    {({ fieldProps, error }) => <><Textfield {...fieldProps} onChange={event => { const value = event.currentTarget.value; fieldProps.onChange(event); onValue?.(value); }} inputMode={numeric ? 'numeric' : undefined} autoComplete="off" isInvalid={Boolean(error || serverError)} /><MessageWrapper>{(error || serverError) && <ErrorMessage>{error || serverError}</ErrorMessage>}</MessageWrapper></>}
  </Field>;
}

function Feedback({ error }: { error: Error | null }) {
  return error ? <Box role="alert"><SectionMessage title={error instanceof DemoError && error.status === 409 ? 'Review the latest case' : 'Could not save this action'} appearance="error" headingLevel="h3"><Text as="p">{error.message}</Text></SectionMessage></Box> : null;
}

export function FilePicker({ role, files, setFiles, busy = false }: { role: string; files: File[]; setFiles: (files: File[]) => void; busy?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<Error | null>(null);
  return <Stack space="space.100">
    <Text weight="medium">Evidence files</Text>
    <Text size="small" color="color.text.subtle">JPEG, PNG, WebP or PDF. Up to ten files, 10 MB each. Demo uploads stay in memory until reset or restart.</Text>
    <Box as="input" ref={input} type="file" hidden multiple accept=".jpg,.jpeg,.png,.webp,.pdf" aria-label="Choose evidence files" onChange={event => { setFiles([...files, ...Array.from(event.currentTarget.files || [])]); event.currentTarget.value = ''; setError(null); }} />
    <Inline space="space.100" shouldWrap><Button isDisabled={busy} onClick={() => input.current?.click()}>Choose files</Button><Button appearance="subtle" isDisabled={busy} onClick={() => { void exampleFile(role).then(file => setFiles([...files, file])).catch(failure => setError(failure as Error)); }}>Use sample image</Button></Inline>
    {files.map((file, index) => <Inline key={index} spread="space-between" alignBlock="center" shouldWrap space="space.100"><Text size="small">{file.name} ({Math.max(1, Math.round(file.size / 1024))} KB)</Text><Button appearance="subtle" isDisabled={busy} onClick={() => setFiles(files.filter((_, item) => item !== index))} aria-label={`Remove ${file.name}`}>Remove</Button></Inline>)}
    <Feedback error={error} />
  </Stack>;
}

function Attachment({ role, item }: { role: string; item: Evidence }) {
  const [preview, setPreview] = useState('');
  const [error, setError] = useState<Error | null>(null);
  const pending = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);
  const open = async () => {
    if (pending.current) return;
    pending.current = true; setError(null);
    try {
      const blob = await evidenceBlob(role, item.key);
      if (!mounted.current) return;
      const url = URL.createObjectURL(blob);
      if (item.type.startsWith('image/')) setPreview(url);
      else { const anchor = document.createElement('a'); anchor.href = url; anchor.download = item.name; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
    } catch (failure) { setError(failure as Error); }
    finally { pending.current = false; }
  };
  return <Stack space="space.100"><Inline spread="space-between" alignBlock="center" shouldWrap space="space.100"><Stack space="space.050"><Text>{item.name}</Text><Text size="small" color="color.text.subtle">{Math.max(1, Math.round(item.size / 1024))} KB · {item.uploaded_by}</Text></Stack><Button onClick={() => void open()}>{item.type.startsWith('image/') ? 'View image' : 'Download PDF'}</Button></Inline>
    {preview && <><Box as="img" xcss={styles.image} src={preview} alt={`Uploaded evidence: ${item.name}`} /><Inline><Button appearance="subtle" onClick={() => setPreview('')}>Close image</Button></Inline></>}
    <Feedback error={error} />
  </Stack>;
}

export function CaseActions({ role, item, onSaved, setBusy }: { role: string; item: DemoCase; onSaved: (result: Saved) => void; setBusy: (busy: boolean) => void }) {
  const [expanded, setExpanded] = useState(false);
  const [action, setAction] = useState(item.actions[0]?.value || '');
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<Error | null>(null);
  const [busy, localBusy] = useState(false);
  const [sampleDetails, setSampleDetails] = useState(false);
  const request = useRef(crypto.randomUUID());
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => { controller.current?.abort(); }, []);
  const fields = error instanceof DemoError ? error.fields : {};
  const submit = async (values: Record<string, string>) => {
    if (controller.current) return;
    const abort = new AbortController(); controller.current = abort;
    const timeout = setTimeout(() => abort.abort(), 20000);
    localBusy(true); setBusy(true); setError(null);
    try {
      const result = await demoJSON<Saved>(role, `groups/${item.group}/cases/${item.key}/${action}/`, { signal: abort.signal, body: { request_key: request.current, epoch: item.epoch, revision: item.revision, fields: values, files: await encodeFiles(files) } });
      onSaved(result);
    } catch (failure) { setError(failure instanceof DemoError ? failure : new Error('The request could not be confirmed. Refresh the case before retrying; your draft has been retained.')); }
    finally { clearTimeout(timeout); controller.current = null; localBusy(false); setBusy(false); }
  };
  return <Stack space="space.150">
    <Inline spread="space-between" alignBlock="center" shouldWrap space="space.100"><Heading as="h3" size="small">Evidence ({item.evidence.length})</Heading>{item.actions.length > 0 && !expanded && <Button appearance="primary" onClick={() => setExpanded(true)}>Take action</Button>}</Inline>
    {item.evidence.map(evidence => <Attachment key={evidence.key} role={role} item={evidence} />)}
    {expanded && <Stack space="space.100"><Heading as="h3" size="small">Update complaint</Heading>
      <Text size="small" color="color.text.subtle">Phone: {item.customer_phone || 'Missing'} · National ID: {item.customer_id || 'Missing'} · {item.village}</Text>
      {item.source && <Text size="small" color="color.text.subtle">Confidential source: {item.source}</Text>}
      <Box><Label htmlFor="demo-case-action">Action</Label><Select inputId="demo-case-action" options={item.actions} value={item.actions.find(option => option.value === action)} isDisabled={busy} onChange={option => { setAction(option?.value || ''); setError(null); setFiles([]); request.current = crypto.randomUUID(); }} /></Box>
      <Feedback error={error} />
      <Form<Record<string, string>> key={`${action}-${sampleDetails}`} onSubmit={submit}>{({ formProps }) => <Box as="form" {...formProps}>
        <Stack space="space.100">
          {action !== 'upload' && <Text size="small">Required fields are marked with an asterisk *</Text>}
          {action === 'complete' ? <><Inline><Button appearance="subtle" onClick={() => setSampleDetails(true)}>Fill sample identifiers</Button></Inline><Input name="customer_phone" label="Primary phone number" value={item.customer_phone || (sampleDetails ? '0700000099' : '')} error={fields.customer_phone} /><Input name="customer_id" label="Customer National ID" value={item.customer_id || (sampleDetails ? '90000099' : '')} numeric error={fields.customer_id} /></> : action === 'upload' ? <FilePicker role={role} files={files} setFiles={setFiles} busy={busy} /> : <Input name="note" label={action === 'comment' ? 'Resolution comment' : action === 'resolve' ? 'Resolution note' : 'Reason for reopening'} error={fields.note} />}
        </Stack>
        <FormFooter><Button appearance="subtle" isDisabled={busy} onClick={() => { setExpanded(false); setError(null); }}>Cancel</Button><Button appearance="primary" type="submit" isLoading={busy}>{action === 'resolve' ? 'Resolve complaint' : action === 'reopen' ? 'Reopen complaint' : action === 'upload' ? 'Upload evidence' : action === 'complete' ? 'Save missing details' : 'Save comment'}</Button></FormFooter>
      </Box>}</Form>
    </Stack>}
  </Stack>;
}

export function CreateComplaint({ role, context, toolbar, onCancel, onSaved, setBusy }: { role: string; context: DemoContext; toolbar: React.ReactNode; onCancel: () => void; onSaved: (result: Saved) => void; setBusy: (value: boolean) => void }) {
  const [step, setStep] = useState(1);
  const [customer, setCustomer] = useState<Record<string, string>>({});
  const [draft, setDraft] = useState({ village: 'Sample service area', description: 'Gas output is low despite normal feeding. Please arrange a service inspection.' });
  const [group, setGroup] = useState(context.groups[0]?.key || '1');
  const [branch, setBranch] = useState('Nakuru');
  const [category, setCategory] = useState(context.categories[0]);
  const [files, setFiles] = useState<File[]>([]);
  const [epoch, setEpoch] = useState(0);
  const [error, setError] = useState<Error | null>(null);
  const [busy, localBusy] = useState(false);
  const request = useRef(crypto.randomUUID());
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  const location = context.locations.find(item => item.branch === branch)!;
  const fieldErrors = error instanceof DemoError ? error.fields : {};
  const submit = async (values: Record<string, string>) => {
    if (step === 1) { setCustomer(values); setStep(2); setError(null); return; }
    if (pending.current) return;
    const abort = new AbortController(); pending.current = abort;
    const timeout = setTimeout(() => abort.abort(), 20000);
    setBusy(true); localBusy(true); setError(null);
    try {
      const result = await demoJSON<Saved>(role, `groups/${group}/cases/`, { signal: abort.signal, body: { request_key: request.current, epoch: context.epoch, fields: { ...customer, ...values, branch, category }, files: await encodeFiles(files) } });
      onSaved(result);
    } catch (failure) { setError(failure instanceof DemoError ? failure : new Error('The request could not be confirmed. Your draft is retained; retry uses the same request key.')); }
    finally { clearTimeout(timeout); pending.current = null; setBusy(false); localBusy(false); }
  };
  return <Root><TopNav><TopNavStart sideNavToggleButton={null}><Text weight="bold">JBL Staff workspace · Local demo</Text></TopNavStart></TopNav>
    <Main><Box xcss={styles.page}><Stack space="space.200">
      <Heading as="h1" size="large">New complaint</Heading>{toolbar}
      <Form<Record<string, string>> key={`${step}-${epoch}`} onSubmit={submit}>{({ formProps }) => <Box as="form" {...formProps}>
      <Grid xcss={styles.columns} gap="space.300">
        <Box xcss={styles.panel}><Stack space="space.150">
          <Heading as="h2" size="medium">{step === 1 ? 'Customer details' : 'Complaint and evidence'}</Heading>
          <Text size="small">Step {step} of 2 · Required fields are marked with an asterisk *</Text>
          <Feedback error={error} />
            {step === 1 ? <><Inline><Button appearance="subtle" onClick={() => { setCustomer({ customer_name: 'Sample Farmer — Demo intake', customer_phone: '0700000099', customer_id: '90000099' }); setEpoch(value => value + 1); }}>Fill sample customer</Button></Inline><Input name="customer_name" label="Customer name" value={customer.customer_name} error={fieldErrors.customer_name} /><Input name="customer_phone" label="Primary phone number" value={customer.customer_phone} error={fieldErrors.customer_phone} /><Input name="customer_id" label="Customer National ID" value={customer.customer_id} numeric error={fieldErrors.customer_id} /></> : <Stack space="space.100">
              <Grid xcss={styles.columns} gap="space.150">{context.groups.length > 1 && <Box><Label htmlFor="demo-create-group">Workspace</Label><Select inputId="demo-create-group" options={context.groups.map(item => ({ value: item.key, label: item.label }))} value={{ value: group, label: context.groups.find(item => item.key === group)!.label }} onChange={option => { const next = option?.value || '1'; setGroup(next); setBranch(next === '2' ? 'Kericho' : 'Nakuru'); }} /></Box>}
              <Box><Label htmlFor="demo-create-branch">Branch</Label><Select inputId="demo-create-branch" options={context.locations.filter(item => group === '2' ? item.branch === 'Kericho' : item.branch !== 'Kericho').map(item => ({ value: item.branch, label: item.branch }))} value={{ value: branch, label: branch }} onChange={option => setBranch(option?.value || 'Nakuru')} /></Box>
              </Grid><Text size="small" color="color.text.subtle">{location.county} County · {location.constituency} Constituency</Text>
              <Box><Label htmlFor="demo-create-category">Category</Label><Select inputId="demo-create-category" options={context.categories.map(value => ({ value, label: value }))} value={{ value: category, label: category }} onChange={option => setCategory(option?.value || context.categories[0])} /></Box>
              <Input name="village" label="Village or nearby landmark" value={draft.village} error={fieldErrors.village} onValue={village => setDraft(previous => ({ ...previous, village }))} /><Input name="description" label="Complaint description" value={draft.description} error={fieldErrors.description} onValue={description => setDraft(previous => ({ ...previous, description }))} />
            </Stack>}
        </Stack></Box>
        <Box xcss={styles.panel}><Stack space="space.150"><Heading as="h2" size="small">{step === 1 ? 'Complaint handoff' : 'Customer and evidence'}</Heading>{customer.customer_name && <Text weight="medium">{customer.customer_name}</Text>}<Text>{context.actor} records the complaint. An HB Resolver adds feedback and resolves it; a Manager can reopen it.</Text>{step === 2 && <FilePicker role={role} files={files} setFiles={setFiles} busy={busy} />}<Text size="small" color="color.text.subtle">Use sample data. Entered details and attachments remain in this local demo until Reset demo or server restart.</Text></Stack></Box>
      </Grid>
      <FormFooter><Button appearance="subtle" isDisabled={busy} onClick={step === 1 ? onCancel : () => setStep(1)}>{step === 1 ? 'Cancel' : 'Back'}</Button><Button appearance="primary" type="submit" isLoading={busy}>{step === 1 ? 'Continue' : 'Record complaint'}</Button></FormFooter>
      </Box>}</Form>
    </Stack></Box></Main>
  </Root>;
}
