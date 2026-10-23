import React, { useContext, useEffect, useId, useRef, useState } from 'react';
import Button from '@atlaskit/button/default/button';
import SectionMessage from '@atlaskit/section-message';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Text } from '@atlaskit/primitives/compiled/text';
import { operation, OperationError } from './complaints-operations-transport';
import { type RecoverySlot } from './workspace-recovery';
import { dismissNotice, notify } from './browser-interactions';

export const TaskSession = React.createContext<() => void>(() => {});
type Pending = { path: string; body: Record<string, unknown> };

/** Exact JSON request recovery; no automatic write after reconnect or sign-in. */
export function useWorkspaceTask<T>(group: string, slot: RecoverySlot, name: string, confirmed: (result: T) => void) {
  const [busy, setBusy] = useState(false), [error, setError] = useState<unknown>();
  const [uncertain, setUncertain] = useState(Boolean(slot.read()[name + ':pending']));
  const active = useRef(true), dispatching = useRef(false), controller = useRef<AbortController>();
  const notice = useRef<number>();
  const noticeOwner=useId();
  const callback = useRef(confirmed); callback.current = confirmed;
  useEffect(() => {
    active.current = true;
    const result = slot.read()[name + ':confirmed'] as T | undefined;
    if (result !== undefined) { slot.patch({[name + ':confirmed']: undefined}); callback.current(result); }
    return () => { active.current = false; controller.current?.abort(); if(notice.current!==undefined)dismissNotice(notice.current); };
  }, []);
  const execute = async (request: Pending) => {
    if (dispatching.current) return;
    if (!navigator.onLine) { const text='You are offline. Your changes are retained. Reconnect before saving.';setError(new OperationError(0,text));notice.current=notify(text,'error',{dedupeKey:noticeOwner+':offline'});return; }
    const retrying = Boolean(slot.read()[name + ':pending']);
    dispatching.current = true; setBusy(true); setError(undefined); if(notice.current!==undefined)dismissNotice(notice.current);
    slot.patch({[name + ':pending']: request});
    const control = new AbortController(); controller.current = control;
    const timer = setTimeout(() => control.abort(), 30000);
    try {
      const result = await operation<T>(group, request.path, control.signal, request.body);
      slot.patch({[name + ':pending']: undefined, [name + ':confirmed']: result});
      if (active.current) { setUncertain(false); callback.current(result); slot.patch({[name + ':confirmed']: undefined}); }
    } catch (issue) {
      const rejected = !retrying && issue instanceof OperationError && [400,401,403,404,409,413,422,429].includes(issue.status);
      if (rejected) slot.patch({[name + ':pending']: undefined});
      if (active.current) { setUncertain(!rejected); setError(issue); notice.current=notify(issue instanceof OperationError ? issue.message : 'The request could not be confirmed. Your changes are retained.', 'error'); }
    } finally { clearTimeout(timer); dispatching.current = false; if (active.current) setBusy(false); }
  };
  return { busy, error, uncertain,
    reset: () => { if (!dispatching.current) {slot.patch({[name + ':pending']:undefined,[name + ':confirmed']:undefined});setUncertain(false);setError(undefined);if(notice.current!==undefined)dismissNotice(notice.current);} },
    save: (path: string, body: Record<string, unknown>) => { if (!slot.read()[name + ':pending']) return execute({path, body: structuredClone(body)}); },
    retry: () => { const pending = slot.read()[name + ':pending'] as Pending | undefined; if (pending) return execute(pending); },
  };
}

export function TaskRecovery({state}: {state: {busy: boolean; uncertain: boolean; error?: unknown; retry: () => unknown}}) {
  const signIn = useContext(TaskSession);
  if (!state.error && !state.uncertain) return null;
  return <Box role="alert"><SectionMessage appearance={state.uncertain ? 'warning' : 'error'} title={state.uncertain ? 'Check the previous save' : 'Changes not saved'} headingLevel="h3"><Text as="p">{state.uncertain ? 'The request may already be saved. Retry the same request to confirm it before making changes.' : state.error instanceof OperationError ? state.error.message : 'Check your connection and try again. Your changes are retained.'}</Text><Inline shouldWrap space="space.100">{state.error instanceof OperationError && [401,403].includes(state.error.status) && <Button onClick={signIn}>Sign in again</Button>}{state.uncertain && <Button isLoading={state.busy} onClick={()=>{void state.retry();}}>Retry previous save</Button>}</Inline></SectionMessage></Box>;
}
