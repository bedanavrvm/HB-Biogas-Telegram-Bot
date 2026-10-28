import React, { useEffect, useRef, useState } from 'react';
import Button from '@atlaskit/button/default/button';
import { cssMap } from '@atlaskit/css';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import { operation, OperationError, download, type Evidence } from './complaints-operations-transport';
import { TaskDialog, displayDate } from './complaints-ui';
import { Grid } from '@atlaskit/primitives/compiled/grid';
import { token } from '@atlaskit/tokens';
import AttachmentIcon from '@atlaskit/icon/core/attachment';
import { notify } from './browser-interactions';
import { IconButton } from '@atlaskit/button/new';
import PreviousIcon from '@atlaskit/icon/core/chevron-left';
import NextIcon from '@atlaskit/icon/core/chevron-right';
import AddIcon from '@atlaskit/icon/core/add';
import MinusIcon from '@atlaskit/icon/core/minus';
import RefreshIcon from '@atlaskit/icon/core/refresh';
import DownloadIcon from '@atlaskit/icon/core/download';
import {FileProgress} from './complaints-publication';

const styles = cssMap({
  viewport: { width: '100%', height: '55vh', overflow: 'auto', overscrollBehavior: 'contain' },
  image: { display: 'block', height: 'auto', marginInline: 'auto', objectFit: 'contain' },
  tiles: { gridTemplateColumns:'repeat(auto-fit, minmax(min(100%, 14rem), 1fr))' },
  tile: { minWidth:0, padding:token('space.150'), border:`${token('border.width')} solid ${token('color.border')}`, borderRadius:token('radius.medium'), overflowWrap:'anywhere' },
  thumbnail: { width:'100%', height:'8rem', objectFit:'contain', backgroundColor:token('color.background.neutral.subtle') },
});
function message(error: unknown) { return error instanceof OperationError ? error.message : 'This action could not be confirmed. You can continue with typed text or try again.'; }

