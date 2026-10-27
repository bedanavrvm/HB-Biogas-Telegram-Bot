// Fixed same-origin native contracts. Proof is transient, never persisted/replayed.
const prefix = '/api/staff/auth/v1/';
const sessionStates = ['signed_out', 'mfa_required', 'authenticated', 'enrollment_required', 'recovery_codes_required', 'reauthentication_required'] as const;
export type SessionState = typeof sessionStates[number];
export type AccessState = SessionState | 'setup_verify' | 'setup_password' | 'setup_codes' | 'setup_invalid';
export type Action = 'login' | 'mfa' | 'logout' | 'setup/verify-email' | 'setup/password' | 'enrollment/begin' | 'enrollment/confirm' | 'enrollment/recovery-codes';
export type Invitation = { setup_id: string; confirmation_key: string };
export type Result = { state: AccessState; failure?: string; retryAfter?: number; username?: string; setupId?: string; enrollment?: { uri: string; qr: string }; codes?: string[]; fieldErrors?: Record<string, string> };
export class TransportError extends Error {
  constructor(public kind: 'network' | 'csrf' | 'unavailable' | 'protocol') { super('Staff access request could not be confirmed.'); }
}
type Reply = { state: string; is_authenticated: boolean; separate_session_required?: boolean; csrf_token?: string; username?: string; setup_id?: string; otpauth_uri?: string; qr_data?: string; recovery_codes?: unknown; field_errors?: unknown };

