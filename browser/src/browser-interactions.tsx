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
import { cssMap } from '@atlaskit/css';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import { token } from '@atlaskit/tokens';
import { TopNavEnd } from '@atlaskit/navigation-system/layout/top-nav';

const themeKey = 'jbl.browser.colorMode';
export function initialColorMode(): 'auto' | 'light' | 'dark' {
  try { const value = localStorage.getItem(themeKey); return value === 'light' || value === 'dark' ? value : 'auto'; } catch { return 'auto'; }
}
const styles = cssMap({
  theme: { display: 'flex', justifyContent: 'flex-end', width: '100%' },
  actions: { gridColumn: 3, display: 'flex', alignItems: 'center', gap: token('space.050') },
  toast: { position: 'fixed', bottom: token('space.200'), left: token('space.200'), margin: 0, width: '90vw', maxWidth: '28rem', boxSizing: 'border-box', padding: token('space.200'), font: token('font.body'), color: token('color.text'), backgroundColor: token('elevation.surface.overlay'), borderColor: token('color.border'), borderStyle: 'solid', borderWidth: token('border.width'), borderRadius: token('radius.medium'), boxShadow: token('elevation.shadow.overlay') },
});
type Notice = { id: number; message: string; tone: 'success' | 'error' | 'warning' | 'information' };
const noticeEvent = 'jbl-browser-notice';
const dismissEvent = 'jbl-browser-dismiss-notice';
let sequence = 0;
export function notify(message: string, tone: Notice['tone'] = 'success') {
  const id=++sequence;window.dispatchEvent(new CustomEvent<Notice>(noticeEvent, { detail: { id, message, tone } }));return id;
}
export function dismissNotice(id:number) {window.dispatchEvent(new CustomEvent<number>(dismissEvent,{detail:id}));}
/** Manual popover is in the top layer, including above an open task dialog. */
export function ToastHost() {
  const [queue, setQueue] = useState<Notice[]>([]), root = useRef<HTMLDivElement>(null);
  const [target,setTarget]=useState<HTMLElement>(document.body);
  const current = queue[0];
  const dismiss = () => setQueue(items => items.slice(1));
  useEffect(() => { const receive = (event: Event) => { const notice = (event as CustomEvent<Notice>).detail; setQueue([notice]); };const clear=(event:Event)=>{const id=(event as CustomEvent<number>).detail;setQueue(items=>items.filter(item=>item.id!==id));};window.addEventListener(noticeEvent, receive);window.addEventListener(dismissEvent,clear);return()=>{window.removeEventListener(noticeEvent,receive);window.removeEventListener(dismissEvent,clear);}; }, []);
  useEffect(()=>{
    const move=()=>{const active=document.activeElement?.closest('dialog[open]');const dialogs=document.querySelectorAll<HTMLDialogElement>('dialog[open]');setTarget(active instanceof HTMLElement?active:dialogs[dialogs.length-1]||document.body);};
    const observer=new MutationObserver(move);observer.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['open']});move();return()=>observer.disconnect();
  },[]);
  useEffect(() => {
    if (!current) return;
    const footer=target.tagName==='DIALOG'?target.querySelector<HTMLElement>('[aria-label="Dialog actions"]'):null;
    const place=()=>{const element=root.current;if(element)element.style.bottom=`${footer&&footer.getBoundingClientRect().height?Math.max(16,innerHeight-footer.getBoundingClientRect().top+8):16}px`;};
    const raise=()=>{const element=root.current;if(!element?.isConnected)return;element.setAttribute('popover','manual');element.style.top='auto';if(element.matches(':popover-open'))element.hidePopover();element.showPopover();};
    place();raise();
    const resize=new ResizeObserver(place);if(footer)resize.observe(footer);window.addEventListener('resize',place);
    const timer = current.tone === 'error' || current.tone === 'warning' ? undefined : setTimeout(dismiss, 6000);
    return () => {clearTimeout(timer);resize.disconnect();window.removeEventListener('resize',place);};
  }, [current,target]);
  const StatusIcon=current?.tone==='error'?ErrorIcon:current?.tone==='warning'?WarningIcon:current?.tone==='success'?CheckIcon:InfoIcon;
  return current ? createPortal(<Box as="div" ref={root} xcss={styles.toast} role={current.tone === 'error' ? 'alert' : 'status'} aria-live={current.tone === 'error' ? 'assertive' : 'polite'}><Inline spread="space-between" alignBlock="start" space="space.150"><StatusIcon label=""/><Stack space="space.050"><Text weight="semibold">{{ success: 'Success', error: 'Error', warning: 'Attention', information: 'Information' }[current.tone]}</Text><Text>{current.message}</Text></Stack><IconButton label="Dismiss notification" appearance="subtle" icon={CrossIcon} onClick={dismiss}/></Inline></Box>, target) : null;
}
export function ThemeControl() {
  const color=useColorMode(),setColor=useSetColorMode();
  const next=color==='dark'?'light':'dark';
  return <Box xcss={styles.theme}><IconButton label={`Switch to ${next} mode`} title={`Switch to ${next} mode`} appearance="subtle" icon={ThemeIcon} onClick={()=>{setColor(next);try{localStorage.setItem(themeKey,next);}catch{/* Theme still works without storage. */}}}/></Box>;
}
export function BrowserActions({ children }: { children?: React.ReactNode }) {
  return <Box xcss={styles.actions}>{children && <TopNavEnd>{children}</TopNavEnd>}<ThemeControl/></Box>;
}
/** Geometry only: consume the actual remaining viewport, not an assumed header height. */
export function useViewportPane(enabled = true) {
  const [element, setElement] = useState<HTMLElement | null>(null);
  useEffect(() => {
    if (!element || !enabled) return;
    const resize = () => { if(!element.getClientRects().length)return;const top = element.getBoundingClientRect().top; const height = Math.max(200, (window.visualViewport?.height || innerHeight) - top - 16); const next = `${height}px`; if (element.style.height !== next) element.style.height = next; };
    const observer = new ResizeObserver(resize); if (element.parentElement) observer.observe(element.parentElement);
    window.addEventListener('resize', resize); window.visualViewport?.addEventListener('resize', resize); resize();
    return () => { observer.disconnect(); window.removeEventListener('resize', resize); window.visualViewport?.removeEventListener('resize', resize); element.style.height = ''; };
  }, [element, enabled]);
  return setElement;
}
