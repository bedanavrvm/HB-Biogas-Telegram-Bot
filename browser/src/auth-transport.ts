// Fixed same-origin contract; no configurable host, bearer token or persistence.
const prefix = '/api/staff/auth/v1/';
const sessionStates = ['signed_out', 'mfa_required', 'authenticated', 'enrollment_required', 'recovery_codes_required', 'reauthentication_required'] as const;
export type SessionState = typeof sessionStates[number];
export type Action = 'login' | 'mfa' | 'logout';
export type Failure = 'invalid_credentials' | 'invalid_code' | 'rate_limited' | 'session_ended';
export class TransportError extends Error {
  constructor(public kind: 'network' | 'csrf' | 'unavailable' | 'protocol') {
    super('Staff access request could not be confirmed.');
  }
}
type Reply = { state: string; is_authenticated: boolean; csrf_token?: string };
type Result = { state: SessionState; failure?: Failure; retryAfter?: number };

async function request(action: 'session' | Action, signal: AbortSignal, body?: Record<string, string>, csrf?: string): Promise<{ response: Response; reply: Reply }> {
  let response: Response;
  try {
    response = await fetch(prefix + action + '/', {
      method: body ? 'POST' : 'GET', mode: 'same-origin', credentials: 'same-origin',
      cache: 'no-store', redirect: 'error', referrerPolicy: 'no-referrer', signal,
      headers: body ? { 'Content-Type': 'application/json', 'X-CSRFToken': csrf! } : { Accept: 'application/json' },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
  } catch {
    throw new TransportError('network');
  }
  if (response.status === 403) throw new TransportError('csrf');
  if (response.status >= 500 || response.status === 404) throw new TransportError('unavailable');
  if (response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== 'application/json') throw new TransportError('protocol');
  let reply: Reply;
  try { reply = await response.json(); } catch { throw new TransportError('protocol'); }
  if (!reply || typeof reply !== 'object' || typeof reply.state !== 'string' || reply.is_authenticated !== (reply.state === 'authenticated')) throw new TransportError('protocol');
  if (reply.state === 'authenticated' && response.status !== 200) throw new TransportError('protocol');
  return { response, reply };
}

async function session(signal: AbortSignal) {
  const { response, reply } = await request('session', signal);
  if (response.status !== 200 || !sessionStates.some(state => state === reply.state) || !/^[A-Za-z0-9]{32}(?:[A-Za-z0-9]{32})?$/.test(reply.csrf_token || '')) throw new TransportError('protocol');
  return { state: reply.state as SessionState, csrf: reply.csrf_token! };
}

export async function checkSession(signal: AbortSignal): Promise<Result> {
  return { state: (await session(signal)).state };
}

export async function submit(action: Action, body: Record<string, string>, signal: AbortSignal): Promise<Result> {
  // Refresh before every mutation: another tab or native login may rotate CSRF.
  const before = await session(signal);
  const { response, reply } = await request(action, signal, body, before.csrf);
  let failure: Failure | undefined;
  if (response.status === 429 && reply.state === 'rate_limited') failure = 'rate_limited';
  else if (response.status === 400 && reply.state === 'invalid_credentials') failure = 'invalid_credentials';
  else if (action === 'mfa' && response.status === 400 && reply.state === 'mfa_required') failure = 'invalid_code';
  else if (action !== 'logout' && reply.state === 'signed_out') failure = 'session_ended';
  else if (!sessionStates.some(state => state === reply.state) || ![200, 202, 401, 409].includes(response.status)) throw new TransportError('protocol');
  // The session read, including CSRF after login rotation, is authoritative.
  // A failed/uncertain POST is never replayed here, including logout.
  const after = await session(signal);
  const retry = Number(response.headers.get('Retry-After'));
  return { state: after.state, failure, ...(failure === 'rate_limited' && Number.isInteger(retry) && retry > 0 && retry <= 600 ? { retryAfter: retry } : {}) };
}
