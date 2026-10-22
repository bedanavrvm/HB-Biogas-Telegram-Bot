import React, { useEffect, useRef, useState } from 'react';
import Button from '@atlaskit/button/default/button';
import { cssMap } from '@atlaskit/css';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import { operation, operationPath, OperationError } from './complaints-operations-transport';

const styles = cssMap({ preview: { width: '100%', height: '70vh', borderWidth: 0 }, image: { maxWidth: '100%', height: 'auto' } });
function message(error: unknown) { return error instanceof OperationError ? error.message : 'This action could not be confirmed. You can continue with typed text or try again.'; }

export function EvidencePreview({ group, id, name, type }: { group: string; id: string; name: string; type: string }) {
  const [url, setURL] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);
  const open = async () => {
    if (busy) return; setBusy(true); setError(''); const request = new AbortController(); controller.current = request;
    const timer = setTimeout(() => request.abort(), 30000);
    try {
      const response = await fetch(operationPath(group, `evidence/${id}/`), { credentials: 'same-origin', mode: 'same-origin', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer', signal: request.signal });
      if (!response.ok) throw new OperationError(response.status, 'The document could not be loaded. Refresh and try again.');
      const blob = await response.blob();
      if (!['application/pdf', 'image/jpeg', 'image/png', 'image/webp'].includes(blob.type)) throw new OperationError(0, 'This file cannot be previewed. Use Download instead.');
      if (!request.signal.aborted) setURL(URL.createObjectURL(blob));
    } catch (issue) { if (!request.signal.aborted) setError(message(issue)); } finally { clearTimeout(timer); setBusy(false); }
  };
  return <Stack space="space.100"><Inline shouldWrap space="space.100" alignBlock="center"><Text>{name}</Text><Button isLoading={busy} onClick={() => { if (url) setURL(''); else void open(); }}>{url ? 'Close preview' : 'Preview'}</Button></Inline>{error && <Box role="alert"><Text color="color.text.danger">{error}</Text></Box>}{url && (type === 'application/pdf' ? <Box as="iframe" xcss={styles.preview} title={name} src={url} /> : <Box as="img" xcss={styles.image} src={url} alt={name} />)}</Stack>;
}

export function VoiceInput({ group, field, caseKey, accept, maxSeconds = 30 }: { group: string; field: string; caseKey?: string; accept: (text: string, id: string) => void; maxSeconds?: number }) {
  const [recording, setRecording] = useState(false), [audio, setAudio] = useState<Blob>(), [text, setText] = useState(''), [attempt, setAttempt] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null), stream = useRef<MediaStream | null>(null), start = useRef(0), duration = useRef(0), key = useRef(''), timer = useRef<ReturnType<typeof setTimeout>>(), mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; clearTimeout(timer.current); if (recorder.current?.state === 'recording') recorder.current.stop(); stream.current?.getTracks().forEach(track => track.stop()); }; }, []);
  const record = async () => {
    setError(''); setAudio(undefined); setText(''); setAttempt('');
    try {
      const media = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!mounted.current) { media.getTracks().forEach(track => track.stop()); return; }
      stream.current = media; const capture = new MediaRecorder(media); recorder.current = capture;
      const chunks: BlobPart[] = [];
      capture.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
      capture.onstop = () => { clearTimeout(timer.current); duration.current = Math.max(1, Date.now() - start.current); media.getTracks().forEach(track => track.stop()); if (mounted.current) { setRecording(false); setAudio(new Blob(chunks, { type: capture.mimeType.split(';')[0] })); key.current = crypto.randomUUID(); } };
      start.current = Date.now(); capture.start(); setRecording(true); timer.current = setTimeout(() => { if (capture.state === 'recording') capture.stop(); }, Math.min(30, maxSeconds) * 1000);
    } catch { setError('Microphone access is unavailable. Continue by typing your note.'); }
  };
  const transcribe = async () => {
    if (!audio || busy) return; setBusy(true); setError('');
    const body = new FormData(); body.set('field_name', field); body.set('duration_ms', String(duration.current)); body.set('client_request_id', key.current); body.set('language_mode', 'auto'); if (caseKey) body.set('case_key', caseKey); body.set('audio', audio, 'recording');
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 45000);
    try { const result = await operation<{ text: string; transcription_id: string; status: string }>(group, 'voice/', controller.signal, body); if (mounted.current) { if (result.status !== 'transcribed') throw new OperationError(0, 'The recording could not be transcribed. You can type the note instead.'); setText(result.text); setAttempt(result.transcription_id); } } catch (issue) { if (mounted.current) setError(message(issue)); } finally { clearTimeout(timeout); if (mounted.current) setBusy(false); }
  };
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') return null;
  return <Stack space="space.100"><Inline shouldWrap space="space.100"><Button isDisabled={busy} onClick={() => { if (recording) recorder.current?.stop(); else void record(); }}>{recording ? 'Stop recording' : 'Record note'}</Button>{audio && !attempt && <Button isLoading={busy} onClick={() => { void transcribe(); }}>Transcribe recording</Button>}{attempt && <Button onClick={() => { accept(text, attempt); setAudio(undefined); setAttempt(''); setText(''); }}>Use this text</Button>}</Inline>{recording && <Box role="status"><Text>Recording. Stops after {Math.min(30, maxSeconds)} seconds.</Text></Box>}{text && <Box role="status"><Text as="p">{text}</Text></Box>}{error && <Box role="alert"><Text color="color.text.danger">{error}</Text></Box>}</Stack>;
}
