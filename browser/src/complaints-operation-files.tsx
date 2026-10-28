import React, {useEffect, useRef, useState} from 'react';
import Button from '@atlaskit/button/default/button';
import {cssMap} from '@atlaskit/css';
import {token} from '@atlaskit/tokens';
import {Box} from '@atlaskit/primitives/compiled/box';
import {Grid} from '@atlaskit/primitives/compiled/grid';
import {Inline} from '@atlaskit/primitives/compiled/inline';
import {Stack} from '@atlaskit/primitives/compiled/stack';
import {Text} from '@atlaskit/primitives/compiled/text';
import CameraIcon from '@atlaskit/icon/core/camera';
import UploadIcon from '@atlaskit/icon/core/upload';
import AttachmentIcon from '@atlaskit/icon/core/attachment';
import {ActionButton,Section} from './complaints-ui';
import {notify} from './browser-interactions';
export const LockedForm = React.createContext(false);
const styles=cssMap({
  attachmentActions:{display:'flex',flexWrap:'wrap',gap:token('space.100')},
  attachmentRow:{display:'grid',gridTemplateColumns:'minmax(0,1fr) auto',alignItems:'center',gap:token('space.100')},
  filename:{minWidth:0,overflowWrap:'anywhere'},
  camera:{'@media (min-width: 64rem)':{display:'none'}},
});
export function Files({ files, setFiles, saveLabel = 'complaint' }: {
    files: File[];
    setFiles: (value: File[]) => void;
    saveLabel?: string;
}) {
    const locked = React.useContext(LockedForm);
    const picker = useRef<HTMLInputElement>(null), camera = useRef<HTMLInputElement>(null);
    const [error, setError] = useState('');
    useEffect(()=>{if(error)notify(error,'error');},[error]);
    const add = (items: FileList | null) => {
        const next = [...files, ...Array.from(items || [])];
        if (next.length > 10 || next.some(file => file.size > 10 * 1024 * 1024) || next.reduce((size, file) => size + file.size, 0) > 30 * 1024 * 1024)
            setError('Choose up to 10 files, 10 MB each and 30 MB in total.');
        else {
            setFiles(next);
            setError('');

        }
    };
    return <Section title="Attachments"><Stack space="space.150"><Text size="small" color="color.text.subtle">Images or PDF · up to 10 files · 10 MB each, 30 MB total</Text>
    <Box as="input" type="file" hidden ref={picker} multiple accept=".jpg,.jpeg,.png,.webp,.pdf" aria-label="Choose evidence files" onChange={event => { add(event.currentTarget.files); event.currentTarget.value = ''; }}/>
    <Box as="input" type="file" hidden ref={camera} accept="image/*" capture="environment" aria-label="Capture a photo" onChange={event => { add(event.currentTarget.files); event.currentTarget.value = ''; }}/>
    <Grid xcss={styles.attachmentActions} gap="space.100"><Box xcss={styles.camera}><Button shouldFitContainer iconBefore={CameraIcon} isDisabled={locked} onClick={() => camera.current?.click()}>Take photo</Button></Box><Button shouldFitContainer iconBefore={UploadIcon} isDisabled={locked} onClick={() => picker.current?.click()}>Attach files</Button></Grid>
    {files.length>0&&<Box role="status"><Text size="small">{files.length} {files.length===1?'file selected':'files selected'}. Uploaded when you save the {saveLabel}.</Text></Box>}
    {files.map((file, index) => <Box key={`${file.name}-${index}`} xcss={styles.attachmentRow}><Box xcss={styles.filename}><Inline space="space.050" alignBlock="center"><AttachmentIcon label=""/><Text size="small">{file.name}</Text></Inline></Box><ActionButton tone="destructive" isDisabled={locked} onClick={() => setFiles(files.filter((_, item) => item !== index))} aria-label={`Remove ${file.name}`}>Remove</ActionButton></Box>)}
    {error && <Box role="alert"><Text color="color.text.danger">{error}</Text></Box>}
  </Stack></Section>;
}
