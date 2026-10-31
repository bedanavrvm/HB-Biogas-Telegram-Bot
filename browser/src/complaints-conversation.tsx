import React, {useEffect, useRef, useState} from 'react';
import Button from '@atlaskit/button/default/button';
import {IconButton} from '@atlaskit/button/new';
import BoldIcon from '@atlaskit/icon/core/text-bold';
import LikeIcon from '@atlaskit/icon/core/thumbs-up';
import LinkIcon from '@atlaskit/icon/core/link';
import LockIcon from '@atlaskit/icon/core/lock-locked';
import ReplyIcon from '@atlaskit/icon/core/undo';
import {cssMap} from '@atlaskit/css';
import {token} from '@atlaskit/tokens';
import {Box} from '@atlaskit/primitives/compiled/box';
import {Inline} from '@atlaskit/primitives/compiled/inline';
import {Stack} from '@atlaskit/primitives/compiled/stack';
import {Text} from '@atlaskit/primitives/compiled/text';
import Textfield from '@atlaskit/textfield';
import {Field,Label,ErrorMessage,MessageWrapper} from '@atlaskit/form';
import {operation,OperationError,type ConversationData,type StaffComment,type Detail} from './complaints-operations-transport';
import {useWorkspaceTask,TaskRecovery,TaskSession} from './workspace-task';
import {useRetainedValue,type RecoverySlot} from './workspace-recovery';
import {Files,LockedForm} from './complaints-operation-files';
import {EvidenceGallery} from './complaints-operations-media';
import {notify,dismissNotice} from './browser-interactions';
import {CopyButton} from './complaints-copy-button';

