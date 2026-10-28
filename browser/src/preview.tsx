import React, { useEffect, useRef, useState } from 'react';
import Button from '@atlaskit/button/default/button';
import LinkButton from '@atlaskit/button/link';
import { cssMap, cx } from '@atlaskit/css';
import Form, { Field, FormFooter, Label } from '@atlaskit/form';
import Heading from '@atlaskit/heading';
import { Root } from '@atlaskit/navigation-system/layout/root';
import { Main } from '@atlaskit/navigation-system/layout/main';
import { TopNav, TopNavStart, TopNavMiddle, TopNavEnd } from '@atlaskit/navigation-system/layout/top-nav';
import { SideNav, SideNavHeader, SideNavBody, SideNavFooter, SideNavToggleButton } from '@atlaskit/navigation-system/layout/side-nav';
import { Anchor } from '@atlaskit/primitives/compiled/anchor';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Grid } from '@atlaskit/primitives/compiled/grid';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import SectionMessage from '@atlaskit/section-message';
import Select from '@atlaskit/select';
import { LinkMenuItem } from '@atlaskit/side-nav-items/link-menu-item';
import { MenuList } from '@atlaskit/side-nav-items/menu-list';
import { MenuSection, MenuSectionHeading } from '@atlaskit/side-nav-items/menu-section';
import Textfield from '@atlaskit/textfield';
import { token } from '@atlaskit/tokens';
import VisuallyHidden from '@atlaskit/visually-hidden';
import { useSetColorMode } from '@atlaskit/app-provider/use-set-color-mode';

