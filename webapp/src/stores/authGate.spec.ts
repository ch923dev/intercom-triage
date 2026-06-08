// Verifies the gate predicate the App template relies on.

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useAuthStore } from './auth';
import { api } from '@/api/client';

vi.mock('@/api/client', () => ({
  api: { refreshSession: vi.fn(), login: vi.fn(), logout: vi.fn() },
  setAccessToken: vi.fn(),
  onAuthLost: vi.fn(),
}));

describe('auth gate predicate', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('is unauthenticated before bootstrap and after a failed bootstrap', async () => {
    vi.mocked(api).refreshSession.mockRejectedValue(new Error('401'));
    const s = useAuthStore();
    expect(s.isAuthenticated).toBe(false);
    await s.bootstrap();
    expect(s.isAuthenticated).toBe(false);
  });
});
