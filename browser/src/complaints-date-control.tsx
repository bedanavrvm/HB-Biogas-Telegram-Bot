import React, {useEffect, useState} from 'react';
import Button from '@atlaskit/button/default/button';
import {IconButton} from '@atlaskit/button/new';
import CalendarIcon from '@atlaskit/icon/core/calendar';
import PreviousIcon from '@atlaskit/icon/core/chevron-left';
import NextIcon from '@atlaskit/icon/core/chevron-right';
import {Label} from '@atlaskit/form';
import Textfield from '@atlaskit/textfield';
import {Box} from '@atlaskit/primitives/compiled/box';
import {Grid} from '@atlaskit/primitives/compiled/grid';
import {Inline} from '@atlaskit/primitives/compiled/inline';
import {Text} from '@atlaskit/primitives/compiled/text';
import {cssMap} from '@atlaskit/css';
import {AdaptiveSelect, TaskDialog, displayDate} from './complaints-ui';
const styles=cssMap({calendar:{gridTemplateColumns:'repeat(7, minmax(0, 1fr))'},field:{minWidth:0,flexGrow:1},day:{textAlign:'center'}});
const months=Array.from({length:12},(_,index)=>({value:String(index),label:new Intl.DateTimeFormat('en-GB',{month:'long',timeZone:'UTC'}).format(new Date(Date.UTC(2026,index,1)))}));
function parse(value:string) {
  const iso=/^\d{4}-\d{2}-\d{2}$/.test(value)?value:'';
  const match=/^(\d{1,2}) ([A-Za-z]{3}) (\d{4})$/.exec(value.trim());
  const month=match?months.findIndex(item=>item.label.slice(0,3).toLowerCase()===match[2].toLowerCase()):-1;
  const result=iso||(match&&month>=0?`${match[3]}-${String(month+1).padStart(2,'0')}-${match[1].padStart(2,'0')}`:'');
  const date=new Date(result+'T12:00:00Z');
  return result&&Number(result.slice(0,4))>=1900&&Number(result.slice(0,4))<=9998&&!Number.isNaN(date.valueOf())&&date.toISOString().slice(0,10)===result?result:'';
}
/** Product calendar and text entry; no native date-picker UI. */
export function DateControl({id,label,value,change}:{id:string;label:string;value:string;change:(value:string)=>void}) {
  const [text,setText]=useState(value?displayDate(value):''),[error,setError]=useState(''),[open,setOpen]=useState(false);
  const initial=(value||new Intl.DateTimeFormat('en-CA',{timeZone:'Africa/Nairobi',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())).split('-').map(Number);
  const [year,setYear]=useState(initial[0]),[month,setMonth]=useState(initial[1]-1);
  useEffect(()=>{setText(value?displayDate(value):'');setError('');if(value){setYear(Number(value.slice(0,4)));setMonth(Number(value.slice(5,7))-1);}},[value]);
  const accept=(day:number)=>{const next=`${year}-${String(month+1).padStart(2,'0')}-${String(day).padStart(2,'0')}`;change(next);setOpen(false);};
  const move=(delta:number)=>{const date=new Date(Date.UTC(year,month+delta,1));if(date.getUTCFullYear()>=1900&&date.getUTCFullYear()<=9998){setYear(date.getUTCFullYear());setMonth(date.getUTCMonth());}};
  const first=(new Date(Date.UTC(year,month,1)).getUTCDay()+6)%7,days=new Date(Date.UTC(year,month+1,0)).getUTCDate();
  return <Box><Label htmlFor={id}>{label}</Label><Inline alignBlock="center" space="space.050"><Box xcss={styles.field}><Textfield id={id} value={text}  aria-invalid={Boolean(error)} aria-describedby={id+'-format'} onChange={event=>setText(event.currentTarget.value)} onBlur={()=>{const next=parse(text);if(next){change(next);setText(displayDate(next));setError('');}else setError('Enter a date such as 5 Oct 2026.');}}/></Box><IconButton label={`Choose ${label.toLowerCase()}`} icon={CalendarIcon} onClick={()=>setOpen(true)}/></Inline><Text id={id+'-format'} size="small" color="color.text.subtle">Day, month and year, e.g. 5 Oct 2026</Text>{error&&<Text id={id+'-error'} size="small" color="color.text.danger">{error}</Text>}
    {open&&<TaskDialog title={`Choose ${label.toLowerCase()}`} compact close={()=>setOpen(false)}><Inline spread="space-between" alignBlock="center"><IconButton label="Previous month" icon={PreviousIcon} onClick={()=>move(-1)}/><Text weight="semibold">{months[month].label} {year}</Text><IconButton label="Next month" icon={NextIcon} onClick={()=>move(1)}/></Inline><Grid xcss={styles.calendar} gap="space.050">{['M','T','W','T','F','S','S'].map((name,index)=><Box key={index} xcss={styles.day}><Text size="small" color="color.text.subtle">{name}</Text></Box>)}{Array.from({length:first},(_,index)=><Box key={'blank'+index}/>)}{Array.from({length:days},(_,index)=><Button key={index} isSelected={value===`${year}-${String(month+1).padStart(2,'0')}-${String(index+1).padStart(2,'0')}`} aria-label={`${index+1} ${months[month].label} ${year}`} onClick={()=>accept(index+1)}>{index+1}</Button>)}</Grid><Inline space="space.100"><Box xcss={styles.field}><Label htmlFor={id+'-month'}>Month</Label><AdaptiveSelect inputId={id+'-month'} options={months} value={months[month]} onChange={item=>{if(item)setMonth(Number(item.value));}}/></Box><Box xcss={styles.field}><Label htmlFor={id+'-year'}>Year</Label><Textfield id={id+'-year'} type="number" min={1900} max={9998} value={year} onChange={event=>{const next=Number(event.currentTarget.value);if(next>=1900&&next<=9998)setYear(next);}}/></Box></Inline></TaskDialog>}
  </Box>;
}
