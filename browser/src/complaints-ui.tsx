import React, { createContext, useCallback, useContext, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Button from '@atlaskit/button/default/button';
import { IconButton } from '@atlaskit/button/new';
import CrossIcon from '@atlaskit/icon/core/cross';
import CheckIcon from '@atlaskit/icon/core/check-mark';
import WarningIcon from '@atlaskit/icon/core/status-warning';
import ErrorIcon from '@atlaskit/icon/core/status-error';
import EditIcon from '@atlaskit/icon/core/edit';
import RefreshIcon from '@atlaskit/icon/core/refresh';
import ChevronDownIcon from '@atlaskit/icon/core/chevron-down';
import Select, { type SelectProps } from '@atlaskit/select';
import { cssMap, cx } from '@atlaskit/css';
import Lozenge from '@atlaskit/lozenge';
import Heading from '@atlaskit/heading';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import { token } from '@atlaskit/tokens';
import {notify,dismissNotice} from './browser-interactions';

export const statusLabel = (status: string, needs = false) => needs ? 'Needs details' : /^(closed|resolved)$/i.test(status) ? 'Closed' : /^reopened$/i.test(status) ? 'Reopened' : 'Open';
export const complaintCount = (value: number) => `${value} ${value === 1 ? 'complaint' : 'complaints'}`;
export function ComplaintStatus({ status, needs = false }: { status: string; needs?: boolean }) {
  const label = statusLabel(status, needs);
  return <Lozenge appearance={label === 'Closed' ? 'success' : label === 'Open' ? 'inprogress' : 'moved'}>{label}</Lozenge>;
}
export function displayDate(value: string, month = false) {
  if (!value) return 'Not recorded';
  const stamp = /^\d{4}(?:-\d{2})?$/.test(value) ? value.length === 4 ? value + '-01-01' : value + '-01' : value;
  const parsed = /^\d{4}-\d{2}-\d{2}/.test(stamp) ? new Date(stamp.slice(0, 10) + 'T12:00:00Z') : new Date(stamp);
  return Number.isNaN(parsed.valueOf()) ? value : new Intl.DateTimeFormat('en-GB', { ...(month ? {} : { day: 'numeric' }), month: 'short', year: 'numeric', timeZone: 'Africa/Nairobi' }).format(parsed).replace(/Sept\b/, 'Sep');
}
const styles = cssMap({
  dialog: { font: token('font.body'), width: '94vw', maxWidth: '46rem', maxHeight: '94vh', boxSizing: 'border-box', padding: 0, borderWidth: token('border.width'), borderStyle: 'solid', borderColor: token('color.border'), borderRadius: token('radius.large'), backgroundColor: token('elevation.surface.overlay'), color: token('color.text'), boxShadow: token('elevation.shadow.overlay'), overflow: 'visible' },
  frame: { display: 'grid', gridTemplateRows: 'auto minmax(0, 1fr) auto', maxHeight: '94vh', minHeight: 0 },
  header: { padding: token('space.200'), borderBlockEnd: `${token('border.width')} solid ${token('color.border')}` },
  body: { padding: token('space.200'), overflowY: 'auto', minHeight: 0, overscrollBehavior: 'contain' },
  footer: { padding: token('space.200'), borderBlockStart: `${token('border.width')} solid ${token('color.border')}`, '&:empty': { display: 'none' } },
  footerActions: { display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: token('space.100'), width: '100%', maxWidth: '24rem', marginInlineStart: 'auto' },
  status: { height: '1.75rem', display: 'flex', alignItems: 'center', minWidth: 0 },
  icon: { display: 'inline-flex' },
  statusChip: { display: 'inline-flex', alignItems: 'center', gap: token('space.050'), paddingInline: token('space.100'), paddingBlock: token('space.025'), borderRadius: token('radius.small'), backgroundColor: token('color.background.neutral'), color: token('color.text.subtle') },
  success: { color: token('color.text.success'), backgroundColor: token('color.background.success') },
  warning: { color: token('color.text.warning'), backgroundColor: token('color.background.warning') },
  error: { color: token('color.text.danger'), backgroundColor: token('color.background.danger') },
  positive: { display: 'inline-flex' },
  fit: { width: '100%', minWidth: 0 },
  section: { borderBlockStart: `${token('border.width')} solid ${token('color.border')}`, paddingBlockStart: token('space.200') },
  compact: { maxWidth: '32rem' },
  medium: { maxWidth: '45rem' },
  wide: { width: '98vw', maxWidth: '90rem' },
  menuAnchor: { display: 'inline-flex', minWidth: 0 },
  controls: { display: 'flex', flexWrap:'wrap', alignItems: 'center', gap: token('space.100') },
  gutter: { width: 0, flexShrink: 0 },
  menu: { position: 'fixed', margin: 0, padding: token('space.100'), minWidth: '12rem', maxWidth: '90vw', maxHeight: '60vh', overflowY: 'auto', borderWidth: token('border.width'), borderStyle: 'solid', borderColor: token('color.border'), borderRadius: token('radius.medium'), backgroundColor: token('elevation.surface.overlay'), color: token('color.text'), boxShadow: token('elevation.shadow.overlay') },
});
type DialogSlots = { root: HTMLDialogElement | null; status: HTMLDivElement | null; footer: HTMLDivElement | null };
const DialogContext = createContext<DialogSlots>({root:null,status:null,footer:null});
let bodyLocks=0, previousOverflow='';
export function DialogStatus({children}:{children:React.ReactNode}) { const {status}=useContext(DialogContext);return status?createPortal(children,status):null; }
export function DialogFooter({children}:{children:React.ReactNode}) {
  const {footer}=useContext(DialogContext),root=useRef<HTMLDivElement>(null);
  useLayoutEffect(()=>{const node=root.current;if(!node)return;const measure=()=>{node.style.gridTemplateColumns='repeat(2, minmax(0, 1fr))';if(node.clientWidth<18*parseFloat(getComputedStyle(document.documentElement).fontSize)||Array.from(node.querySelectorAll('button span')).some(span=>span.clientWidth>0&&span.scrollWidth>span.clientWidth+1))node.style.gridTemplateColumns='minmax(0, 1fr)';};const resize=new ResizeObserver(measure),text=new MutationObserver(measure);resize.observe(node);text.observe(document.documentElement,{attributes:true,attributeFilter:['style']});measure();return()=>{resize.disconnect();text.disconnect();};},[footer]);
  return footer?createPortal(<Box ref={root} xcss={styles.footerActions}>{children}</Box>,footer):null;
}
export function Section({title,children}:{title:string;children:React.ReactNode}) { return <Box xcss={styles.section}><Stack space="space.150"><Heading as="h3" size="small">{title}</Heading>{children}</Stack></Box>; }
export function useValidationFocus(formId:string,errors:Record<string,string>) {
  const errorKey=JSON.stringify(errors);
  useEffect(()=>{
    if(!Object.keys(errors).length)return;
    const focus=()=>{const input=document.getElementById(formId)?.querySelector<HTMLElement>('[aria-invalid="true"]');input?.focus();input?.scrollIntoView({block:'nearest'});};
    const frame=requestAnimationFrame(focus),id=notify('Review the highlighted fields before saving.','warning',{dedupeKey:'form-validation:'+formId,action:{label:'Review fields',run:focus}});
    return()=>{cancelAnimationFrame(frame);dismissNotice(id);};
  },[formId,errorKey]);
}

export function ActionButton({tone='positive',...props}:React.ComponentProps<typeof Button>&{tone?:'positive'|'destructive'|'neutral'}) {
  const root=useRef<HTMLDivElement>(null);
  useLayoutEffect(()=>{const node=root.current;if(!node)return;const colors=[['--ds-background-brand-bold',token('color.background.success.bold')],['--ds-background-brand-bold-hovered',token('color.background.success.bold.hovered')],['--ds-background-brand-bold-pressed',token('color.background.success.bold.pressed')]];colors.forEach(([key,value])=>{if(tone==='positive')node.style.setProperty(key,value);else node.style.removeProperty(key);});},[tone]);
  return <Box ref={root} xcss={cx(styles.positive,props.shouldFitContainer&&styles.fit)}><Button {...props} appearance={tone==='destructive'?'danger':tone==='positive'?'primary':props.appearance||'default'}/></Box>;
}
export function DraftStatus({state}:{state:'draft'|'saving'|'saved'|'offline'|'error'}) {
  const icon=useRef<HTMLSpanElement>(null);
  useEffect(()=>{if(state!=='saving'||matchMedia('(prefers-reduced-motion: reduce)').matches)return;const animation=icon.current?.animate([{transform:'rotate(0deg)'},{transform:'rotate(360deg)'}],{duration:1000,iterations:Infinity});return()=>animation?.cancel();},[state]);
  const Icon=state==='saved'?CheckIcon:state==='saving'?RefreshIcon:state==='offline'?WarningIcon:state==='error'?ErrorIcon:EditIcon;
  return <Box xcss={cx(styles.statusChip,state==='saved'&&styles.success,state==='offline'&&styles.warning,state==='error'&&styles.error)}><Box as="span" ref={icon} xcss={styles.icon}><Icon label="" size="small"/></Box><Text size="small" weight="medium" color="inherit">{{draft:'Draft',saving:'Saving…',saved:'Saved',offline:'Offline',error:'Not saved'}[state]}</Text></Box>;
}
/** Portals stay in the modal's accessible layer, not its scrolling body. */
export function AdaptiveSelect<Option extends {label:string;value:string|number},Multi extends boolean=false>(props:SelectProps<Option,Multi>) {
  const dialog=useContext(DialogContext),root=useRef<HTMLDivElement>(null),[maxHeight,setMaxHeight]=useState(320),[open,setOpen]=useState(false);
  useEffect(()=>{if(!open)return;const measure=()=>{const bounds=root.current?.getBoundingClientRect();if(!bounds)return;const viewport=window.visualViewport;const top=viewport?.offsetTop||0,bottom=top+(viewport?.height||innerHeight);setMaxHeight(Math.max(64,Math.min(320,Math.max(bounds.top-top,bottom-bounds.bottom)-16)));};measure();window.visualViewport?.addEventListener('resize',measure);window.addEventListener('resize',measure);return()=>{window.visualViewport?.removeEventListener('resize',measure);window.removeEventListener('resize',measure);};},[open]);
  return <Box ref={root} xcss={styles.fit}><Select {...props} isSearchable menuPortalTarget={dialog.root||undefined} menuPosition="fixed" menuPlacement="auto" maxMenuHeight={maxHeight} menuShouldScrollIntoView={false} captureMenuScroll onMenuOpen={()=>{setOpen(true);props.onMenuOpen?.();}} onMenuClose={()=>{setOpen(false);props.onMenuClose?.();}}/></Box>;
}
/** Native modal focus/inert/Escape semantics with the existing ADS content. */
export function TaskDialog({ title, close, children, compact = false, wide = false, size, hasStatus=false, placement="center" }: { title: string; close: () => void; children: React.ReactNode; compact?: boolean; wide?: boolean; size?:'medium';hasStatus?:boolean;placement?:"center"|"top"|"bottom" }) {
  const ref = useRef<HTMLDialogElement|null>(null), heading = useId();
  const [online,setOnline]=useState(navigator.onLine);
  useEffect(()=>{const update=()=>setOnline(navigator.onLine);window.addEventListener('online',update);window.addEventListener('offline',update);return()=>{window.removeEventListener('online',update);window.removeEventListener('offline',update);};},[]);
  const scrimDown = useRef(false);
  const [root,setRoot]=useState<HTMLDialogElement|null>(null),[status,setStatus]=useState<HTMLDivElement|null>(null),[footer,setFooter]=useState<HTMLDivElement|null>(null);
  const bind=useCallback((node:HTMLDialogElement|null)=>{ref.current=node;setRoot(node);},[]);
  const closeRef = useRef(close); closeRef.current = close;
  useEffect(() => {
    const dialog=ref.current!,opener=document.activeElement as HTMLElement|null;
    if(bodyLocks++===0){previousOverflow=document.body.style.overflow;document.body.style.overflow='hidden';}
    dialog.showModal();
    const cancel=(event:Event)=>{event.preventDefault();closeRef.current();};dialog.addEventListener('cancel',cancel);
    return()=>{dialog.removeEventListener('cancel',cancel);dialog.close();if(--bodyLocks===0)document.body.style.overflow=previousOverflow;if(opener?.isConnected)opener.focus();};
  },[]);
  useLayoutEffect(()=>{
    const dialog=root;if(!dialog)return;
    const size=()=>{const mobile=innerWidth<64*parseFloat(getComputedStyle(document.documentElement).fontSize);dialog.querySelectorAll('input').forEach(input=>{if(mobile)input.style.font=token('font.body.large');else input.style.removeProperty('font');});};
    const observer=new MutationObserver(size);observer.observe(dialog,{childList:true,subtree:true});window.addEventListener('resize',size);size();return()=>{observer.disconnect();window.removeEventListener('resize',size);};
  },[root]);
  const outside = (event: React.PointerEvent<HTMLDialogElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return event.target === event.currentTarget && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom);
  };
  return <Box as="dialog" ref={bind} data-placement={placement} style={placement==='top'?{marginBlockStart:'4.5rem',marginBlockEnd:'auto',maxHeight:'calc(100dvh - 5rem)'}:undefined} aria-labelledby={heading} onPointerDown={event=>{scrimDown.current=outside(event);}} onPointerUp={event=>{const dismiss=scrimDown.current&&outside(event);scrimDown.current=false;if(dismiss)closeRef.current();}} onPointerCancel={()=>{scrimDown.current=false;}} xcss={cx(styles.dialog,compact&&styles.compact,size==='medium'&&styles.medium,wide&&styles.wide)}><DialogContext.Provider value={{root,status,footer}}><Box xcss={styles.frame}><Box xcss={styles.header} aria-label="Dialog header"><Inline spread="space-between" alignBlock="start" space="space.150"><Stack space="space.050"><Heading id={heading} as="h2" size="medium">{title}</Heading>{hasStatus&&<Box ref={setStatus} xcss={styles.status} role="status" aria-live="polite" aria-atomic="true" aria-label="Draft save status"/>}</Stack><IconButton label="Close" appearance="subtle" icon={CrossIcon} onClick={close}/></Inline></Box><Box xcss={styles.body} aria-label="Dialog content"><Stack space="space.200">{hasStatus&&!online&&<Box role="status"><Text color="color.text.warning">You are offline. Keep editing and reconnect before saving. Nothing is submitted automatically.</Text></Box>}{children}</Stack></Box><Box ref={setFooter} xcss={styles.footer} aria-label="Dialog actions"/></Box></DialogContext.Provider></Box>;
}

