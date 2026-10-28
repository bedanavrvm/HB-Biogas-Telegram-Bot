import React,{useEffect,useId,useLayoutEffect,useRef,useState} from 'react';
import CopyIcon from '@atlaskit/icon/core/copy';
import {notify} from './browser-interactions';

export function CopyButton({label,value,message='Copied',icon}:{label:string;value:()=>string;message?:string;icon?:React.ReactNode}){
  const [copied,setCopied]=useState(0),button=useRef<HTMLButtonElement>(null),tooltip=useRef<HTMLSpanElement>(null),id=useId();
  useEffect(()=>{if(!copied)return;const timer=setTimeout(()=>setCopied(0),2000),close=()=>setCopied(0),key=(event:KeyboardEvent)=>{if(event.key==='Escape')close();};window.addEventListener('scroll',close,true);window.addEventListener('resize',close);window.addEventListener('keydown',key);return()=>{clearTimeout(timer);window.removeEventListener('scroll',close,true);window.removeEventListener('resize',close);window.removeEventListener('keydown',key);};},[copied]);
  useLayoutEffect(()=>{
    const node=tooltip.current,anchor=button.current;if(!copied||!node||!anchor)return;
    node.setAttribute('popover','manual');node.showPopover();
    const bounds=anchor.getBoundingClientRect();node.style.left=`${Math.max(8,Math.min(innerWidth-node.offsetWidth-8,bounds.left+bounds.width/2-node.offsetWidth/2))}px`;
    node.style.top=`${bounds.bottom+node.offsetHeight+12<innerHeight?bounds.bottom+8:Math.max(8,bounds.top-node.offsetHeight-8)}px`;
    return()=>{if(node.matches(':popover-open'))node.hidePopover();};
  },[copied]);
  return <span className="stitch-copy-control"><button type="button" className="stitch-copy-button" ref={button} aria-label={label} aria-describedby={copied?id:undefined} onClick={()=>{void navigator.clipboard.writeText(value()).then(()=>setCopied(Date.now())).catch(()=>notify('Copy is unavailable. Select the value and copy it.','warning'));}}>{icon||<CopyIcon label="" size="small"/>}</button>{copied>0&&<span id={id} role="tooltip" ref={tooltip} className="stitch-copy-tooltip">{message}</span>}</span>;
}
