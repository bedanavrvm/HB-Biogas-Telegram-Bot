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
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import SectionMessage from '@atlaskit/section-message';
import Textfield from '@atlaskit/textfield';
import { token } from '@atlaskit/tokens';
import { checkSession, submit, TransportError, type Action, type SessionState } from './auth-transport';

// Same documented task composition as DESIGN.md; no scenario/demo navigation.
const styles = cssMap({
  page: { maxWidth: '81rem', marginInline: 'auto', boxSizing: 'border-box', padding: token('space.200'), '@media (min-width: 64rem)': { paddingInline: token('space.400') } },
  access: { maxWidth: '31.25rem', marginInline: 'auto', minWidth: 0 },
});
type State = SessionState | 'checking' | 'uncertain';
type Feedback = { title: string; message: string };
const titles: Record<State, string> = {
  checking: 'Checking your session', uncertain: 'Check your session', signed_out: 'Sign in',
  mfa_required: 'Check your authenticator', authenticated: 'Your workspace',
  enrollment_required: 'Authenticator setup required', recovery_codes_required: 'Finish saving your recovery codes',
  reauthentication_required: 'Sign in again',
};
const failureMessages = {
  invalid_credentials: { title: 'We could not verify your details', message: 'Check your staff username and password, then try again.' },
  invalid_code: { title: 'We could not verify your code', message: 'Enter a current authenticator code or an unused recovery code.' },
  rate_limited: { title: 'Please wait before trying again', message: 'Too many attempts. Try again later or contact your administrator.' },
  session_ended: { title: 'Your session ended', message: 'Sign in again to continue.' },
};

function AccessField({ name, label, password = false, code = false, autoFocus = false, initialValue = '' }: { name: string; label: string; password?: boolean; code?: boolean; autoFocus?: boolean; initialValue?: string }) {
  const limit = password ? 1024 : code ? 32 : 150;
  return <Field<string> name={name} label={label} isRequired defaultValue={initialValue} validate={value => !(password ? value : value?.trim()) ? 'Complete this field.' : value!.length > limit ? `Use ${limit} characters or fewer.` : undefined}>
    {({ fieldProps, error }) => <><Textfield {...fieldProps} type={password ? 'password' : 'text'} autoComplete={password ? 'current-password' : code ? 'one-time-code' : 'username'} autoFocus={autoFocus} /><MessageWrapper>{error && <ErrorMessage>{error}</ErrorMessage>}</MessageWrapper></>}
  </Field>;
}

export function StaffAccess() {
  const [state, setState] = useState<State>('checking');
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
    if (action === 'logout') setUsername('');
    if (!quiet) {
      setBusy(true); setFeedback(null); setFormEpoch(value => value + 1);
      if (!action || action === 'logout') setState('checking');
    }
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const result = action ? await submit(action, values, controller.signal) : await checkSession(controller.signal);
      if (current !== generation.current) return;
      setState(result.state);
      if (result.failure) setFeedback({ ...failureMessages[result.failure], ...(result.retryAfter ? { message: `Try again in ${result.retryAfter} seconds or contact your administrator.` } : {}) });
      if (result.state !== 'mfa_required') setRecovery(false);
    } catch (error) {
      if (current !== generation.current) return;
      setState('uncertain');
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
  const support = ['enrollment_required', 'recovery_codes_required', 'reauthentication_required'].includes(state);
  const form = state === 'signed_out' || state === 'mfa_required';
  return <Root>
    <TopNav><TopNavStart sideNavToggleButton={null}><Text weight="bold">JBL Staff workspace</Text></TopNavStart><TopNavMiddle>{null}</TopNavMiddle>{state === 'authenticated' && <TopNavEnd><Button onClick={() => void run('logout', {})} isLoading={busy}>Sign out</Button></TopNavEnd>}</TopNav>
    <Main id="content" testId="auth-content" skipLinkLabel="Page content"><Box xcss={styles.page}><Box as="section" aria-labelledby="access-heading" aria-busy={busy} xcss={styles.access}><Stack space="space.150">
      <Box id="access-heading" tabIndex={-1}><Heading as="h1" size="large">{state === 'mfa_required' && recovery ? 'Use a recovery code' : titles[state]}</Heading></Box>
      {feedback && <Box role="alert"><SectionMessage title={feedback.title} appearance="error" headingLevel="h2"><Text as="p">{feedback.message}</Text></SectionMessage></Box>}
      {state === 'checking' && <Text as="p" role="status">Checking access with the company service.</Text>}
      {state === 'uncertain' && <Button appearance="primary" onClick={() => void run()} isLoading={busy}>Check session</Button>}
      {form && <>
        <Text as="p">{state === 'signed_out' ? 'Use your existing staff account to continue.' : recovery ? 'Each recovery code can only be used once.' : 'Enter the current code from your authenticator app.'}</Text>
        {state === 'mfa_required' && <Inline space="space.100" shouldWrap><Button appearance="subtle" onClick={() => { setRecovery(value => !value); setFormEpoch(value => value + 1); }}>{recovery ? 'Use your authenticator' : 'Use a recovery code'}</Button><Button appearance="subtle" onClick={() => void run('logout', {})}>Cancel sign in</Button></Inline>}
        <Text as="p" size="small">Required fields are marked with an asterisk *</Text>
        <Form key={formEpoch} label={state === 'signed_out' ? 'Staff sign-in' : 'Verify your code'} onSubmit={(values: Record<string, string>) => run(state === 'signed_out' ? 'login' : 'mfa', values)}>
          {state === 'signed_out' ? <><AccessField name="username" label="Staff username" initialValue={username} autoFocus /><AccessField name="password" label="Password" password /></> : <AccessField name="code" label={recovery ? 'Recovery code' : 'Authenticator code'} code autoFocus />}
          <FormFooter><Button type="submit" appearance="primary" shouldFitContainer isLoading={busy}>{state === 'signed_out' ? 'Sign in' : 'Verify'}</Button></FormFooter>
        </Form>
      </>}
      {state === 'authenticated' && <SectionMessage title="Sign-in complete" headingLevel="h2"><Text as="p">Your company identity is confirmed. Workflow tools are not enabled in this closed client.</Text></SectionMessage>}
      {support && <><SectionMessage title="Administrator assistance required" appearance="warning" headingLevel="h2"><Text as="p">Contact your company administrator through your usual support channel to complete setup. This client does not change your authenticator or show recovery codes.</Text></SectionMessage><Button appearance="primary" onClick={() => void run('logout', {})} isLoading={busy}>Sign out</Button></>}
      {(form || state === 'uncertain') && <Text as="p" size="small" color="color.text.subtle">Trouble signing in? Contact your company administrator. Never share passwords or codes.</Text>}
      <Box as="footer"><Anchor href="/THIRD_PARTY_NOTICES.txt">Open-source notices</Anchor></Box>
    </Stack></Box></Box></Main>
  </Root>;
}
