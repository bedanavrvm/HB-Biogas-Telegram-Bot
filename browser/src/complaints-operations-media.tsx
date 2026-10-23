import React, { useEffect, useRef, useState } from 'react';
import Button from '@atlaskit/button/default/button';
import { cssMap } from '@atlaskit/css';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import { operation, operationPath, OperationError, download } from './complaints-operations-transport';
import { TaskDialog } from './complaints-ui';
import { notify } from './browser-interactions';
import { IconButton } from '@atlaskit/button/new';
import PreviousIcon from '@atlaskit/icon/core/chevron-left';
import NextIcon from '@atlaskit/icon/core/chevron-right';
import AddIcon from '@atlaskit/icon/core/add';
import MinusIcon from '@atlaskit/icon/core/minus';
import RefreshIcon from '@atlaskit/icon/core/refresh';
import DownloadIcon from '@atlaskit/icon/core/download';

const styles = cssMap({ viewport: { width: '100%', height: '65vh', overflow: 'auto', overscrollBehavior: 'contain' }, image: { display: 'block', height: 'auto', marginInline: 'auto' } });
function message(error: unknown) { return error instanceof OperationError ? error.message : 'This action could not be confirmed. You can continue with typed text or try again.'; }

export function EvidencePreview({ group, id, name, type, showName=true }: { group: string; id: string; name: string; type: string; showName?:boolean }) {
  const [url, setURL] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState(''), [opened, setOpened] = useState(false), [page, setPage] = useState(1), [pages, setPages] = useState(1), [zoom, setZoom] = useState(100);
  const controller = useRef<AbortController | null>(null);
  const image = useRef<HTMLImageElement>(null), viewport = useRef<HTMLDivElement>(null), generation = useRef(0);
  const drag = useRef<{x:number;y:number;scrollX:number;scrollY:number}>();
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);
  useEffect(() => { if(image.current) image.current.style.width = `${zoom}%`; }, [zoom, url]);
  const open = async (selectedPage = page) => {
    controller.current?.abort(); const started = ++generation.current;
    setOpened(true); setBusy(true); setError(''); setURL(''); const request = new AbortController(); controller.current = request;
    const timer = setTimeout(() => request.abort(), 30000);
    try {
      if(type === 'application/pdf') {
        const data = await operation<{image:string;page:number;page_count:number}>(group, `evidence/${id}/preview/`, request.signal, {page:selectedPage});
        if(started === generation.current) {setURL(data.image);setPage(data.page);setPages(data.page_count);setZoom(100);}
        return;
      }
      const response = await fetch(operationPath(group, `evidence/${id}/`), { credentials: 'same-origin', mode: 'same-origin', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer', signal: request.signal });
      if (!response.ok) throw new OperationError(response.status, 'The document could not be loaded. Refresh and try again.');
      const blob = await response.blob();
      if (!['image/jpeg', 'image/png', 'image/webp'].includes(blob.type)) throw new OperationError(0, 'This file cannot be previewed. Use Download instead.');
      if (!request.signal.aborted) setURL(URL.createObjectURL(blob));
    } catch (issue) { if (started === generation.current) { const detail = request.signal.aborted ? 'Preview took too long. Try again or download the file.' : message(issue); setError(detail); notify(detail, 'error'); } } finally { clearTimeout(timer); if(started === generation.current)setBusy(false); }
  };
  const close = () => {generation.current++;controller.current?.abort();setOpened(false);setURL('');setBusy(false);};
  return <Stack space="space.100"><Inline shouldWrap space="space.100" alignBlock="center">{showName&&<Text>{name}</Text>}<Button onClick={() => {void open();}}>Preview</Button></Inline>{opened && <TaskDialog title={name} close={close} wide><Inline spread="space-between" alignBlock="center" space="space.050"><IconButton label="Previous page" appearance="subtle" icon={PreviousIcon} isDisabled={busy || page <= 1} onClick={() => {void open(page - 1);}}/><Inline shouldWrap alignBlock="center" space="space.050"><IconButton label="Zoom out" appearance="subtle" icon={MinusIcon} isDisabled={zoom <= 50} onClick={() => setZoom(value => Math.max(50,value-25))}/><Button appearance="subtle" onClick={() => setZoom(100)}>{zoom}%</Button><IconButton label="Zoom in" appearance="subtle" icon={AddIcon} isDisabled={zoom >= 400} onClick={() => setZoom(value => Math.min(400,value+25))}/><IconButton label="Fit to width" appearance="subtle" icon={RefreshIcon} onClick={() => {setZoom(100);viewport.current?.scrollTo(0,0);}}/><IconButton label="Download original" appearance="subtle" icon={DownloadIcon} onClick={() => {void download(group,`evidence/${id}/?download=1`).then(()=>notify('File ready. Your browser handles the download.','information')).catch(issue=>notify(message(issue),'error'));}}/></Inline><IconButton label="Next page" appearance="subtle" icon={NextIcon} isDisabled={busy || page >= pages} onClick={() => {void open(page + 1);}}/></Inline><Text size="small">Page {page} of {pages}</Text>{busy && <Box role="status"><Text>Loading preview…</Text></Box>}{error && <Box role="alert"><Text color="color.text.danger">{error}</Text><Button onClick={() => {void open();}}>Retry preview</Button></Box>}<Box as="div" ref={viewport} xcss={styles.viewport} tabIndex={0} aria-label="Scrollable document preview" onPointerDown={(event: React.PointerEvent<HTMLDivElement>) => {if(zoom<=100)return;drag.current={x:event.clientX,y:event.clientY,scrollX:event.currentTarget.scrollLeft,scrollY:event.currentTarget.scrollTop};event.currentTarget.setPointerCapture(event.pointerId);}} onPointerMove={(event: React.PointerEvent<HTMLDivElement>) => {const start=drag.current;if(start){event.currentTarget.scrollLeft=start.scrollX+start.x-event.clientX;event.currentTarget.scrollTop=start.scrollY+start.y-event.clientY;}}} onPointerUp={() => {drag.current=undefined;}} onPointerCancel={() => {drag.current=undefined;}}>{url && <Box as="img" ref={image} xcss={styles.image} src={url} alt={name} draggable={false} onError={() => {setError('This image could not be displayed. Download the original instead.');notify('The image could not be displayed. Download the original instead.','error');}}/>}</Box></TaskDialog>}</Stack>;
}

export function VoiceInput({ group, field, caseKey, accept, maxSeconds = 30 }: { group: string; field: string; caseKey?: string; accept: (text: string, id: string) => void; maxSeconds?: number }) {
  const [recording, setRecording] = useState(false), [audio, setAudio] = useState<Blob>(), [text, setText] = useState(''), [attempt, setAttempt] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  useEffect(()=>{if(error)notify(error,'error');},[error]);
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