type Confirmation = { message: string; title: string; accept: string; cancel: string; resolve: (value: boolean) => void };
const confirmationEvent = 'jbl-browser-confirmation';
/** One transient confirmation; no window.confirm, customer storage or implicit save. */
export function confirmAction(message: string, options: Partial<Pick<Confirmation, 'title'|'accept'|'cancel'>> = {}) {
  return new Promise<boolean>(resolve=>window.dispatchEvent(new CustomEvent<Confirmation>(confirmationEvent,{detail:{message,title:'Discard changes?',accept:'Discard changes',cancel:'Keep editing',...options,resolve}})));
}
export function ConfirmationHost() {
  const [requests,setRequests]=useState<Confirmation[]>([]), pending=useRef<Confirmation[]>([]);
  const answer=(value:boolean)=>{const [request,...remaining]=pending.current;pending.current=remaining;setRequests(remaining);request?.resolve(value);};
  useEffect(()=>{const receive=(event:Event)=>{pending.current=[...pending.current,(event as CustomEvent<Confirmation>).detail];setRequests(pending.current);};window.addEventListener(confirmationEvent,receive);return()=>{window.removeEventListener(confirmationEvent,receive);pending.current.forEach(request=>request.resolve(false));pending.current=[];};},[]);
  const current=requests[0];
  return current?<TaskDialog title={current.title} placement="top" compact close={()=>answer(false)}><Text>{current.message}</Text><DialogFooter><Button onClick={()=>answer(false)} autoFocus>{current.cancel}</Button><ActionButton tone="destructive" onClick={()=>answer(true)}>{current.accept}</ActionButton></DialogFooter></TaskDialog>:null;
}

