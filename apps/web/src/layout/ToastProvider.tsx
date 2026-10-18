import { useCallback, useRef, useState } from 'react';
import { Toast, ToastContainer } from 'react-bootstrap';

import { ToastContext, type Notify, type ToastVariant } from '../lib/toast';

type Item = { id: number; message: string; variant: ToastVariant };

export function ToastProvider({ children }: { children: React.ReactNode }): React.JSX.Element {
  const [items, setItems] = useState<Item[]>([]);
  const nextId = useRef(0);

  const notify = useCallback<Notify>((message, variant = 'info') => {
    nextId.current += 1;
    const id = nextId.current;
    setItems((current) => [...current, { id, message, variant }]);
  }, []);

  const dismiss = (id: number) => {
    setItems((current) => current.filter((item) => item.id !== id));
  };

  return (
    <ToastContext.Provider value={notify}>
      {children}
      <ToastContainer position="top-end" className="p-3 position-fixed" style={{ zIndex: 2000 }}>
        {items.map((item) => (
          <Toast
            key={item.id}
            bg={item.variant}
            autohide
            delay={6000}
            onClose={() => {
              dismiss(item.id);
            }}
          >
            <Toast.Body className={item.variant === 'info' ? '' : 'text-white'}>
              {item.message}
            </Toast.Body>
          </Toast>
        ))}
      </ToastContainer>
    </ToastContext.Provider>
  );
}
