import React, { useCallback, useEffect, useRef, useState } from 'react';
import Button from '@atlaskit/button/default/button';
import { cssMap } from '@atlaskit/css';
import Form, { ErrorMessage, Field, FormFooter, MessageWrapper } from '@atlaskit/form';
import Heading from '@atlaskit/heading';
import { Root } from '@atlaskit/navigation-system/layout/root';
import { Main } from '@atlaskit/navigation-system/layout/main';
import { TopNav, TopNavStart, TopNavMiddle, TopNavEnd } from '@atlaskit/navigation-system/layout/top-nav';
import { Anchor } from '@atlaskit/primitives/compiled/anchor';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Grid } from '@atlaskit/primitives/compiled/grid';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import SectionMessage from '@atlaskit/section-message';
import Textfield from '@atlaskit/textfield';
import { token } from '@atlaskit/tokens';
import { resumeAccess, submit, TransportError, type Action, type AccessState, type Invitation, type Result } from './auth-transport';

// Same documented task composition as DESIGN.md; no scenario/demo navigation.
const styles = cssMap({
  page: { maxWidth: '81rem', marginInline: 'auto', boxSizing: 'border-box', padding: token('space.200'), '@media (min-width: 64rem)': { paddingInline: token('space.400') } },
  enrollmentAccess: { maxWidth: '56.25rem', marginInline: 'auto', minWidth: 0 },
  enrollmentColumns: { '@media (min-width: 64rem)': { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' } },
  codes: { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' },
  qr: { maxWidth: '100%', height: 'auto' },
  secret: { overflowWrap: 'anywhere', font: token('font.code') },
  access: { maxWidth: '31.25rem', marginInline: 'auto', minWidth: 0 },
});
type State = AccessState | 'checking' | 'uncertain';
type Feedback = { title: string; message: string };
const titles: Record<State, string> = {
  checking: 'Checking your session', uncertain: 'Check your session', signed_out: 'Sign in',
  mfa_required: 'Check your authenticator', authenticated: 'Your workspace',
  enrollment_required: 'Set up your authenticator', recovery_codes_required: 'Save your recovery codes',
  reauthentication_required: 'Finish signing in', setup_verify: 'Set up your account', setup_password: 'Create your password',
  setup_codes: 'Save your recovery codes', setup_invalid: 'Reopen your setup invitation',
};
const failureMessages: Record<string, Feedback> = {
  invalid_credentials: { title: 'We could not verify your details', message: 'Check your staff username and password, then try again.' },
  invalid_enrollment_code: { title: 'We could not verify your code', message: 'Enter the current code from the authenticator account you just added.' },
  invalid_code: { title: 'We could not verify your code', message: 'Enter a current authenticator code or an unused recovery code.' },
  rate_limited: { title: 'Please wait before trying again', message: 'Too many attempts. Try again later or contact your administrator.' },
  invalid_password: { title: 'Choose a different password', message: 'Check the guidance below and try again.' },
  setup_invalid: { title: 'This invitation could not be verified', message: 'Reopen your latest setup invitation. If it has expired, ask your administrator for a new one.' },
  enrollment_restart: { title: 'Check your setup', message: 'Continue the current setup below. If it has expired, cancel and sign in again.' },
  session_ended: { title: 'Your session ended', message: 'Sign in again to continue.' },
};

function AccessField({ name, label, password = false, newPassword = false, code = false, numeric = false, autoFocus = false, initialValue = '', serverError }: { name: string; label: string; password?: boolean; newPassword?: boolean; code?: boolean; numeric?: boolean; autoFocus?: boolean; initialValue?: string; serverError?: string }) {
  const limit = password ? 1024 : code ? 32 : 150;
  return <Field<string> name={name} label={label} isRequired defaultValue={initialValue} validate={value => !(password ? value : value?.trim()) ? 'Complete this field.' : value!.length > limit ? `Use ${limit} characters or fewer.` : undefined}>
    {({ fieldProps, error }) => <><Textfield {...fieldProps} isInvalid={Boolean(error || (!fieldProps.value && serverError))} type={password ? 'password' : 'text'} inputMode={numeric ? 'numeric' : undefined} autoComplete={newPassword ? 'new-password' : password ? 'current-password' : code ? 'one-time-code' : 'username'} autoFocus={autoFocus} /><MessageWrapper>{(error || (!fieldProps.value && serverError)) && <ErrorMessage>{error || serverError}</ErrorMessage>}</MessageWrapper></>}
  </Field>;
}

export function StaffAccess({ invitation = null }: { invitation?: Invitation | null }) {
  const [state, setState] = useState<State>('checking');
  const invitationRef = useRef(invitation);
  const [details, setDetails] = useState<Pick<Result, 'enrollment' | 'codes' | 'setupId' | 'fieldErrors'>>({});
  const [copied, setCopied] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [busy, setBusy] = useState(false);
  const [recovery, setRecovery] = useState(false);
  const [formEpoch, setFormEpoch] = useState(0);
  const [username, setUsername] = useState('');
  const pending = useRef<AbortController | null>(null);
  const pendingKind = useRef<'read' | 'write' | null>(null);
  const generation = useRef(0);
  const currentState = useRef<State>('checking');

  const run = useCallback(async (action?: Action, values: Record<string, string> = {}, quiet = false) => {
    if (pending.current) {
      if (!action || pendingKind.current === 'write') return;
      // A background read must never swallow an explicit sign-out/action.
      pending.current.abort();
    }
    const controller = new AbortController();
    const current = ++generation.current;
    pending.current = controller;
    pendingKind.current = action ? 'write' : 'read';
    if (action === 'login') setUsername(values.username);
    if (action === 'setup/verify-email' && invitationRef.current) {
      invitationRef.current.confirmation_key = ''; invitationRef.current.setup_id = ''; invitationRef.current = null;
    }
    setDetails(previous => ({ setupId: previous.setupId })); setCopied(false);
    if (!quiet) {
      setBusy(true); setFeedback(null); setFormEpoch(value => value + 1);
      if (!action || action === 'logout' || action.startsWith('enrollment/') || action.startsWith('setup/')) setState('checking');
    }
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const result = action ? await submit(action, values, controller.signal) : await resumeAccess(controller.signal, invitationRef.current);
      if (current !== generation.current) return;
      setState(result.state);
      setDetails({ enrollment: result.enrollment, codes: result.codes, setupId: result.setupId, fieldErrors: result.fieldErrors });
      if (result.username) setUsername(result.username);
      if (result.failure) setFeedback({ ...(failureMessages[result.failure] || failureMessages.session_ended), ...(result.retryAfter ? { message: `Try again in ${result.retryAfter} seconds or contact your administrator.` } : {}) });
      if (result.state !== 'mfa_required') setRecovery(false);
    } catch (error) {
      if (current !== generation.current) return;
      setDetails({}); setState('uncertain');
      setFeedback({ title: error instanceof TransportError && error.kind === 'csrf' ? 'Your request could not be verified' : 'We could not confirm your session', message: 'Check your session before trying again. Your previous request will not be sent again automatically.' });
    } finally {
      clearTimeout(timeout);
      if (current === generation.current) { pending.current = null; pendingKind.current = null; setBusy(false); }
    }
  }, []);

  useEffect(() => {
    void run();
    const hide = () => {
      ++generation.current; pending.current?.abort(); pending.current = null; pendingKind.current = null;
      if (invitationRef.current) { invitationRef.current.confirmation_key = ''; invitationRef.current.setup_id = ''; invitationRef.current = null; }
      setDetails({}); setCopied(false);
      setBusy(false); setState('checking'); setFeedback(null); setFormEpoch(value => value + 1);
    };
    const visibility = () => { if (document.visibilityState === 'hidden') hide(); else void run(); };
    const restore = (event: PageTransitionEvent) => { if (event.persisted) { hide(); void run(); } };
    const poll = setInterval(() => { if (document.visibilityState === 'visible' && currentState.current === 'authenticated' && !pending.current) void run(undefined, {}, true); }, 30000);
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener('pageshow', restore);
    return () => { ++generation.current; pending.current?.abort(); pending.current = null; pendingKind.current = null; clearInterval(poll); document.removeEventListener('visibilitychange', visibility); window.removeEventListener('pageshow', restore); };
  }, [run]);

  useEffect(() => {
    currentState.current = state;
    document.title = `${titles[state]} - JBL staff access`;
    if (state !== 'checking') (document.querySelector<HTMLInputElement>('[data-testid="auth-content"] input') || document.getElementById('access-heading'))?.focus();
  }, [state]);
  const routineForm = state === 'signed_out' || state === 'mfa_required';
  const enrollmentForm = state === 'enrollment_required';
  const passwordForm = state === 'setup_password';
  const form = routineForm || enrollmentForm || passwordForm;
  const title = state === 'mfa_required' && recovery ? 'Use a recovery code' : titles[state];
  const cancelSetup = () => {
    if (passwordForm || state === 'setup_verify') {
      // Leaving an anonymous task clears local proof, while preserving the
      // verified bound server progress so Cancel does not strand first setup.
      if (invitationRef.current) { invitationRef.current.confirmation_key = ''; invitationRef.current.setup_id = ''; invitationRef.current = null; }
      setDetails(previous => ({ setupId: previous.setupId })); setFeedback(null);
      setFormEpoch(value => value + 1); setState('signed_out');
    } else void run('logout', {});
  };
  const cancel = <Inline><Button appearance="subtle" onClick={cancelSetup}>Cancel setup</Button></Inline>;
  const copyCodes = async () => {
    try { await navigator.clipboard.writeText(details.codes!.join('\n')); setCopied(true); }
    catch { setFeedback({ title: 'Copy was unavailable', message: 'Select the codes below and save them in your password manager.' }); }
  };
  return <Root>
    <TopNav><TopNavStart sideNavToggleButton={null}><Text weight="bold">JBL Staff workspace</Text></TopNavStart><TopNavMiddle>{null}</TopNavMiddle>{state === 'authenticated' && <TopNavEnd><Button onClick={() => void run('logout', {})} isLoading={busy}>Sign out</Button></TopNavEnd>}</TopNav>
    <Main id="content" testId="auth-content" skipLinkLabel="Page content"><Box xcss={styles.page}><Box as="section" aria-labelledby="access-heading" aria-busy={busy} xcss={details.enrollment ? styles.enrollmentAccess : styles.access}><Stack space="space.150">
      <Box id="access-heading" tabIndex={-1}><Heading as="h1" size="large">{title}</Heading></Box>
      {feedback && <Box role="alert"><SectionMessage title={feedback.title} appearance="error" headingLevel="h2"><Text as="p">{feedback.message}</Text></SectionMessage></Box>}
      {state === 'checking' && <Box role="status"><Text as="p">Checking access with the company service.</Text></Box>}
      {state === 'uncertain' && <Button appearance="primary" onClick={() => void run()} isLoading={busy}>Check session</Button>}
      {state === 'signed_out' && details.setupId && <Button onClick={() => void run()}>Continue account setup</Button>}
      {state === 'setup_verify' && <><Text as="p">Continue to verify your invitation and create a password for your existing staff account.</Text>{cancel}<Button appearance="primary" isLoading={busy} onClick={() => { const proof = invitationRef.current; if (proof) void run('setup/verify-email', { ...proof }); }}>Continue setup</Button></>}
      {form && <>
        <Text as="p">{state === 'signed_out' ? 'Use your existing staff account to continue.' : passwordForm ? 'Choose a strong, unique password. Your password manager can create and save it.' : enrollmentForm ? details.enrollment ? 'Scan this QR code with your authenticator app, then enter its code.' : 'Confirm your password to continue authenticator setup.' : recovery ? 'Each recovery code can only be used once.' : 'Enter the current code from your authenticator app.'}</Text>
        {state === 'mfa_required' && <Inline space="space.100" shouldWrap><Button appearance="subtle" onClick={() => { setRecovery(value => !value); setFormEpoch(value => value + 1); }}>{recovery ? 'Use your authenticator' : 'Use a recovery code'}</Button><Button appearance="subtle" onClick={() => void run('logout', {})}>Cancel sign in</Button></Inline>}
        {(enrollmentForm || passwordForm) && cancel}
        <Grid gap="space.300" xcss={details.enrollment ? styles.enrollmentColumns : undefined}>
        {enrollmentForm && details.enrollment && <Stack space="space.100"><Box as="img" src={details.enrollment.qr} alt="Scan with your authenticator app" width={192} height={192} xcss={styles.qr} data-sensitive="true" /><Text as="p" size="small">On this phone, add a time-based account in your authenticator using this setup key:</Text><Box as="code" xcss={styles.secret} data-sensitive="true">{new URL(details.enrollment.uri).searchParams.get('secret')}</Box></Stack>}
        <Box><Text as="p" size="small">Required fields are marked with an asterisk *</Text>
        <Form key={formEpoch} label={title} onSubmit={(values: Record<string, string>) => run(passwordForm ? 'setup/password' : enrollmentForm ? details.enrollment ? 'enrollment/confirm' : 'enrollment/begin' : state === 'signed_out' ? 'login' : 'mfa', { ...values, ...(passwordForm ? { setup_id: details.setupId! } : {}) })}>
          {state === 'signed_out' ? <><AccessField name="username" label="Staff username" initialValue={username} autoFocus /><AccessField name="password" label="Password" password /></> : passwordForm ? <><AccessField name="password1" label="New password" password newPassword autoFocus serverError={details.fieldErrors?.password1} /><AccessField name="password2" label="Confirm password" password newPassword serverError={details.fieldErrors?.password2} /></> : enrollmentForm && !details.enrollment ? <AccessField name="password" label="Password" password autoFocus /> : <AccessField name="code" label={recovery && !enrollmentForm ? 'Recovery code' : 'Authenticator code'} code numeric={enrollmentForm || !recovery} autoFocus />}
          <FormFooter><Button type="submit" appearance="primary" shouldFitContainer isLoading={busy}>{state === 'signed_out' ? 'Sign in' : passwordForm ? 'Create password and continue' : enrollmentForm && !details.enrollment ? 'Continue setup' : 'Verify'}</Button></FormFooter>
        </Form></Box></Grid>
      </>}
      {state === 'recovery_codes_required' && <><Text as="p">Your authenticator is ready. Show your recovery codes once and save them before signing in.</Text>{cancel}<Button appearance="primary" isLoading={busy} onClick={() => void run('enrollment/recovery-codes')}>Show recovery codes</Button></>}
      {state === 'setup_codes' && details.codes && <><Text as="p">Save these one-use codes in your password manager. You can use one if your authenticator is unavailable. They will not be shown again.</Text><Grid xcss={styles.codes} gap="space.100"><>{details.codes.map(code => <Box as="code" key={code} xcss={styles.secret} data-sensitive="true">{code}</Box>)}</></Grid><Inline space="space.100"><Button onClick={() => void copyCodes()}>Copy codes</Button>{copied && <Box role="status"><Text>Codes copied</Text></Box>}</Inline><Button appearance="primary" isLoading={busy} onClick={() => void run('logout', {})}>I saved my codes - sign in</Button></>}
      {state === 'reauthentication_required' && <><SectionMessage title="Continue with your authenticator" headingLevel="h2"><Text as="p">Recovery codes have already been shown. Sign in with your password and authenticator. If you did not save your recovery codes, contact your administrator.</Text></SectionMessage><Button appearance="primary" isLoading={busy} onClick={() => void run('logout', {})}>Continue to sign in</Button></>}
      {state === 'setup_invalid' && <>{!feedback && <Text as="p">Use the latest invitation from your company administrator. If it has expired, ask for a new invitation.</Text>}<Button appearance="primary" isLoading={busy} onClick={() => void run('logout', {})}>Back to sign in</Button></>}
      {state === 'authenticated' && <SectionMessage title="Sign-in complete" headingLevel="h2"><Text as="p">Your company identity is confirmed. Workflow tools are not enabled in this closed client.</Text></SectionMessage>}
      {(form || state === 'uncertain') && <Text as="p" size="small" color="color.text.subtle">Trouble signing in? Contact your company administrator. Never share passwords or codes.</Text>}
      <Box as="footer"><Anchor href="/THIRD_PARTY_NOTICES.txt">Open-source notices</Anchor></Box>
    </Stack></Box></Box></Main>
  </Root>;
}
