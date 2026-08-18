import '@testing-library/jest-dom/vitest';

import { cleanup, configure } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

// `findBy*` and `waitFor` poll for one second by default. A screen that waits
// on two chained requests can exceed that on a loaded machine, which showed up
// as failures that moved between runs rather than a consistent break. This
// raises only how long they are willing to wait - what they assert is
// unchanged, and a passing test still resolves in milliseconds.
configure({ asyncUtilTimeout: 5_000 });

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