const previewable = (item:Evidence) => ['image/jpeg','image/png','image/webp','application/pdf'].includes(item.mime_type);
function fileState(item:Evidence) { return item.status==='pending'?'File saved. Preparing preview.':item.status==='failed'?'File saved. Ask Complaints IT to retry publication.':!previewable(item)?'Preview unsupported. Download the original.':''; }
function Metadata({item}:{item:Evidence}) {
  const facts=[({'image/png':'PNG image','image/jpeg':'JPEG image','image/webp':'WebP image','application/pdf':'PDF'}[item.mime_type]||'File'),item.size?`${Number((item.size/1024).toFixed(1))} KB`:'',item.uploaded_by,item.created_at_iso?displayDate(item.created_at_iso):item.created_at].filter(Boolean);
  return facts.length?<span data-stitch="file-meta"><Text size="small" color="color.text.subtle">{facts.join(' · ')}</Text></span>:null;
}
function original(group:string,item:Evidence) { void download(group,`evidence/${item.id}/?download=1`).then(()=>notify('File ready. Your browser handles the download.','information',{dedupeKey:'evidence-download:'+item.id})).catch(issue=>notify(message(issue),'error',{dedupeKey:'evidence-download-error:'+item.id})); }
function EvidenceTile({group,item,open,commentKey}:{group:string;item:Evidence;open:()=>void;commentKey?:string}) {
  const root=useRef<HTMLDivElement>(null),[visible,setVisible]=useState(false),[url,setURL]=useState(''),[error,setError]=useState(''),[retry,setRetry]=useState(0);
  const state=fileState(item);
  useEffect(()=>{const observer=new IntersectionObserver(entries=>{if(entries.some(entry=>entry.isIntersecting)){setVisible(true);observer.disconnect();}},{rootMargin:'100px'});if(root.current)observer.observe(root.current);return()=>observer.disconnect();},[]);
  useEffect(()=>{if(!visible||state)return;const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),30000);let active=true;setError('');setURL('');void operation<{image:string}>(group,`evidence/${item.id}/preview/`,controller.signal,{page:1,thumbnail:true}).then(data=>{if(active)setURL(data.image);}).catch(()=>{if(active)setError('Preview unavailable');}).finally(()=>clearTimeout(timer));return()=>{active=false;controller.abort();clearTimeout(timer);};},[group,item.id,visible,state,retry]);
  return <Box ref={root} xcss={styles.tile} data-stitch="evidence-tile"><Stack space="space.100"><div data-stitch="file-name"><Text weight="semibold">{item.name}</Text></div><Metadata item={item}/><FileProgress evidence={item.id} commentKey={commentKey}/>{url?<Box as="img" data-stitch="thumbnail" xcss={styles.thumbnail} loading="lazy" src={url} alt={'Thumbnail of '+item.name} onError={()=>{setURL('');setError('Preview unavailable');}}/>:<Box data-stitch="file-placeholder" role={error?'status':undefined}><AttachmentIcon label=""/><Text size="small">{state||error||'Loading preview…'}</Text></Box>}<Inline data-stitch="file-actions" shouldWrap space="space.100">{!state&&<Button aria-label={'Preview '+item.name} onClick={error?()=>setRetry(value=>value+1):open}>{error?'Retry preview':'Preview'}</Button>}{item.status!=='pending'&&item.status!=='failed'&&<Button aria-label={'Download '+item.name} onClick={()=>original(group,item)}>Download</Button>}</Inline></Stack></Box>;
}
export function EvidenceGallery({group,items,commentKey}:{group:string;items:Evidence[];commentKey?:string}) {
  const [index,setIndex]=useState(-1),opener=useRef<HTMLElement|null>(null);
  const close=()=>{setIndex(-1);requestAnimationFrame(()=>{if(opener.current?.isConnected)opener.current.focus();});};
  return <Box as="section" aria-label="Complaint attachments"><Grid xcss={styles.tiles} gap="space.150">{items.map((item,i)=><EvidenceTile key={item.id} group={group} item={item} commentKey={commentKey} open={()=>{opener.current=document.activeElement as HTMLElement;setIndex(i);}}/>)}</Grid>{items[index]&&<EvidenceViewer key={items[index].id} group={group} item={items[index]} index={index} total={items.length} navigate={setIndex} close={close}/>}</Box>;
}
function EvidenceViewer({group,item,index,total,navigate,close}:{group:string;item:Evidence;index:number;total:number;navigate:(index:number)=>void;close:()=>void}) {
  const {id,name}=item;
  const [url, setURL] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState(''), [page, setPage] = useState(1), [pages, setPages] = useState(1), [zoom, setZoom] = useState(100), [fitPage,setFitPage]=useState(true);
  const controller = useRef<AbortController | null>(null);
  const image = useRef<HTMLImageElement>(null), viewport = useRef<HTMLDivElement>(null), generation = useRef(0);
  useEffect(()=>{const node=viewport.current,dialog=node?.closest('dialog'),content=node?.parentElement;if(!node||!dialog||!content)return;const size=()=>{const header=dialog.querySelector('[aria-label="Dialog header"]')?.getBoundingClientRect().height||0,body=dialog.querySelector('[aria-label="Dialog content"]'),padding=body?parseFloat(getComputedStyle(body).paddingTop)+parseFloat(getComputedStyle(body).paddingBottom):32;const other=Array.from(content.children).filter(child=>child!==node).reduce((sum,child)=>sum+child.getBoundingClientRect().height,0),gaps=parseFloat(getComputedStyle(content).rowGap||'0')*Math.max(0,content.children.length-1);const height=Math.max(96,(window.visualViewport?.height||innerHeight)*0.94-header-padding-other-gaps-4);node.style.height=`${height}px`;};const observer=new ResizeObserver(size);observer.observe(content);observer.observe(dialog.querySelector('[aria-label="Dialog header"]')!);window.addEventListener('resize',size);window.visualViewport?.addEventListener('resize',size);size();return()=>{observer.disconnect();window.removeEventListener('resize',size);window.visualViewport?.removeEventListener('resize',size);};},[]);
  const drag = useRef<{x:number;y:number;scrollX:number;scrollY:number}>();
  useEffect(() => {if(!fileState(item))void open(1);return()=>{generation.current++;controller.current?.abort();};},[]);
  useEffect(() => { if(image.current){image.current.style.width=fitPage?'100%':`${zoom}%`;image.current.style.height=fitPage?'100%':'auto';} }, [zoom, url, fitPage]);
  const open = async (selectedPage = page) => {
    controller.current?.abort(); const started = ++generation.current;
    setBusy(true); setError(''); setURL(''); const request = new AbortController(); controller.current = request;
    const timer = setTimeout(() => request.abort(), 30000);
    try {
      const data = await operation<{image:string;page:number;page_count:number}>(group, `evidence/${id}/preview/`, request.signal, {page:selectedPage});
      if(started === generation.current) {setURL(data.image);setPage(data.page);setPages(data.page_count);setZoom(100);setFitPage(true);}
    } catch (issue) { if (started === generation.current) { const detail = request.signal.aborted ? 'Preview took too long. Try again or download the file.' : message(issue); setError(detail); notify(detail, 'error'); } } finally { clearTimeout(timer); if(started === generation.current)setBusy(false); }
  };
  return <TaskDialog title={name} close={close} wide>
    <Inline spread="space-between" alignBlock="center" shouldWrap space="space.100">
      {total>1&&<Inline alignBlock="center" space="space.050"><IconButton label="Previous attachment" icon={PreviousIcon} isDisabled={index===0} onClick={()=>navigate(index-1)}/><Text size="small">File {index+1} of {total}</Text><IconButton label="Next attachment" icon={NextIcon} isDisabled={index===total-1} onClick={()=>navigate(index+1)}/></Inline>}
      {item.mime_type==='application/pdf'&&<Inline alignBlock="center" space="space.050"><IconButton label="Previous page" appearance="subtle" icon={PreviousIcon} isDisabled={busy||page<=1} onClick={()=>{void open(page-1);}}/><Text size="small">Page {page} of {pages}</Text><IconButton label="Next page" appearance="subtle" icon={NextIcon} isDisabled={busy||page>=pages} onClick={()=>{void open(page+1);}}/></Inline>}
      <IconButton label="Download original" appearance="subtle" icon={DownloadIcon} isDisabled={item.status==='pending'||item.status==='failed'} onClick={()=>original(group,item)}/>
    </Inline>
    <Inline shouldWrap alignBlock="center" space="space.050"><IconButton label="Zoom out" appearance="subtle" icon={MinusIcon} isDisabled={!fitPage&&zoom<=50} onClick={()=>{setFitPage(false);setZoom(value=>Math.max(50,value-25));}}/><Text size="small">{fitPage?'Fit page':zoom+'%'}</Text><IconButton label="Zoom in" appearance="subtle" icon={AddIcon} isDisabled={!fitPage&&zoom>=400} onClick={()=>{setFitPage(false);setZoom(value=>Math.min(400,value+25));}}/><Button appearance="subtle" aria-pressed={fitPage} onClick={()=>{setFitPage(true);viewport.current?.scrollTo(0,0);}}>Fit page</Button><Button appearance="subtle" aria-pressed={!fitPage&&zoom===100} iconBefore={RefreshIcon} onClick={()=>{setFitPage(false);setZoom(100);viewport.current?.scrollTo(0,0);}}>Fit width</Button></Inline>
    {fileState(item)&&<Text>{fileState(item)}</Text>}{busy && <Box role="status"><Text>Loading preview…</Text></Box>}{error && <Box role="alert"><Text color="color.text.danger">{error}</Text><Button onClick={() => {void open();}}>Retry preview</Button></Box>}<Box as="div" ref={viewport} xcss={styles.viewport} tabIndex={0} aria-label="Scrollable document preview" onPointerDown={(event: React.PointerEvent<HTMLDivElement>) => {if(fitPage||zoom<=100)return;drag.current={x:event.clientX,y:event.clientY,scrollX:event.currentTarget.scrollLeft,scrollY:event.currentTarget.scrollTop};event.currentTarget.setPointerCapture(event.pointerId);}} onPointerMove={(event: React.PointerEvent<HTMLDivElement>) => {const start=drag.current;if(start){event.currentTarget.scrollLeft=start.scrollX+start.x-event.clientX;event.currentTarget.scrollTop=start.scrollY+start.y-event.clientY;}}} onPointerUp={() => {drag.current=undefined;}} onPointerCancel={() => {drag.current=undefined;}}>{url && <Box as="img" ref={image} xcss={styles.image} src={url} alt={name} draggable={false} onError={() => {setError('This image could not be displayed. Download the original instead.');}}/>}</Box><Metadata item={item}/><FileProgress evidence={item.id} commentKey={commentKey}/></TaskDialog>;
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
  return <Stack space="space.100" data-stitch="voice"><Text weight="semibold">Voice-to-text</Text><Inline shouldWrap space="space.100"><Button isDisabled={busy} onClick={() => { if (recording) recorder.current?.stop(); else void record(); }}>{recording ? 'Stop recording' : 'Record note'}</Button>{audio && !attempt && <Button isLoading={busy} onClick={() => { void transcribe(); }}>Transcribe recording</Button>}{attempt && <Button onClick={() => { accept(text, attempt); setAudio(undefined); setAttempt(''); setText(''); }}>Use this text</Button>}</Inline>{recording && <Box role="status"><Text>Recording. Stops after {Math.min(30, maxSeconds)} seconds.</Text></Box>}{text && <Box role="status"><Text as="p">{text}</Text></Box>}{error && <Box role="alert"><Text color="color.text.danger">{error}</Text></Box>}</Stack>;
}
