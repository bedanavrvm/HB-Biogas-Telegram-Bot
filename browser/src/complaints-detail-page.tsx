import React, {useState} from 'react';
import Button from '@atlaskit/button/default/button';
import {IconButton} from '@atlaskit/button/new';
import CopyIcon from '@atlaskit/icon/core/copy';
import BackIcon from '@atlaskit/icon/core/arrow-left';
import PersonIcon from '@atlaskit/icon/core/person-avatar';
import FileIcon from '@atlaskit/icon/core/file';
import LocationIcon from '@atlaskit/icon/core/location';
import AttachmentIcon from '@atlaskit/icon/core/attachment';
import CommentIcon from '@atlaskit/icon/core/comment';
import Tabs,{Tab,TabList,TabPanel} from '@atlaskit/tabs';
import Heading from '@atlaskit/heading';
import {Box} from '@atlaskit/primitives/compiled/box';
import {Inline} from '@atlaskit/primitives/compiled/inline';
import {Stack} from '@atlaskit/primitives/compiled/stack';
import {Text} from '@atlaskit/primitives/compiled/text';
import {Anchor} from '@atlaskit/primitives/compiled/anchor';
import {cssMap} from '@atlaskit/css';
import {token} from '@atlaskit/tokens';
import type {Bootstrap,Detail} from './complaints-operations-transport';
import {ComplaintStatus,displayDate} from './complaints-ui';
import {notify} from './browser-interactions';
import {DetailMap} from './complaints-detail-map';
import {EvidenceGallery} from './complaints-operations-media';
import {Activity} from './complaints-operations-history';
import {Conversation,Initials} from './complaints-conversation';
import type {RecoverySlot} from './workspace-recovery';