export function consumeInvitation(): Invitation | null {
  const fragment = new URLSearchParams(window.location.hash.slice(1));
  if (!fragment.has('setup')) return null;
  // Fragments never enter HTTP logs; erase even malformed invitation material.
  window.history.replaceState(null, '', window.location.pathname + window.location.search);
  return { setup_id: fragment.get('setup') || '', confirmation_key: fragment.get('key') || '' };
}
async function request(action: string, signal: AbortSignal, body?: Record<string, string>, csrf?: string) {
  let response: Response;
  try {
    response = await fetch(prefix + action + '/', { method: body ? 'POST' : 'GET', mode: 'same-origin', credentials: 'same-origin', cache: 'no-store', redirect: 'error', referrerPolicy: 'no-referrer', signal,
      headers: body ? { 'Content-Type': 'application/json', 'X-CSRFToken': csrf! } : { Accept: 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) });
  } catch { throw new TransportError('network'); }
  if (response.status === 403) throw new TransportError('csrf');
  if (response.status >= 500 || response.status === 404) throw new TransportError('unavailable');
  if (response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== 'application/json') throw new TransportError('protocol');
  let reply: Reply;
  try { reply = await response.json(); } catch { throw new TransportError('protocol'); }
  if (!reply || typeof reply !== 'object' || typeof reply.state !== 'string' || reply.is_authenticated !== (reply.state === 'authenticated') || (reply.is_authenticated && response.status !== 200)) throw new TransportError('protocol');
  return { response, reply };
}
async function session(signal: AbortSignal, setup = false) {
  const result = await request(setup ? 'setup/session' : 'session', signal);
  if (result.response.status !== 200 || !/^[A-Za-z0-9]{32}(?:[A-Za-z0-9]{32})?$/.test(result.reply.csrf_token || '')) throw new TransportError('protocol');
  if (!setup && !sessionStates.some(state => state === result.reply.state)) throw new TransportError('protocol');
  return result.reply;
}
function enrollment(reply: Reply): Result['enrollment'] {
  if (reply.otpauth_uri === undefined && reply.qr_data === undefined) return undefined;
  if (typeof reply.otpauth_uri !== 'string' || reply.otpauth_uri.length > 4096 || typeof reply.qr_data !== 'string' || reply.qr_data.length > 200000 || !/^data:image\/svg\+xml;base64,[A-Za-z0-9+/]+=*$/.test(reply.qr_data)) throw new TransportError('protocol');
  const uri = new URL(reply.otpauth_uri);
  if (uri.protocol !== 'otpauth:' || uri.hostname !== 'totp' || !/^[A-Z2-7]{16,128}$/.test(uri.searchParams.get('secret') || '')) throw new TransportError('protocol');
  return { uri: reply.otpauth_uri, qr: reply.qr_data };
}
export async function checkSession(signal: AbortSignal): Promise<Result> {
  const reply = await session(signal);
  if (reply.separate_session_required) return { state:'signed_out',failure:'separate_session' };
  if (['enrollment_required', 'recovery_codes_required', 'reauthentication_required'].includes(reply.state)) {
    const draft = await request('enrollment/session', signal);
    if (draft.response.status !== 200 || !sessionStates.some(state => state === draft.reply.state)) throw new TransportError('protocol');
    return { state: draft.reply.state as SessionState, enrollment: enrollment(draft.reply), username: draft.reply.username };
  }
  return { state: reply.state as SessionState };
}
export async function resumeAccess(signal: AbortSignal, invitation: Invitation | null): Promise<Result> {
  const result = await checkSession(signal);
  if (result.failure === 'separate_session') return result;
  if (result.state !== 'signed_out') return result;
  const progress = await request('setup/session', signal);
  // A stale browser-owned Django cookie can still authenticate request.user.
  // Anonymous setup's 409 must not hide the valid native signed-out state.
  if (progress.response.status === 409 && progress.reply.state === 'sign_out_required') return result;
  if (progress.response.status !== 200) throw new TransportError('protocol');
  const setup = progress.reply;
  if (invitation) return { state: 'setup_verify' };
  if (setup.state === 'password_required' && setup.setup_id && setup.username) return { state: 'setup_password', setupId: setup.setup_id, username: setup.username };
  return { state: 'signed_out', username: setup.username };
}
async function post(action: Action, body: Record<string, string>, signal: AbortSignal) {
  const before = await session(signal, action.startsWith('setup/'));
  return request(action, signal, body, before.csrf_token);
}
function fieldErrors(reply: Reply): Record<string, string> {
  const result: Record<string, string> = {};
  if (reply.field_errors && typeof reply.field_errors === 'object') {
    for (const field of ['password1', 'password2']) {
      const errors = (reply.field_errors as Record<string, unknown>)[field];
      if (Array.isArray(errors)) result[field] = errors.filter(row => row && typeof row.message === 'string' && row.message.length <= 500).map(row => row.message).join(' ');
    }
  }
  return result;
}
export async function submit(action: Action, body: Record<string, string>, signal: AbortSignal): Promise<Result> {
  if (action.startsWith('setup/') || action.startsWith('enrollment/')) body = { ...body, request_key: crypto.randomUUID() };
  const { response, reply } = await post(action, body, signal);
  if (response.status === 429) return { ...await resumeAccess(signal, null), failure: 'rate_limited', retryAfter: Math.min(600, Math.max(1, Number(response.headers.get('Retry-After')) || 60)) };
  if (action === 'setup/verify-email') {
    if (response.status === 200 && reply.state === 'reauthentication_required') return { state:'signed_out',username:reply.username };
    if (response.status !== 200 || reply.state !== 'password_required') return { state: 'setup_invalid', failure: 'setup_invalid' };
    return resumeAccess(signal, null);
  }
  if (action === 'setup/password') {
    const setup = await session(signal, true);
    if (response.status === 400 && reply.state === 'invalid_password') return { state: 'setup_password', setupId: setup.setup_id, username: setup.username, fieldErrors: fieldErrors(reply), failure: 'invalid_password' };
    if (response.status !== 200 || reply.state !== 'reauthentication_required' || !setup.username) return { state: 'setup_invalid', failure: 'setup_invalid' };
    // One explicit create-password action; no proof retained between screens.
    return submit('login', { username: setup.username, password: body.password1 }, signal);
  }
  if (action === 'login' && reply.state === 'enrollment_required' && [200, 202].includes(response.status)) {
    const result = await submit('enrollment/begin', { password: body.password }, signal);
    return { ...result, username: body.username };
  }
  if (action === 'enrollment/confirm' && response.status === 200 && reply.state === 'recovery_codes_required') return submit('enrollment/recovery-codes', {}, signal);
  if (action === 'enrollment/recovery-codes' && response.status === 200 && reply.state === 'reauthentication_required') {
    const codes = reply.recovery_codes;
    if (!Array.isArray(codes) || codes.length < 1 || codes.length > 50 || !codes.every(code => typeof code === 'string' && /^[0-9A-Za-z-]{6,32}$/.test(code))) throw new TransportError('protocol');
    const after = await session(signal);
    if (after.state !== 'reauthentication_required') throw new TransportError('protocol');
    return { state: 'setup_codes', codes };
  }
  const after = await checkSession(signal);
  if (response.status === 400) return { ...after, failure: reply.state === 'invalid_credentials' ? 'invalid_credentials' : action === 'enrollment/confirm' ? 'invalid_enrollment_code' : action === 'mfa' ? 'invalid_code' : 'setup_invalid' };
  if (![200, 202, 401, 409].includes(response.status)) throw new TransportError('protocol');
  if (response.status === 409 && action.startsWith('enrollment/')) return { ...after, failure: 'enrollment_restart' };
  return { ...after, ...(action !== 'logout' && after.state === 'signed_out' ? { failure: after.failure || 'session_ended' } : {}) };
}
