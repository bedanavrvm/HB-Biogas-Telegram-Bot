import React,{useEffect,useRef,useState} from 'react';
import Button from '@atlaskit/button/default/button';
import CameraIcon from '@atlaskit/icon/core/camera';
import AttachmentIcon from '@atlaskit/icon/core/attachment';
import {fileTransfer,watchFileTransfers,type FileTransfer} from './complaints-operations-transport';

export const LockedForm=React.createContext(false);

function Transfer({file}:{file:File}){
  const [value,setValue]=useState<FileTransfer|undefined>(()=>fileTransfer(file));
  useEffect(()=>watchFileTransfers(next=>{if(next.file===file)setValue(next);}),[file]);
  return value?<div className="stitch-file-progress" role="status"><span>{value.percent}% · {value.stage}</span><progress max={100} value={value.percent} aria-label={'Upload progress for '+file.name}/></div>:null;
}

export function Files({files,setFiles,saveLabel='complaint',compact=false}:{files:File[];setFiles:(value:File[])=>void;saveLabel?:string;compact?:boolean}){
  const locked=React.useContext(LockedForm),picker=useRef<HTMLInputElement>(null),camera=useRef<HTMLInputElement>(null);
  const [error,setError]=useState(''),[dragging,setDragging]=useState(false);
  const add=(items:FileList|null)=>{
    if(locked)return;
    const selected=Array.from(items||[]),next=[...files,...selected];
    if(next.length>10||next.some(file=>!file.size||file.size>10*1024*1024)||next.reduce((size,file)=>size+file.size,0)>30*1024*1024){setError('Choose up to 10 nonempty files, 10 MB each and 30 MB in total.');return;}
    if(selected.some(file=>! /\.(jpe?g|png|webp|pdf)$/i.test(file.name))){setError('Choose a JPEG, PNG, WebP image or PDF.');return;}
    setFiles(next);setError('');
  };
  const inputs=<><input type="file" hidden ref={picker} multiple accept=".jpg,.jpeg,.png,.webp,.pdf" aria-label="Choose evidence files" onChange={event=>{add(event.currentTarget.files);event.currentTarget.value='';}}/><input type="file" hidden ref={camera} accept="image/*" capture="environment" aria-label="Capture a photo" onChange={event=>{add(event.currentTarget.files);event.currentTarget.value='';}}/></>;
  const list=files.length>0&&<div className="stitch-selected-files">{files.map((file,index)=><div className="stitch-selected-file" key={`${file.name}-${index}`}><div><span>{file.name}</span><button type="button" aria-label={`Remove ${file.name}`} disabled={locked} onClick={()=>setFiles(files.filter((_,item)=>item!==index))}>Remove</button></div><Transfer file={file}/></div>)}<small>Files are received when you save the {saveLabel}. Publication continues after the save.</small></div>;
  if(compact)return <div className="stitch-files-compact">{inputs}<button type="button" className="stitch-camera" aria-label="Take photo" disabled={locked} onClick={()=>camera.current?.click()}><CameraIcon label="" size="small"/></button><button type="button" aria-label="Attach files" title="Images or PDF; up to 10 files, 10 MB each, 30 MB total" disabled={locked} onClick={()=>picker.current?.click()}><AttachmentIcon label="" size="small"/></button>{list}{error&&<span role="alert">{error}</span>}</div>;
  return <section className="stitch-dropzone" data-dragging={dragging} aria-label="Attachments" onDragOver={event=>{event.preventDefault();if(!locked)setDragging(true);}} onDragLeave={()=>setDragging(false)} onDrop={event=>{event.preventDefault();setDragging(false);add(event.dataTransfer.files);}}><h3>Attachments</h3><p>JPEG, PNG, WebP or PDF · up to 10 files · 10 MB each, 30 MB total</p>{inputs}<div className="stitch-file-buttons"><Button iconBefore={CameraIcon} isDisabled={locked} onClick={()=>camera.current?.click()}>Take photo</Button><Button iconBefore={AttachmentIcon} isDisabled={locked} onClick={()=>picker.current?.click()}>Attach files</Button></div><p>Drop files here or choose Attach files.</p>{list}{error&&<p role="alert">{error}</p>}</section>;
}
