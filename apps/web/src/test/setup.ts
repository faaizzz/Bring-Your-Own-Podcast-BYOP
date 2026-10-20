import '@testing-library/jest-dom/vitest';
import { cleanup, configure } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

// CI runners are slower than laptops; waiting longer costs nothing when the UI is quick.
configure({ asyncUtilTimeout: 5000 });

// jsdom has no object URLs; previews of chosen files need them.
URL.createObjectURL = vi.fn(() => 'blob:mock');
URL.revokeObjectURL = vi.fn();

// jsdom does not lay anything out, so it cannot scroll.
Element.prototype.scrollIntoView = vi.fn();

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  document.documentElement.removeAttribute('data-bs-theme');
});
