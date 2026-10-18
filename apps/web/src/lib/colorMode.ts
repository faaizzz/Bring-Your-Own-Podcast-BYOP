import { useCallback, useEffect, useState } from 'react';

export type ColorMode = 'light' | 'dark';

export const COLOR_MODE_KEY = 'byop-color-mode';

function isColorMode(value: unknown): value is ColorMode {
  return value === 'light' || value === 'dark';
}

/** Stored choice first, then the OS preference, then light. Storage may be unavailable. */
export function getInitialColorMode(): ColorMode {
  try {
    const stored = window.localStorage.getItem(COLOR_MODE_KEY);
    if (isColorMode(stored)) return stored;
  } catch {
    // Private mode or blocked storage: fall through to the OS preference.
  }
  const prefersDark =
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches;
  return prefersDark ? 'dark' : 'light';
}

export function applyColorMode(mode: ColorMode): void {
  document.documentElement.setAttribute('data-bs-theme', mode);
}

export function useColorMode(): { mode: ColorMode; toggle: () => void } {
  const [mode, setMode] = useState<ColorMode>(getInitialColorMode);

  useEffect(() => {
    applyColorMode(mode);
    try {
      window.localStorage.setItem(COLOR_MODE_KEY, mode);
    } catch {
      // Not persisted; the toggle still works for this session.
    }
  }, [mode]);

  const toggle = useCallback(() => setMode((m) => (m === 'dark' ? 'light' : 'dark')), []);
  return { mode, toggle };
}
