import React, {useEffect, useRef} from 'react';
import layouts, {type LayoutPreference} from '../../core/static/miniapp/table_layouts';
import '../../core/static/miniapp/table_layouts.css';
import {operation} from './complaints-operations-transport';

export function TableLayoutSettings({group}:{group:string}) {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (root.current) layouts.mount(root.current, {
      load: () => operation<LayoutPreference>(group, 'preferences/', new AbortController().signal),
      save: payload => operation<LayoutPreference>(group, 'preferences/', new AbortController().signal, payload),
    });
  }, [group]);
  return <div ref={root} aria-label="Personal table layouts"/>;
}