// Official references and application-specific decisions: browser/DESIGN.md.
const styles = cssMap({
  page: { maxWidth: '81rem', marginInline: 'auto', boxSizing: 'border-box', padding: token('space.200'), '@media (min-width: 64rem)': { paddingInline: token('space.400') } },
  frame: { minWidth: 0 },
  // Keep our one-column template distinct from Root's base atomic class;
  // late development style insertion must not override Root's media rules.
  composition: { gridTemplateColumns: 'repeat(1, minmax(0, 1fr))', alignItems: 'start' },
  reviewComposition: { '@media (min-width: 64rem)': { gridTemplateColumns: 'minmax(0, 1fr) 18rem' } },
  access: { maxWidth: '31.25rem', marginInline: 'auto', minWidth: 0 },
  help: { maxWidth: '48rem' },
  grouping: { padding: token('space.150'), borderRadius: token('radius.small'), backgroundColor: token('color.background.neutral') },
  tile: { padding: token('space.200'), borderRadius: token('radius.medium'), borderStyle: 'solid', borderWidth: token('border.width'), borderColor: token('color.border'), minWidth: 0 },
  tools: { gridTemplateColumns: 'repeat(1, minmax(0, 1fr))', '@media (min-width: 48rem)': { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' } },
  codes: { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' },
  review: { padding: token('space.200'), borderInlineStartStyle: 'solid', borderInlineStartWidth: token('border.width'), borderInlineStartColor: token('color.border'), minWidth: 0 },
  navText: { padding: token('space.150') },
  task: { minWidth: 0 },
});

const pages = ['login', 'setup', 'password', 'mfa', 'enroll', 'scan', 'recovery', 'codes', 'reauthenticate', 'shell', 'help'] as const;
type Page = typeof pages[number];
type Scenario = 'success' | 'invalid' | 'unavailable' | 'limited' | 'expired' | 'enrollment';
type Theme = 'system' | 'light' | 'dark';
const isReview = window.location.pathname === '/review.html';
const isPage = (value: string): value is Page => pages.some(page => page === value);
const pageFromHash = (): Page => {
  const value = window.location.hash.slice(1);
  return isPage(value) && value !== 'codes' ? value : 'login';
};
const titles: Record<Page, string> = {
  login: 'Sign in', setup: 'Verify your setup link', password: 'Create your password',
  mfa: 'Check your authenticator', enroll: 'Set up your authenticator', scan: 'Confirm your authenticator',
  recovery: 'Save your recovery codes', codes: 'Store these somewhere safe',
  reauthenticate: 'You are ready to sign in', shell: 'Your workspace', help: 'Account help',
};
const descriptions: Record<Page, string> = {
  login: 'Use your existing staff account to continue.',
  setup: 'Verify the setup link supplied for your existing staff account.',
  password: 'Create a staff password. Sign in again after setup.',
  mfa: 'Enter the current code from your authenticator app.',
  enroll: 'Confirm your password before adding an authenticator.',
  scan: 'Add your staff account, then enter its authenticator code.',
  recovery: 'Save your codes privately for when you cannot use your authenticator.',
  codes: 'These are invalid demo labels. Real recovery codes are shown only once.',
  reauthenticate: 'Complete a fresh password and authenticator sign-in to continue.',
  shell: 'Open a tool available to your role and scope.',
  help: 'Contact your company administrator through your usual support channel.',
};
const errors: Partial<Record<Scenario, [string, string]>> = {
  invalid: ['We could not verify your details', 'Check your details and try again.'],
  unavailable: ['Service temporarily unavailable', 'Try again shortly. Contact your administrator if this continues.'],
  limited: ['Please wait before trying again', 'Too many attempts. Retry when the service allows you to continue.'],
  expired: ['Your session or setup link expired', 'Sign in again. If setup was interrupted, contact your administrator.'],
};

function DemoField({ name, label, value, password = false }: { name: string; label: string; value: string; password?: boolean }) {
  return <Field name={name} label={label} defaultValue={value} component={({ fieldProps }) =>
      // Synthetic preview only. The single screen-level notice explains these fixed values.
      <Textfield {...fieldProps} isReadOnly type={password ? 'password' : 'text'} autoComplete="off" aria-describedby="demo-notice" />
    } />;
}

export function AccessPreview() {
  const [page, setPage] = useState<Page>(pageFromHash);
  const [theme, setTheme] = useState<Theme>('system');
  const setColorMode = useSetColorMode();
  const [scenario, setScenario] = useState<Scenario>('success');
  const [error, setError] = useState<[string, string] | null>(null);
  const [busy, setBusy] = useState(false);
  const [recoveryMode, setRecoveryMode] = useState(false);
  const [viewed, setViewed] = useState(false);
  const [announcement, setAnnouncement] = useState('');
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);
  const allowCodes = useRef(false);
  const previousPage = useRef(page);

  function go(next: Page, reveal = false) {
    if (pending.current !== null) clearTimeout(pending.current);
    pending.current = null;
    setBusy(false);
    if (next === 'login') setRecoveryMode(false);
    allowCodes.current = reveal;
    if (window.location.hash.slice(1) === next) {
      setPage(next === 'codes' && !reveal ? 'recovery' : next);
      setError(null);
    } else window.location.hash = next;
  }

  useEffect(() => {
    const update = () => {
      const hash = window.location.hash.slice(1);
      if (hash === 'content') return;
      const next = isPage(hash) ? hash : 'login';
      setPage(next === 'codes' && !allowCodes.current ? 'recovery' : next);
      allowCodes.current = false;
      setError(null);
      setBusy(false);
      if (pending.current !== null) clearTimeout(pending.current);
      pending.current = null;
      if (next === 'login') setRecoveryMode(false);
    };
    window.addEventListener('hashchange', update);
    return () => {
      window.removeEventListener('hashchange', update);
      if (pending.current !== null) clearTimeout(pending.current);
    };
  }, []);

  useEffect(() => {
    setColorMode(theme === 'system' ? 'auto' : theme);
  }, [theme, setColorMode]);

  useEffect(() => {
    document.title = `${titles[page]} · JBL React / Atlassian preview`;
    if (previousPage.current !== page) document.getElementById('page-heading')?.focus();
    previousPage.current = page;
  }, [page]);

  function simulate(next: Page) {
    if (busy) return;
    setBusy(true);
    setError(null);
    setAnnouncement('Simulating a response. No request is sent.');
    pending.current = setTimeout(() => {
      pending.current = null;
      setBusy(false);
      const failure = errors[scenario];
      if (failure) {
        setError(failure);
        setAnnouncement('');
        return;
      }
      if (next === 'codes') setViewed(true);
      go(next, next === 'codes');
      setAnnouncement('Demo response complete.');
    }, 450);
  }

  function demoForm(next: Page, label: string, fields?: React.ReactNode) {
    return <Form onSubmit={() => simulate(next)} label={titles[page]}>
      {fields}
      <FormFooter><Button type="submit" appearance="primary" shouldFitContainer isLoading={busy}>{label}</Button></FormFooter>
    </Form>;
  }
  const backLinks = <Box as="nav" aria-label="Account help"><Inline space="space.200" shouldWrap><Anchor href="#login">Back to sign in</Anchor><Anchor href="#help">Get access help</Anchor></Inline></Box>;
  let body: React.ReactNode;
  switch (page) {
    case 'login': body = <>
      {demoForm(scenario === 'enrollment' ? 'enroll' : 'mfa', 'Sign in', <><DemoField name="username" label="Staff username" value="demo.staff" /><DemoField name="password" label="Password" value="demo-only" password /></>)}
      <Box as="nav" aria-label="Sign-in help"><Stack space="space.100"><Anchor href="#setup">Set up your account</Anchor><Anchor href="#help">Trouble signing in?</Anchor></Stack></Box>
    </>; break;
    case 'setup': body = <>
      <Text as="p">This preview simulates an approved setup link. No email is sent.</Text>
      {demoForm('password', 'Verify link')}{backLinks}
    </>; break;
    case 'password': body = <>
      {demoForm('reauthenticate', 'Save password', <><DemoField name="new-password" label="New password" value="demo-only-password" password /><DemoField name="confirm-password" label="Confirm password" value="demo-only-password" password /></>)}{backLinks}
    </>; break;
    case 'mfa': body = <>
      {demoForm('shell', 'Verify', <DemoField name="mfa-code" label={recoveryMode ? 'Recovery code' : 'Authenticator code'} value={recoveryMode ? 'DEMO-CODE-ONLY' : '000000'} />)}
      <Stack space="space.100"><Button appearance="subtle" onClick={() => setRecoveryMode(value => !value)}>{recoveryMode ? 'Use your authenticator' : 'Use a recovery code'}</Button><Anchor href="#login">Cancel sign in</Anchor></Stack>
    </>; break;
    case 'enroll': body = <>{demoForm('scan', 'Continue', <DemoField name="recheck-password" label="Password" value="demo-only" password />)}{backLinks}</>; break;
    case 'scan': body = <>
      <Box xcss={styles.grouping}><Stack space="space.100"><Text weight="bold">Authenticator setup preview</Text><Text as="p">No QR code or authenticator secret is created in this demo.</Text></Stack></Box>
      {demoForm('recovery', 'Confirm', <DemoField name="enrollment-code" label="Authenticator code" value="000000" />)}{backLinks}
    </>; break;
    case 'recovery': body = <>
      <Text as="p">{viewed ? 'Codes have already been shown. Use your authenticator or contact your administrator.' : 'Request your codes when you are ready to save them. They can only be shown once.'}</Text>
      {viewed ? <LinkButton href="#reauthenticate" appearance="primary">Return to sign in</LinkButton> : demoForm('codes', 'Show codes')}{backLinks}
    </>; break;
    case 'codes': body = <>
      <Box as="section" testId="demo-codes" aria-label="Invalid demo recovery codes" xcss={styles.grouping}><Grid gap="space.150" xcss={styles.codes}>{['01','02','03','04'].map(code => <Text as="p" key={code}>DEMO CODE {code}</Text>)}</Grid></Box>
      <Text as="p">Save codes privately, then complete a fresh sign-in.</Text><LinkButton href="#reauthenticate" appearance="primary" shouldFitContainer>I saved my codes</LinkButton>
    </>; break;
    case 'reauthenticate': body = <><Text as="p">Setup alone does not grant access. No account has changed in this demo.</Text><LinkButton href="#login" appearance="primary">Sign in</LinkButton></>; break;
    case 'shell': body = <>
      <SectionMessage title="Tools are not connected" headingLevel="h2"><Text as="p">This preview loads no staff records or permissions.</Text></SectionMessage>
      <Grid gap="space.200" xcss={styles.tools} testId="workflow-grid">{['Complaints','TAT Tracker','Loan Origination','Jawabu Portal'].map((name, index) => <Box as="article" xcss={styles.tile} testId="workflow-card" key={name}><Stack space="space.100"><Heading as="h2" size="small">{name}</Heading><Text as="p" color="color.text.subtle">{index ? 'Available in a later pilot.' : 'First planned pilot.'}</Text><Text as="p" size="small" color="color.text.subtle">Not connected</Text></Stack></Box>)}</Grid>
    </>; break;
    case 'help': body = <>
      <Stack space="space.200">{[
        ['New to browser access?', 'Ask your administrator to enable your existing account.'],
        ['Setup interrupted or expired?', 'Ask for assistance. Do not create another account.'],
        ['Authenticator unavailable?', 'Use a saved recovery code or follow the approved identity-verification process.'],
      ].map(([label,text]) => <Stack key={label} space="space.050"><Heading as="h2" size="small">{label}</Heading><Text as="p">{text}</Text></Stack>)}</Stack>
      <Text as="p" size="small" color="color.text.subtle">Never share passwords, authenticator secrets or recovery codes.</Text>{backLinks}
    </>; break;
  }
  const title = page === 'mfa' && recoveryMode ? 'Use a recovery code' : titles[page];
  const selectedPage = page === 'scan' ? 'enroll' : page === 'codes' ? 'recovery' : page;
  const pageOptions = pages.filter(value => value !== 'scan' && value !== 'codes').map(value => ({ value, label: titles[value] }));
  const themes: {value: Theme; label: string}[] = [{value:'system',label:'System'},{value:'light',label:'Light'},{value:'dark',label:'Dark'}];
  const scenarios: {value: Scenario; label: string}[] = [{value:'success',label:'Success'},{value:'invalid',label:'Invalid details'},{value:'unavailable',label:'Service unavailable'},{value:'limited',label:'Too many attempts'},{value:'expired',label:'Expired session or link'},{value:'enrollment',label:'Enrollment required'}];
  const controls = isReview && <Box as="aside" id="review-controls" aria-label="Design review controls" testId="review-controls" xcss={styles.review}><Stack space="space.200">
    <Heading as="h2" size="small">Design review</Heading>
    <Text as="p" size="small" color="color.text.subtle">Synthetic states for review.</Text>
    <Box><Label htmlFor="review-page">Page</Label><Select inputId="review-page" options={pageOptions} value={pageOptions.find(option=>option.value===selectedPage)} onChange={option=>{if(option)go(option.value);}} isSearchable={false} /></Box>
    <Box><Label htmlFor="review-theme">Theme</Label><Select inputId="review-theme" options={themes} value={themes.find(option=>option.value===theme)} onChange={option=>{if(option)setTheme(option.value);}} isSearchable={false} /></Box>
    <Box><Label htmlFor="review-response">Response</Label><Select inputId="review-response" options={scenarios} value={scenarios.find(option=>option.value===scenario)} onChange={option=>{if(option)setScenario(option.value);}} isSearchable={false} /></Box>
    <Button onClick={()=>{setViewed(false);setRecoveryMode(false);setScenario('success');setError(null);go('login');}}>Reset demo</Button>
    <Anchor href="/">Open staff preview</Anchor>
  </Stack></Box>;
  const workspace = page === 'shell';
  return <Root defaultSideNavCollapsed={false}>
    <TopNav>
      <TopNavStart sideNavToggleButton={workspace ? <SideNavToggleButton expandLabel="Open navigation" collapseLabel="Close navigation" /> : null}><Anchor href={workspace ? '#shell' : '#login'}><Text weight="bold">JBL Staff workspace</Text></Anchor></TopNavStart>
      <TopNavMiddle>{null}</TopNavMiddle>
      <TopNavEnd><LinkButton href="#help" appearance="subtle">Help</LinkButton>{workspace && <LinkButton href="#login">Sign out</LinkButton>}</TopNavEnd>
    </TopNav>
    {workspace && <SideNav label="Workspace navigation" defaultWidth={240}>
      <SideNavHeader><Box xcss={styles.navText}><Text weight="bold">Jawabu Biashara Limited</Text></Box></SideNavHeader>
      <SideNavBody><MenuSection><MenuSectionHeading>Workspace</MenuSectionHeading><MenuList><LinkMenuItem href="#shell" isSelected>Overview</LinkMenuItem><LinkMenuItem href="#help">Account help</LinkMenuItem></MenuList></MenuSection></SideNavBody>
      <SideNavFooter><Box xcss={styles.navText}><Text size="small" color="color.text.subtle">Local preview</Text></Box></SideNavFooter>
    </SideNav>}
    <Main id="content" testId="content" skipLinkLabel="Page content"><VisuallyHidden><Box role="status" aria-live="polite">{announcement}</Box></VisuallyHidden><Box xcss={styles.page}>
      <Box xcss={styles.frame}><Stack space="space.200">
        <Grid gap="space.300" xcss={cx(styles.composition,isReview && styles.reviewComposition)}>
          <Box as="section" testId="access-page" aria-busy={busy} aria-labelledby="page-heading" xcss={cx(styles.task,!workspace && styles.access,page==='help' && styles.help)}>
            <Stack space="space.150">
              <Text as="p" id="demo-notice" size="small" color="color.text.subtle">Demo: fixed values only. No account changes or live requests.</Text>
              <Box id="page-heading" tabIndex={-1}><Heading as="h1" size="large">{title}</Heading></Box>
              <Text as="p" testId="task-description" color="color.text.subtle">{page==='mfa' && recoveryMode ? 'Each recovery code can only be used once.' : descriptions[page]}</Text>
              {error && <Box role="alert" testId="form-feedback"><SectionMessage appearance="error" title={error[0]} headingLevel="h2"><Stack space="space.100"><Text as="p">{error[1]}</Text>{scenario==='expired' && <Anchor href="#help">Get access help</Anchor>}</Stack></SectionMessage></Box>}
              {body}
              <Box as="footer"><Anchor href="/THIRD_PARTY_NOTICES.txt">Open-source notices</Anchor></Box>
            </Stack>
          </Box>
          {controls}
        </Grid>
      </Stack></Box>
    </Box></Main>
  </Root>;
}