const styles=cssMap({
  body:{whiteSpace:'pre-wrap',overflowWrap:'anywhere'},
  mentions:{border:`${token('border.width')} solid ${token('color.border')}`,borderRadius:token('radius.small'),padding:token('space.100')},
});
export function Initials({name}:{name:string}) {return <div className="stitch-avatar" aria-hidden="true">{name.trim().split(/\s+/).slice(0,2).map(part=>part[0]).join('').toUpperCase()}</div>;}
const commentTime=(value:string)=>new Intl.DateTimeFormat('en-GB',{dateStyle:'medium',timeStyle:'short',timeZone:'Africa/Nairobi'}).format(new Date(value));
function Body({item}:{item:StaffComment}) {
  return <Box xcss={styles.body}><Text as="p">{item.format==='bold_v1'?item.body.split(/(\*\*[^*\n]+\*\*)/g).map((part,i)=>i%2===1?<Text key={i} weight="bold">{part.slice(2,-2)}</Text>:part):item.body}</Text></Box>;
}
function Comment({item,depth,group,caseKey,canPost,reply,jump,slot}:{item:StaffComment;depth:number;group:string;caseKey:string;canPost:boolean;reply:(item:StaffComment)=>void;jump:(key:string)=>void;slot:RecoverySlot}) {
  const [reaction,setReaction]=useState(item.reaction);
  useEffect(()=>setReaction(item.reaction),[item.reaction]);
  const task=useWorkspaceTask<typeof item.reaction>(group,slot,'reaction:'+item.id,setReaction);
  return <article className="stitch-thread-comment" id={'comment-'+item.id} data-stitch="comment" data-depth={Math.min(depth,2)} aria-label={'Comment by '+item.author} tabIndex={-1}>
    <Initials name={item.author}/><div data-stitch="comment-bubble">
      <header className="stitch-comment-header"><div className="stitch-comment-author"><strong>{item.author}</strong><span data-note-kind>{item.kind==='hb_feedback'?'HB feedback':item.affiliation||'Internal'}</span></div><time dateTime={item.created_at}>{commentTime(item.created_at)} EAT</time></header>
      {item.reply_to&&<button type="button" className="stitch-parent-quote" onClick={()=>jump(item.reply_to!.id)}><span><ReplyIcon label="" size="small"/>Reply to {item.reply_to.author}</span><span>{item.reply_to.excerpt}</span></button>}
      <Body item={item}/>{item.mentions.length>0&&<p className="stitch-comment-mentions">Mentioned: {item.mentions.map(person=>'@'+person.label).join(', ')}</p>}
      {item.evidence.length>0&&<EvidenceGallery group={group} items={item.evidence} commentKey={item.id}/>}
      <div className="stitch-comment-actions">{canPost&&<Button appearance="subtle" iconBefore={ReplyIcon} onClick={()=>reply(item)}>Reply</Button>}
        <Button appearance="subtle" iconBefore={LikeIcon} aria-label={(reaction.active?'Remove thumbs-up':'Give thumbs-up')+' on comment by '+item.author} aria-pressed={reaction.active} isSelected={reaction.active} isDisabled={!canPost||task.busy||task.uncertain} onClick={()=>{void task.save(`cases/${caseKey}/conversation/${item.id}/reaction/`,{active:!reaction.active,revision:reaction.revision,client_request_id:crypto.randomUUID()});}}>{reaction.count||'Like'}</Button>
        <CopyButton label={'Copy link to comment by '+item.author} message="Comment link copied" icon={<LinkIcon label="" size="small"/>} value={()=>{const url=new URL(`/staff/app/complaints/cases/${caseKey}/`,location.origin);url.searchParams.set('workspace',group);url.hash='comment-'+item.id;return url.href;}}/>
      </div><TaskRecovery state={task}/>
    </div>
  </article>;
}
export function Conversation({group,item,slot,markDirty,changed,evidenceAllowed,saved}:{group:string;item:Detail;slot:RecoverySlot;markDirty:(dirty:boolean,pending?:boolean)=>void;changed:()=>void;evidenceAllowed:boolean;saved:(isReply:boolean)=>void}) {
  const [data,setData]=useState<ConversationData>(),[error,setError]=useState(''),[loading,setLoading]=useState(false),[refresh,setRefresh]=useState(0),[olderBusy,setOlderBusy]=useState(false);
  const [body,setBody]=useRetainedValue(slot,'comment:body',''),[files,setFiles]=useRetainedValue<File[]>(slot,'comment:files',[]),[reply,setReply]=useRetainedValue<StaffComment|null>(slot,'comment:reply',null);
  const [mentions,setMentions]=useRetainedValue<{id:string;label:string}[]>(slot,'comment:mentions',[]),[attempt,setAttempt]=useRetainedValue<Record<string,unknown>|null>(slot,'comment:attachmentRetry',null);
  const [uploadFailure,setUploadFailure]=useRetainedValue(slot,'comment:uploadFailure',false);
  const [query,setQuery]=useState(''),[people,setPeople]=useState<{id:string;label:string}[]>([]),[mentionOpen,setMentionOpen]=useState(false),[peopleError,setPeopleError]=useState(''),[peopleLoading,setPeopleLoading]=useState(false),[validation,setValidation]=useState('');
  const editor=useRef<HTMLTextAreaElement>(null),active=useRef(true),parentRequest=useRef<AbortController>();
  const [focusParent,setFocusParent]=useState('');
  const evidenceVersion=item.evidence.map(file=>file.id+file.status).join(',');
  const recheck=React.useContext(TaskSession);
  useEffect(()=>{active.current=true;return()=>{active.current=false;parentRequest.current?.abort();};},[]);
  const task=useWorkspaceTask<ConversationData>(group,slot,'comment',result=>{
    setData(previous=>({...result,items:[...(previous?.items||[]).filter(row=>!result.items.some(current=>current.id===row.id)),...result.items]}));if(files.length)changed();
    if(result.attachment_failure&&!result.background_publication){setUploadFailure(true);notify('Comment saved. Some attachments failed. Retry the same files below.','warning');}
    else{setBody('');setFiles([]);setMentions([]);setReply(null);setAttempt(null);setUploadFailure(false);saved(Boolean(reply));}
  });
  const locked=task.busy||task.uncertain||Boolean(attempt);
  const canPost=Boolean(data?.can_post)&&!['CLOSED'].includes(item.status)&&!item.needs_details;
  useEffect(()=>{markDirty(Boolean(body||files.length||locked||reply||mentions.length),task.busy||task.uncertain);return()=>markDirty(false);},[body,files,locked,reply,mentions,task.busy,task.uncertain,markDirty]);
  useEffect(()=>{
    const controller=new AbortController();setLoading(true);setError('');
    const focus=/^#comment-([a-f0-9-]{36})$/.exec(location.hash)?.[1];
    void operation<ConversationData>(group,`cases/${item.key}/conversation/`,controller.signal,{}).then(async result=>{
      if(focus&&!result.items.some(row=>row.id===focus)){
        try {
          const target=await operation<ConversationData>(group,`cases/${item.key}/conversation/`,controller.signal,{focus});
          result={...result,items:[...target.items,...result.items]};
        } catch(issue) {
          if(!(issue instanceof OperationError)||![400,404].includes(issue.status))throw issue;
          if(!controller.signal.aborted)setError('The linked comment is unavailable. The current conversation is shown below.');
        }
      }
      if(!controller.signal.aborted){setData(result);if(focus)requestAnimationFrame(()=>{const node=document.getElementById('comment-'+focus);node?.scrollIntoView({block:'center'});node?.focus({preventScroll:true});});}
    }).catch(issue=>{if(!controller.signal.aborted){if(issue instanceof OperationError&&issue.status===401)recheck();else setError(issue instanceof OperationError?issue.message:'Conversation could not be loaded.');}}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[group,item.key,item.revision,item.status,refresh,evidenceVersion]);
  useEffect(()=>{
    if(!mentionOpen)return;
    const controller=new AbortController();setPeopleLoading(true);setPeopleError('');setPeople([]);
    const timer=setTimeout(()=>{void operation<{people:{id:string;label:string}[]}>(group,`cases/${item.key}/conversation/people/`,controller.signal,{query}).then(result=>{if(!controller.signal.aborted)setPeople(result.people);}).catch(()=>{if(!controller.signal.aborted)setPeopleError('Staff names could not be loaded. Try again.');}).finally(()=>{if(!controller.signal.aborted)setPeopleLoading(false);});},200);
    return()=>{clearTimeout(timer);controller.abort();};
  },[query,mentionOpen,group,item.key]);
  const older=async()=>{if(olderBusy||!data?.next_cursor)return;setOlderBusy(true);try{const result=await operation<ConversationData>(group,`cases/${item.key}/conversation/`,new AbortController().signal,{cursor:data.next_cursor});if(active.current)setData(previous=>({...result,items:[...result.items,...(previous?.items||[]).filter(row=>!result.items.some(other=>other.id===row.id))].sort((a,b)=>a.created_at.localeCompare(b.created_at)||a.id.localeCompare(b.id))}));}catch{if(active.current)setError('Older comments could not be loaded. Refresh the conversation and try again.');}finally{if(active.current)setOlderBusy(false);}};
  const send=()=>{
    if(attempt){void task.save(`cases/${item.key}/conversation/post/`,attempt,files);return;}
    if(!body.trim()){setValidation('Enter a comment.');editor.current?.focus();return;}
    const values={body,reply_to:reply?.id||'',mentions:JSON.stringify(mentions.map(person=>person.id)),expected_revision:item.revision,client_request_id:crypto.randomUUID()};
    if(files.length)setAttempt(values);
    void task.save(`cases/${item.key}/conversation/post/`,values,files);
  };
  const rows=(data?.items||[]).slice().sort((a,b)=>Date.parse(a.created_at)-Date.parse(b.created_at)||a.id.localeCompare(b.id));
  const ids=new Set(rows.map(row=>row.id)),children=new Map<string,StaffComment[]>();
  rows.forEach(row=>{if(row.reply_to&&ids.has(row.reply_to.id)){const siblings=children.get(row.reply_to.id)||[];siblings.push(row);children.set(row.reply_to.id,siblings);}});
  const roots=rows.filter(row=>!row.reply_to||!ids.has(row.reply_to.id));
  const ordered:{item:StaffComment;depth:number}[]=[],seen=new Set<string>();
  for(const root of [...roots,...rows]){
    const pending=[{item:root,depth:root.reply_to?1:0}];
    while(pending.length){
      const node=pending.pop()!;if(seen.has(node.item.id))continue;
      seen.add(node.item.id);ordered.push(node);
      const replies=children.get(node.item.id)||[];
      for(let index=replies.length-1;index>=0;index--)pending.push({item:replies[index],depth:node.depth+1});
    }
  }
  const jump=async(key:string)=>{
    const node=document.getElementById('comment-'+key);
    if(node){node.scrollIntoView({block:'center'});node.focus({preventScroll:true});return;}
    parentRequest.current?.abort();const controller=new AbortController();parentRequest.current=controller;
    try{
      const result=await operation<ConversationData>(group,`cases/${item.key}/conversation/`,controller.signal,{focus:key});
      if(!controller.signal.aborted){setData(previous=>previous?{...previous,items:[...previous.items,...result.items.filter(row=>!previous.items.some(current=>current.id===row.id))]}:result);setFocusParent(key);}
    }catch(issue){if(!controller.signal.aborted){if(issue instanceof OperationError&&issue.status===401)recheck();else notify('The replied message could not be opened. Your draft is retained.','warning');}}
  };
  useEffect(()=>{if(!focusParent)return;const node=document.getElementById('comment-'+focusParent);if(node){node.scrollIntoView({block:'center'});node.focus({preventScroll:true});setFocusParent('');}},[focusParent,data]);
  useEffect(()=>{if(!error)return;const id=notify(error,'error',{dedupeKey:'conversation-read:'+item.key});return()=>dismissNotice(id);},[error,item.key]);
  useEffect(()=>{if(!validation)return;const id=notify(validation,'warning',{dedupeKey:'conversation-validation:'+item.key});return()=>dismissNotice(id);},[validation,item.key]);
  return <Stack space="space.100">
    <Inline shouldWrap alignBlock="center" spread="space-between"><Text size="small" color="color.text.subtle">{data?`${data.total} ${data.total===1?'comment':'comments'}`:'Staff conversation'}</Text><Button appearance="subtle" isLoading={loading} onClick={()=>{setRefresh(value=>value+1);changed();}}>Refresh conversation</Button></Inline>
    {error&&<Box role="alert"><Text color="color.text.danger">{error}</Text></Box>}
    {data?.next_cursor&&<Inline><Button isLoading={olderBusy} onClick={()=>{void older();}}>Load older comments</Button></Inline>}
    {ordered.map(({item:row,depth})=><Comment key={row.id} item={row} depth={depth} jump={key=>{void jump(key);}} group={group} caseKey={item.key} canPost={canPost} slot={slot} reply={row=>{setReply(row);editor.current?.focus();editor.current?.scrollIntoView({block:'center'});}}/>)}
    {data&&!rows.length&&<Text color="color.text.subtle">No comments yet. Start the staff conversation below.</Text>}
    {!canPost&&data&&<Text color="color.text.subtle">{item.status==='CLOSED'?'This complaint is closed. An authorized JBL colleague can reopen it to continue the conversation.':item.needs_details?'Complete the missing customer details before commenting.':'Your role has read-only access to this conversation.'}</Text>}
    {(canPost||body||files.length>0)&&<Box as="form" data-stitch="composer" onSubmit={(event:React.FormEvent)=>{event.preventDefault();send();}}><Stack space="space.100">
      {reply&&<Inline shouldWrap alignBlock="center" space="space.100"><div className="stitch-composer-reply"><strong>Replying to {reply.author}</strong><span>{reply.body}</span></div><Button appearance="subtle" isDisabled={locked} onClick={()=>setReply(null)}>Cancel reply</Button></Inline>}
      <Field<string,HTMLTextAreaElement> name="staff-comment" label={<><LockIcon label="" size="small"/>Add internal note</>} defaultValue={body} isRequired>{({fieldProps})=><><Box as="textarea" {...fieldProps} ref={editor} aria-label="Add to the staff conversation" aria-labelledby={undefined} placeholder="Write internal triage notes visible to staff with access..." value={body} rows={3} maxLength={5000} readOnly={locked||!canPost} aria-invalid={Boolean(validation)} aria-describedby={validation?'comment-error':fieldProps['aria-describedby']} onChange={event=>{fieldProps.onChange(event);setBody(event.currentTarget.value);setValidation('');}}/><MessageWrapper>{validation&&<Box id="comment-error"><ErrorMessage>{validation}</ErrorMessage></Box>}</MessageWrapper></>}</Field>
      <div className="stitch-composer-tools">{evidenceAllowed&&<LockedForm.Provider value={locked||!canPost}><Files files={files} setFiles={setFiles} saveLabel="comment" compact/></LockedForm.Provider>}<IconButton icon={BoldIcon} label="Bold selected text" appearance="subtle" isDisabled={locked||!canPost} onClick={()=>{const node=editor.current;if(!node)return;const start=node.selectionStart,end=node.selectionEnd;setBody(body.slice(0,start)+'**'+(body.slice(start,end)||'bold text')+'**'+body.slice(end));requestAnimationFrame(()=>{node.focus();node.setSelectionRange(start+2,(end>start?end:start+9)+2);});}}/><Button appearance="subtle" aria-label="Mention staff" isDisabled={locked||!canPost||mentions.length>=10} aria-expanded={mentionOpen} onClick={()=>setMentionOpen(value=>!value)}>@</Button><Button type="submit" appearance="primary" aria-label={uploadFailure&&attempt?'Retry attachments':'Add comment'} isLoading={task.busy} isDisabled={(!canPost&&!(uploadFailure&&attempt))||task.uncertain}>{uploadFailure&&attempt?'Retry attachments':'Save Note'}</Button></div>
      {mentionOpen&&<Box xcss={styles.mentions}><Stack space="space.100"><Label htmlFor="mention-staff">Find staff to mention</Label><Textfield id="mention-staff" value={query} onChange={event=>setQuery(event.currentTarget.value)} placeholder="Search staff names"/>{peopleLoading?<Text size="small">Loading staff…</Text>:peopleError?<Text color="color.text.danger">{peopleError}</Text>:<Inline shouldWrap space="space.050">{people.filter(person=>!mentions.some(current=>current.id===person.id)).map(person=><Button key={person.id} appearance="subtle" onClick={()=>{setMentions([...mentions,person]);setBody(body+(body&&!body.endsWith(' ')?' ':'')+'@'+person.label+' ');setMentionOpen(false);editor.current?.focus();}}>{person.label}</Button>)}{!people.length&&<Text size="small">No matching staff with access.</Text>}</Inline>}</Stack></Box>}
      {mentions.length>0&&<Inline shouldWrap space="space.100">{mentions.map(person=><Button key={person.id} isDisabled={locked} aria-label={'Remove mention of '+person.label} onClick={()=>setMentions(mentions.filter(row=>row.id!==person.id))}>@{person.label} ×</Button>)}</Inline>}
      <TaskRecovery state={task}/>
      {attempt&&!task.busy&&!task.uncertain&&Boolean(task.error)&&<Button onClick={()=>setAttempt(null)}>Review comment before retrying</Button>}
      {uploadFailure&&attempt&&<Text>Comment saved. Retry attachment publication with the same text and files.</Text>}
      <div className="stitch-composer-help"><span>Staff with access to this complaint only.</span><span>{body.length} / 5,000</span></div>
    </Stack></Box>}
  </Stack>;
}
