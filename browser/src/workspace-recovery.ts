import { useRef, useState, type SetStateAction } from 'react';

export type Submission = { path: string; values: Record<string, unknown>; files: File[]; key: string };
export type RecoverySlot = {
  read: () => Record<string, unknown>;
  patch: (values: Record<string, unknown>) => void;
};

/** One unfinished task, in this tab only. Never a credential or authorization cache. */
export class WorkspaceRecovery {
  private owner = '';
  private generation = 0;
  private task = '';
  private values: Record<string, unknown> = {};
  bind(owner: string) {
    if (!/^[a-f0-9]{64}$/.test(owner)) throw new Error('Recovery owner is unavailable.');
    if (owner !== this.owner) { this.clear(); this.owner = owner; }
  }
  clear() { this.values = {}; this.task = ''; this.generation++; }
  bound(owner: string) { return Boolean(owner && owner === this.owner); }
  slot(task: string): RecoverySlot {
    if (this.task !== task) { this.clear(); this.task = task; }
    const owner = this.owner, generation = this.generation;
    const current = () => Boolean(owner && owner === this.owner && generation === this.generation);
    return {
      read: () => current() ? { ...this.values } : {},
      patch: values => { if (current()) this.values = { ...this.values, ...values }; },
    };
  }
}

export function useRetainedValue<T>(slot: RecoverySlot, key: string, initial: T): [T, (next: SetStateAction<T>) => void] {
  const [value, setValue] = useState<T>(() => slot.read()[key] === undefined ? initial : slot.read()[key] as T);
  const latest = useRef(value); latest.current = value;
  const change = (next: SetStateAction<T>) => {
    const resolved = typeof next === 'function' ? (next as (previous: T) => T)(latest.current) : next;
    latest.current = resolved; slot.patch({ [key]: resolved }); setValue(resolved);
  };
  return [value, change];
}