type MenuItem = { label: string; run: ()=>void|Promise<void>; disabled?: boolean; selected?: boolean };
export function ActionMenu({label,icon,items,heading,text}:{label:string;text?:string;icon?:React.ComponentProps<typeof IconButton>['icon'];items:MenuItem[];heading?:string}) {
  const [open,setOpen]=useState(false),anchor=useRef<HTMLDivElement>(null),panel=useRef<HTMLDivElement>(null),id=useId();
  useEffect(()=>{
    if(!open)return;const node=panel.current!;node.setAttribute('popover','auto');
    const place=()=>{const bounds=anchor.current!.getBoundingClientRect(),height=window.visualViewport?.height||innerHeight;if(bounds.bottom<0||bounds.top>height){setOpen(false);return;}const below=bounds.bottom+4,above=bounds.top-node.offsetHeight-4;node.style.insetInlineStart=`${Math.max(8,Math.min(bounds.left,innerWidth-node.offsetWidth-8))}px`;node.style.top=`${Math.max(8,below+node.offsetHeight<=height-8?below:above>=8?above:height-node.offsetHeight-8)}px`;};
    const toggle=(event:Event)=>{if((event as ToggleEvent).newState==='closed')setOpen(false);};
    node.addEventListener('toggle',toggle);node.showPopover();place();node.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus();
    window.addEventListener('resize',place);
    window.addEventListener('scroll',place,true);
    return()=>{node.removeEventListener('toggle',toggle);window.removeEventListener('resize',place);window.removeEventListener('scroll',place,true);if(node.matches(':popover-open'))node.hidePopover();};
  },[open]);
  const close=()=>{setOpen(false);anchor.current?.querySelector<HTMLButtonElement>('button')?.focus();};
  const keyboard=(event:React.KeyboardEvent<HTMLDivElement>)=>{const buttons=Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'));const index=buttons.indexOf(document.activeElement as HTMLButtonElement);if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();buttons[(index+(event.key==='ArrowDown'?1:buttons.length-1))%buttons.length]?.focus();}else if(event.key==='Escape'){event.preventDefault();close();}};
  return <Box ref={anchor} xcss={styles.menuAnchor}>{text?<button type="button" aria-label={label} aria-haspopup="menu" aria-expanded={open} aria-controls={open?id:undefined} onClick={()=>setOpen(value=>!value)}>{icon&&React.createElement(icon,{label:""})}<span>{text}</span></button>:icon?<IconButton appearance="subtle" label={label} icon={icon} aria-haspopup="menu" aria-expanded={open} aria-controls={open?id:undefined} onClick={()=>setOpen(value=>!value)}/>:<Button iconAfter={ChevronDownIcon} aria-haspopup="menu" aria-expanded={open} aria-controls={open?id:undefined} onClick={()=>setOpen(value=>!value)}>{label}</Button>}{open&&<Box ref={panel} id={id} role="menu" aria-label={label} xcss={styles.menu} onKeyDown={keyboard}><Stack space="space.050">{heading&&<Box role="presentation"><Text weight="semibold">{heading}</Text></Box>}{items.map(item=><Button key={item.label} appearance="subtle" shouldFitContainer role={item.selected===undefined?'menuitem':'menuitemradio'} aria-checked={item.selected} isDisabled={item.disabled} isSelected={item.selected} onClick={()=>{close();void item.run();}}>{item.label}</Button>)}</Stack></Box>}</Box>;
}

/** Match actual control boxes; does not restyle ADS labels, colours or focus. */
export function ControlRow({children}:{children:React.ReactNode}) {
  const root=useRef<HTMLDivElement>(null);
  useLayoutEffect(()=>{const measure=()=>{const node=root.current;if(!node)return;const height=innerWidth>=1024?40:44;node.querySelectorAll('button').forEach(button=>{button.style.minHeight=`${height}px`;});node.querySelectorAll('input').forEach(input=>{const container=input.parentElement;if(container)container.style.minHeight=`${height}px`;input.style.font=innerWidth<1024?token('font.body.large'):token('font.body');});};measure();window.addEventListener('resize',measure);return()=>window.removeEventListener('resize',measure);},[]);
  return <Box ref={root} xcss={styles.controls}>{children}</Box>;
}

export function HeaderGutter({side}:{side:'start'|'end'}) {
  const ref=useRef<HTMLDivElement>(null);
  useLayoutEffect(()=>{const page=document.querySelector<HTMLElement>('[data-testid="complaints-operations-content"]');const node=ref.current;if(!page||!node)return;const measure=()=>{const bounds=page.getBoundingClientRect(),box=node.getBoundingClientRect(),style=getComputedStyle(page);node.style.width=`${Math.max(0,side==='start'?bounds.left+parseFloat(style.paddingLeft)-box.left:box.right-bounds.right+parseFloat(style.paddingRight))}px`;};const observer=new ResizeObserver(measure);observer.observe(page);window.addEventListener('resize',measure);measure();return()=>{observer.disconnect();window.removeEventListener('resize',measure);};},[side]);
  return <Box ref={ref} xcss={styles.gutter}/>;
}
