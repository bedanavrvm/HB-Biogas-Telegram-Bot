import React, {useEffect, useRef, useState} from 'react';
import Button from '@atlaskit/button/default/button';
import {IconButton} from '@atlaskit/button/new';
import AddIcon from '@atlaskit/icon/core/add';
import MinusIcon from '@atlaskit/icon/core/minus';
import RefreshIcon from '@atlaskit/icon/core/refresh';
import {Box} from '@atlaskit/primitives/compiled/box';
import {Text} from '@atlaskit/primitives/compiled/text';
import {Anchor} from '@atlaskit/primitives/compiled/anchor';
import type {Detail,MapConfig} from './complaints-operations-transport';

type MapInstance = {remove:()=>void;invalidateSize:()=>void;setView:(point:number[],zoom:number)=>MapInstance;zoomIn:()=>void;zoomOut:()=>void};
type Leaflet = {map:(node:HTMLElement,options:Record<string,unknown>)=>MapInstance;
  tileLayer:(url:string,options:Record<string,unknown>)=>{addTo:(map:MapInstance)=>void;on:(name:string,callback:()=>void)=>void;redraw:()=>void};
  divIcon:(options:Record<string,unknown>)=>unknown;marker:(point:number[],options:Record<string,unknown>)=>{addTo:(map:MapInstance)=>void}};
declare global {interface Window {L?:Leaflet}}
let loading:Promise<Leaflet>|undefined;
function leaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (!loading) loading=new Promise<Leaflet>((resolve,reject)=>{
    const entry=Array.from(document.scripts).find(script=>script.src && new URL(script.src).origin===location.origin);
    if(!entry){reject(new Error('Map assets unavailable'));return;}
    const css=document.createElement('link');css.rel='stylesheet';css.href=new URL('vendor-leaflet-1.9.4.css',entry.src).href;document.head.append(css);
    const script=document.createElement('script');script.src=new URL('vendor-leaflet-1.9.4.js',entry.src).href;
    script.onload=()=>window.L?resolve(window.L):reject(new Error('Map unavailable'));
    script.onerror=()=>{script.remove();css.remove();loading=undefined;reject(new Error('Map unavailable'));};document.head.append(script);
  });
  return loading;
}
export function DetailMap({item,config}:{item:Detail;config?:MapConfig}) {
  const node=useRef<HTMLDivElement>(null),map=useRef<MapInstance>(),redraw=useRef<()=>void>();
  const [failure,setFailure]=useState(''),[retry,setRetry]=useState(0);
  const lat=Number(item.location.latitude),lng=Number(item.location.longitude);
  const coordinates=Boolean(item.location.latitude&&item.location.longitude&&Number.isFinite(lat)&&Number.isFinite(lng)&&Math.abs(lat)<=90&&Math.abs(lng)<=180);
  let link='';try{const url=new URL(item.location.url);if(['https:','http:'].includes(url.protocol))link=url.href;}catch{/* Historical unstructured location. */}
  useEffect(()=>{
    if(!coordinates||!config?.enabled||!node.current)return;
    let cancelled=false,observer:ResizeObserver|undefined;
    setFailure('');
    void leaflet().then(L=>{
      if(cancelled||!node.current)return;
      // A case change or retry can remove the container before a CSS zoom transition ends.
      const instance=L.map(node.current,{scrollWheelZoom:false,zoomControl:false,zoomAnimation:false}).setView([lat,lng],18);map.current=instance;
      const tiles=L.tileLayer(config.tile_url,{maxZoom:20,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'});
      let tileFailed=false;
      tiles.on('loading',()=>{tileFailed=false;});
      tiles.on('tileerror',()=>{tileFailed=true;if(!cancelled)setFailure('Map tiles could not be loaded. You can still open the saved map pin.');});
      tiles.on('load',()=>{if(!cancelled&&!tileFailed)setFailure('');});
      tiles.addTo(instance);redraw.current=()=>{instance.invalidateSize();tiles.redraw();};
      L.marker([lat,lng],{keyboard:true,title:'Recorded complaint location',icon:L.divIcon({className:'complaint-map-pin',html:'<svg width="32" height="40" viewBox="0 0 32 40" xmlns="http://www.w3.org/2000/svg"><path d="M16 39S1 23 1 16a15 15 0 0 1 30 0c0 7-15 23-15 23Z" fill="#216e4e" stroke="white" stroke-width="2"/><circle cx="16" cy="16" r="5" fill="white"/></svg>',iconSize:[32,40],iconAnchor:[16,40]})}).addTo(instance);
      observer=new ResizeObserver(()=>instance.invalidateSize());observer.observe(node.current);requestAnimationFrame(()=>instance.invalidateSize());
    }).catch(()=>{if(!cancelled)setFailure('The map could not be loaded. Open the saved map pin or retry.');});
    return()=>{cancelled=true;observer?.disconnect();map.current?.remove();map.current=undefined;};
  },[item.key,lat,lng,coordinates,config?.enabled,config?.tile_url,retry]);
  return <div className="stitch-map">
    {coordinates&&config?.enabled&&<div className="stitch-map-view"><div className="stitch-map-toolbar"><IconButton icon={AddIcon} appearance="subtle" label="Zoom in map" onClick={()=>map.current?.zoomIn()}/><IconButton icon={MinusIcon} appearance="subtle" label="Zoom out map" onClick={()=>map.current?.zoomOut()}/><IconButton icon={RefreshIcon} appearance="subtle" label="Refresh map location" onClick={()=>{if(map.current){map.current.setView([lat,lng],18);redraw.current?.();}else setRetry(value=>value+1);}}/></div><div ref={node} className="stitch-map-canvas" aria-label="Interactive recorded complaint location"/>{item.village&&<div className="stitch-map-landmark">{item.village}</div>}</div>}
    {failure&&<Box role="status"><Text>{failure}</Text><Button appearance="subtle" onClick={()=>setRetry(value=>value+1)}>Retry map</Button></Box>}
    {(!coordinates||!config?.enabled)&&<Text size="small" color="color.text.subtle">{coordinates?'Interactive map is unavailable for this workspace.':'No recorded map coordinates.'}</Text>}
    <div className="stitch-map-facts">{[['County',item.county],['Constituency',item.constituency]].map(([label,value])=><div key={label}><span className="stitch-label">{label}</span><span>{value||'Not recorded'}</span></div>)}</div>{link&&<Anchor href={link} target="_blank" rel="noopener noreferrer">Open map pin</Anchor>}{(!coordinates||!config?.enabled)&&item.village&&<Text size="small">{item.village}</Text>}
  </div>;
}
