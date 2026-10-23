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
import Select, { type SelectProps } from '@atlaskit/select';
import { cssMap, cx } from '@atlaskit/css';
import Lozenge from '@atlaskit/lozenge';
import Heading from '@atlaskit/heading';
import { Box } from '@atlaskit/primitives/compiled/box';
import { Inline } from '@atlaskit/primitives/compiled/inline';
import { Stack } from '@atlaskit/primitives/compiled/stack';
import { Text } from '@atlaskit/primitives/compiled/text';
import { token } from '@atlaskit/tokens';

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
  return Number.isNaN(parsed.valueOf()) ? value : new Intl.DateTimeFormat('en-GB', { ...(month ? {} : { day: 'numeric' }), month: 'short', year: 'numeric', timeZone: 'Africa/Nairobi' }).format(parsed);
}
const styles = cssMap({
  dialog: { font: token('font.body'), width: '94vw', maxWidth: '60rem', maxHeight: '94vh', boxSizing: 'border-box', padding: 0, borderWidth: token('border.width'), borderStyle: 'solid', borderColor: token('color.border'), borderRadius: token('radius.large'), backgroundColor: token('elevation.surface.overlay'), color: token('color.text'), boxShadow: token('elevation.shadow.overlay'), overflow: 'visible' },
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
});
type DialogSlots = { root: HTMLDialogElement | null; status: HTMLDivElement | null; footer: HTMLDivElement | null };
const DialogContext = createContext<DialogSlots>({root:null,status:null,footer:null});
export function DialogStatus({children}:{children:React.ReactNode}) { const {status}=useContext(DialogContext);return status?createPortal(children,status):null; }
export function DialogFooter({children}:{children:React.ReactNode}) {
  const {footer}=useContext(DialogContext),root=useRef<HTMLDivElement>(null);
  useLayoutEffect(()=>{const node=root.current;if(!node)return;const measure=()=>{node.style.gridTemplateColumns=node.clientWidth<18*parseFloat(getComputedStyle(document.documentElement).fontSize)?'minmax(0, 1fr)':'repeat(2, minmax(0, 1fr))';};const resize=new ResizeObserver(measure),text=new MutationObserver(measure);resize.observe(node);text.observe(document.documentElement,{attributes:true,attributeFilter:['style']});measure();return()=>{resize.disconnect();text.disconnect();};},[footer]);
  return footer?createPortal(<Box ref={root} xcss={styles.footerActions}>{children}</Box>,footer):null;
}
export function Section({title,children}:{title:string;children:React.ReactNode}) { return <Box xcss={styles.section}><Stack space="space.150"><Heading as="h3" size="small">{title}</Heading>{children}</Stack></Box>; }
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
export function TaskDialog({ title, close, children, compact = false, wide = false, size, hasStatus=false }: { title: string; close: () => void; children: React.ReactNode; compact?: boolean; wide?: boolean; size?:'medium';hasStatus?:boolean }) {
  const ref = useRef<HTMLDialogElement|null>(null), heading = useId();
  const [root,setRoot]=useState<HTMLDialogElement|null>(null),[status,setStatus]=useState<HTMLDivElement|null>(null),[footer,setFooter]=useState<HTMLDivElement|null>(null);
  const bind=useCallback((node:HTMLDialogElement|null)=>{ref.current=node;setRoot(node);},[]);
  const closeRef = useRef(close); closeRef.current = close;
  useEffect(() => { const dialog = ref.current!; const opener = document.activeElement as HTMLElement | null; dialog.showModal(); const cancel = (event: Event) => { event.preventDefault(); closeRef.current(); }; dialog.addEventListener('cancel', cancel); return () => { dialog.removeEventListener('cancel', cancel); dialog.close(); opener?.focus(); }; }, []);
  return <Box as="dialog" ref={bind} aria-labelledby={heading} xcss={cx(styles.dialog,compact&&styles.compact,size==='medium'&&styles.medium,wide&&styles.wide)}><DialogContext.Provider value={{root,status,footer}}><Box xcss={styles.frame}><Box xcss={styles.header} aria-label="Dialog header"><Inline spread="space-between" alignBlock="start" space="space.150"><Stack space="space.050"><Heading id={heading} as="h2" size="medium">{title}</Heading>{hasStatus&&<Box ref={setStatus} xcss={styles.status} role="status" aria-live="polite" aria-atomic="true" aria-label="Draft save status"/>}</Stack><IconButton label="Close" appearance="subtle" icon={CrossIcon} onClick={close}/></Inline></Box><Box xcss={styles.body} aria-label="Dialog content"><Stack space="space.200">{children}</Stack></Box><Box ref={setFooter} xcss={styles.footer} aria-label="Dialog actions"/></Box></DialogContext.Provider></Box>;
}
