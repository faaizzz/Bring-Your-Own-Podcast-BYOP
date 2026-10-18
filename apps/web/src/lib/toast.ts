import { createContext, useContext } from 'react';

export type ToastVariant = 'success' | 'danger' | 'info';

export type Notify = (message: string, variant?: ToastVariant) => void;

export const ToastContext = createContext<Notify | null>(null);

/** Show a transient message. Must be used below `ToastProvider` (the admin layout has one). */
export function useToast(): Notify {
  const notify = useContext(ToastContext);
  if (!notify) throw new Error('useToast must be used inside ToastProvider');
  return notify;
}
