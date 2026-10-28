import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { IconButton } from '@atlaskit/button/new';
import ThemeIcon from '@atlaskit/icon/core/theme';
import CrossIcon from '@atlaskit/icon/core/cross';
import CheckIcon from '@atlaskit/icon/core/check-mark';
import ErrorIcon from '@atlaskit/icon/core/status-error';
import WarningIcon from '@atlaskit/icon/core/status-warning';
import InfoIcon from '@atlaskit/icon/core/information-circle';
import { useColorMode, useSetColorMode } from '@atlaskit/app-provider';
import { cssMap, cx } from '@atlaskit/css';
import Button from '@atlaskit/button/default/button';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import { token } from '@atlaskit/tokens';
import { TopNavEnd } from '@atlaskit/navigation-system/layout/top-nav';
import { ConfirmationHost, HeaderGutter } from './complaints-ui';

const themeKey = 'jbl.browser.colorMode';
export function initialColorMode(): 'auto' | 'light' | 'dark' {
  try { const value = localStorage.getItem(themeKey); return value === 'light' || value === 'dark' ? value : 'auto'; } catch { return 'auto'; }
}
const styles = cssMap({
  theme: { display: 'flex', justifyContent: 'flex-end' },
  actions: { gridColumn: 3, justifySelf: 'end', display: 'flex', alignItems: 'center', gap: token('space.050') },

  toast: { position: 'fixed', bottom: token('space.200'), left: token('space.200'), margin: 0, width: '90vw', maxWidth: '28rem', maxHeight: '50vh', overflowY: 'auto', boxSizing: 'border-box', padding: 0, font: token('font.body'), color: token('color.text'), backgroundColor: 'transparent', border: 'none' },
  notice: { padding: token('space.200'), borderWidth: token('border.width'), borderStyle: 'solid', borderRadius: token('radius.medium'), boxShadow: token('elevation.shadow.overlay') },
  success: { backgroundColor: token('color.background.success'), borderColor: token('color.border.success') },
  error: { backgroundColor: token('color.background.danger'), borderColor: token('color.border.danger') },
  warning: { backgroundColor: token('color.background.warning'), borderColor: token('color.border.warning') },
  information: { backgroundColor: token('color.background.information'), borderColor: token('color.border.information') },
});
type Notice = { id: number; message: string; tone: 'success' | 'error' | 'warning' | 'information'; title?: string; dedupeKey?: string; action?: {label:string;run:()=>void|Promise<void>} };
const noticeEvent = 'jbl-browser-notice';
const dismissEvent = 'jbl-browser-dismiss-notice';
let sequence = 0;
const activeNotices=new Map<string,number>();
export function notify(message: string, tone: Notice['tone'] = 'success', options: Pick<Notice,'title'|'dedupeKey'|'action'> = {}) {
  const key=options.dedupeKey,existing=key?activeNotices.get(key):undefined;if(existing)return existing;
  const id=++sequence;if(key)activeNotices.set(key,id);window.dispatchEvent(new CustomEvent<Notice>(noticeEvent, { detail: { id, message, tone, ...options } }));return id;
}
export function dismissNotice(id:number) {for(const [key,value] of activeNotices)if(value===id)activeNotices.delete(key);window.dispatchEvent(new CustomEvent<number>(dismissEvent,{detail:id}));}
/** Manual popover is in the top layer, including above an open task dialog. */
export function ToastHost() {
  const [queue, setQueue] = useState<Notice[]>([]), root = useRef<HTMLDivElement>(null);
  const [target,setTarget]=useState<HTMLElement>(document.body);
  const dismiss = dismissNotice;
  useEffect(() => { const receive = (event: Event) => { const notice = (event as CustomEvent<Notice>).detail; setQueue(items=>notice.dedupeKey&&items.some(item=>item.dedupeKey===notice.dedupeKey)?items:[...items,notice]); };const clear=(event:Event)=>{const id=(event as CustomEvent<number>).detail;setQueue(items=>items.filter(item=>item.id!==id));};window.addEventListener(noticeEvent, receive);window.addEventListener(dismissEvent,clear);return()=>{window.removeEventListener(noticeEvent,receive);window.removeEventListener(dismissEvent,clear);activeNotices.clear();}; }, []);
  useEffect(()=>{
    const move=()=>{const active=document.activeElement?.closest('dialog[open]');const dialogs=document.querySelectorAll<HTMLDialogElement>('dialog[open]');setTarget(active instanceof HTMLElement?active:dialogs[dialogs.length-1]||document.body);};
    const observer=new MutationObserver(move);observer.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['open']});move();return()=>observer.disconnect();
  },[]);
  useEffect(() => {
    if (!queue.length) return;
    const footer=target.tagName==='DIALOG'?target.querySelector<HTMLElement>('[aria-label="Dialog actions"]'):null;
    const place=()=>{const element=root.current;if(element)element.style.bottom=`${footer&&footer.getBoundingClientRect().height?Math.max(16,innerHeight-footer.getBoundingClientRect().top+8):16}px`;};
    const raise=()=>{const element=root.current;if(!element?.isConnected)return;element.setAttribute('popover','manual');element.style.top='auto';if(element.matches(':popover-open'))element.hidePopover();element.showPopover();};
    place();raise();
    const resize=new ResizeObserver(place);if(footer)resize.observe(footer);window.addEventListener('resize',place);
    return () => {resize.disconnect();window.removeEventListener('resize',place);};
  }, [queue.length,target]);
  return <><ConfirmationHost/>{queue.length ? createPortal(<Box as="div" ref={root} xcss={styles.toast} aria-label="Notifications"><Stack space="space.100">{queue.slice(0,3).map(notice=><ToastCard key={notice.id} notice={notice} dismiss={dismiss}/>)}</Stack></Box>, target) : null}</>;
}
function ToastCard({notice,dismiss}:{notice:Notice;dismiss:(id:number)=>void}) {
  const [hovered,setHovered]=useState(false),[focused,setFocused]=useState(false),remaining=useRef(5000),dismissRef=useRef(dismiss);dismissRef.current=dismiss;
  useEffect(()=>{if(hovered||focused||notice.tone==='error'||notice.tone==='warning')return;const started=Date.now(),timer=setTimeout(()=>dismissRef.current(notice.id),remaining.current);return()=>{clearTimeout(timer);remaining.current=Math.max(0,remaining.current-(Date.now()-started));};},[hovered,focused,notice.id,notice.tone]);
  const StatusIcon=notice.tone==='error'?ErrorIcon:notice.tone==='warning'?WarningIcon:notice.tone==='success'?CheckIcon:InfoIcon;
  return <Box xcss={cx(styles.notice,styles[notice.tone])} role={notice.tone==='error'?'alert':'status'} onMouseEnter={()=>setHovered(true)} onMouseLeave={()=>setHovered(false)} onFocus={()=>setFocused(true)} onBlur={(event:React.FocusEvent<HTMLDivElement>)=>{if(!event.currentTarget.contains(event.relatedTarget))setFocused(false);}}><Inline spread="space-between" alignBlock="start" space="space.150"><StatusIcon label=""/><Stack space="space.050"><Text weight="semibold">{notice.title||{success:'Success',error:'Error',warning:'Attention',information:'Information'}[notice.tone]}</Text><Text>{notice.message}</Text>{notice.action&&<Button appearance="subtle" onClick={()=>{void Promise.resolve(notice.action!.run()).catch(()=>notify('The action could not be completed. Try again.','error'));}}>{notice.action.label}</Button>}</Stack><IconButton label="Dismiss notification" appearance="subtle" icon={CrossIcon} onClick={()=>dismiss(notice.id)}/></Inline></Box>;
}
export function ThemeControl() {
  const color=useColorMode(),setColor=useSetColorMode();
  const next=color==='dark'?'light':'dark';
  return <Box xcss={styles.theme}><IconButton label={`Switch to ${next} mode`} isTooltipDisabled={false} appearance="subtle" icon={ThemeIcon} onClick={()=>{setColor(next);try{localStorage.setItem(themeKey,next);}catch{/* Theme still works without storage. */}}}/></Box>;
}
export function BrowserActions({ children, aligned=false }: { children?: React.ReactNode; aligned?:boolean }) {
  return <Box xcss={styles.actions}><ThemeControl/>{children && (aligned?children:<TopNavEnd>{children}</TopNavEnd>)}{aligned&&<HeaderGutter side="end"/>}</Box>;
}
/** Geometry only: consume the actual remaining viewport, not an assumed header height. */
export function useViewportPane(enabled = true) {
  const [element, setElement] = useState<HTMLElement | null>(null);
  useEffect(() => {
    if (!element || !enabled) return;
    const resize = () => { if(!element.getClientRects().length)return;const font=parseFloat(getComputedStyle(document.documentElement).fontSize),viewport=window.visualViewport?.height||innerHeight;const bounded=innerWidth>=64*font&&viewport>=40*font;const top=element.getBoundingClientRect().top;const next=bounded?`${Math.max(200,viewport-top-16)}px`:'';if(element.style.height!==next)element.style.height=next; };
    const observer = new ResizeObserver(resize); if (element.parentElement) observer.observe(element.parentElement);
    const text=new MutationObserver(resize);text.observe(document.documentElement,{attributes:true,attributeFilter:['style']});
    window.addEventListener('resize', resize); window.visualViewport?.addEventListener('resize', resize); resize();
    return () => { observer.disconnect();text.disconnect();window.removeEventListener('resize', resize); window.visualViewport?.removeEventListener('resize', resize); element.style.height = ''; };
  }, [element, enabled]);
  return setElement;
}
