import { useSyncExternalStore } from 'react';

function subscribe(onChange: () => void): () => void {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-bs-theme'],
  });
  return () => {
    observer.disconnect();
  };
}

function snapshot(): 'light' | 'dark' {
  return document.documentElement.getAttribute('data-bs-theme') === 'dark' ? 'dark' : 'light';
}

/** The colour theme the page is showing now (follows the header's light/dark toggle). */
export function useTheme(): 'light' | 'dark' {
  return useSyncExternalStore(subscribe, snapshot, () => 'light');
}