const styles=cssMap({
  card:{backgroundColor:token('elevation.surface'),border:`${token('border.width')} solid ${token('color.border')}`,borderRadius:token('radius.large'),padding:token('space.200'),minWidth:0,overflowWrap:'anywhere'},
  header:{paddingBlockEnd:token('space.150'),marginBlockEnd:token('space.200'),borderBlockEnd:`${token('border.width')} solid ${token('color.border')}`},
  toolbar:{paddingBlock:token('space.100'),borderBlockEnd:`${token('border.width')} solid ${token('color.border')}`},
  facts:{display:'grid',gridTemplateColumns:'repeat(2,minmax(0,1fr))',gap:token('space.150')},
  reporter:{gridColumn:'1/-1',display:'flex',flexWrap:'wrap',alignItems:'center',gap:token('space.150'),padding:token('space.150'),border:`${token('border.width')} solid ${token('color.border')}`,borderRadius:token('radius.medium')},
  reporterName:{minWidth:0,flexGrow:1},
  fact:{padding:token('space.100'),border:`${token('border.width')} solid ${token('color.border')}`,borderRadius:token('radius.small'),minWidth:0},
  high:{padding:token('space.100'),border:`${token('border.width')} solid ${token('color.border')}`,borderRadius:token('radius.small'),backgroundColor:token('color.background.danger'),minWidth:0},
  body:{whiteSpace:'pre-wrap'},
});
function Card({title,icon,extra,children}:{title:string;icon:React.ReactNode;extra?:React.ReactNode;children:React.ReactNode}) {
  return <Box as="section" xcss={styles.card} aria-label={title}><Box xcss={styles.header}><Inline shouldWrap spread="space-between" alignBlock="center" space="space.100"><Inline alignBlock="center" space="space.100">{icon}<Heading as="h2" size="xsmall">{title}</Heading></Inline>{extra}</Inline></Box>{children}</Box>;
}
export function ComplaintDetailPage({group,item,bootstrap,actions,navigation,back,slot,markDirty,changed}:{group:string;item:Detail;bootstrap?:Bootstrap;actions:React.ReactNode;navigation:React.ReactNode;back:()=>void;slot:RecoverySlot;markDirty:(value:boolean,pending?:boolean)=>void;changed:()=>void}) {
  const [tab,setTab]=useState(0);
  const copy=(value:string,success:string)=>{void navigator.clipboard.writeText(value).then(()=>notify(success)).catch(()=>notify('Copy is unavailable. Select the value and copy it.','warning'));};
  return <Stack space="space.200">
    <Inline shouldWrap spread="space-between" alignBlock="center" space="space.100"><Inline shouldWrap alignBlock="center" space="space.100"><Button appearance="subtle" iconBefore={BackIcon} onClick={back}>Complaints</Button><Text size="small" color="color.text.subtle">/ {item.reference}</Text><ComplaintStatus status={item.status} needs={item.needs_details}/></Inline>{navigation}</Inline>
    <Heading as="h1" size="large">{item.category||'Customer complaint'}</Heading>
    <Box xcss={styles.toolbar}><Inline shouldWrap spread="space-between" alignBlock="center" space="space.100"><Inline shouldWrap alignBlock="center" space="space.050"><Button iconBefore={CommentIcon} appearance="subtle" onClick={()=>{setTab(0);requestAnimationFrame(()=>{const composer=document.querySelector<HTMLTextAreaElement>('textarea[name="staff-comment"]');if(composer){composer.scrollIntoView({block:'center'});composer.focus();}else document.getElementById('staff-conversation')?.scrollIntoView({block:'start'});});}}>Conversation</Button><IconButton appearance="subtle" label="Copy complaint link" icon={CopyIcon} onClick={()=>{const link=new URL(`/staff/app/complaints/cases/${item.key}/`,location.origin);link.searchParams.set('workspace',group);copy(link.href,'Complaint link copied.');}}/></Inline>{actions}</Inline></Box>
    <Card title="Customer & complaint details" icon={<PersonIcon label=""/>} extra={<Text size="small" color="color.text.subtle">{item.age_label}</Text>}><Box xcss={styles.facts}>
      <Box xcss={styles.reporter}><Initials name={item.customer_name||'Customer'}/><Stack xcss={styles.reporterName} space="space.050"><Text size="small" color="color.text.subtle">Customer / reporter</Text><Text weight="semibold">{item.customer_name||'Not recorded'}</Text></Stack><Inline alignBlock="center" space="space.050"><Text size="small">ID {item.customer_id||'Not provided'}</Text>{item.customer_id&&<IconButton label="Copy National ID" appearance="subtle" icon={CopyIcon} onClick={()=>copy(item.customer_id,'National ID copied.')}/>}</Inline></Box>
      {[['Primary phone',item.customer_phone],['Alternative phone',item.secondary_phone]].map(([label,phone])=><Box key={label} xcss={styles.fact}><Stack space="space.050"><Text size="small" color="color.text.subtle">{label}</Text>{phone?<Anchor href={'tel:'+phone}>{phone}</Anchor>:<Text>Not provided</Text>}</Stack></Box>)}
      {[['Branch',item.branch],['Complaint type',item.category],['Reported',displayDate(item.reported_at)]].map(([label,value])=><Box key={label} xcss={styles.fact}><Stack space="space.050"><Text size="small" color="color.text.subtle">{label}</Text><Text>{value||'Not recorded'}</Text></Stack></Box>)}
      <Box xcss={item.priority==='high'?styles.high:styles.fact}><Stack space="space.050"><Text size="small" color="color.text.subtle">Priority</Text><Text weight="semibold">{item.priority?item.priority[0].toUpperCase()+item.priority.slice(1)+' priority':'Not recorded'}</Text></Stack></Box>
    </Box></Card>
    <Card title="Complaint description" icon={<FileIcon label=""/>}><Box xcss={styles.body}><Text as="p">{item.description||'No description recorded.'}</Text></Box></Card>
    <Card title="Installation location" icon={<LocationIcon label=""/>}><DetailMap item={item} config={bootstrap?.map}/></Card>
    <Card title="Attachments" icon={<AttachmentIcon label=""/>} extra={<Text size="small" color="color.text.subtle">{item.evidence.length} {item.evidence.length===1?'file':'files'}</Text>}>{item.evidence.length?<EvidenceGallery group={group} items={item.evidence}/>:<Text color="color.text.subtle">No attachments yet.</Text>}</Card>
    <Box id="staff-conversation" xcss={styles.card}><Tabs id="complaint-activity" selected={tab} onChange={setTab}><TabList><Tab>Conversation</Tab><Tab>History</Tab></TabList><TabPanel><Conversation key={item.key} group={group} item={item} slot={slot} markDirty={markDirty} changed={changed} evidenceAllowed={Boolean(bootstrap?.actor.capabilities.includes('complaint.case.evidence.manage'))}/></TabPanel><TabPanel><Activity key={`${item.key}-${item.revision}-${item.history[0]?.id}`} group={group} caseKey={item.key} initial={item.history} next={item.history_next_cursor} reported={item.recorded_at||''}/></TabPanel></Tabs></Box>
  </Stack>;
}
