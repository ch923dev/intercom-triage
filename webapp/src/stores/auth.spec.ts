import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useAuthStore } from './auth';
import { api, setAccessToken } from '@/api/client';

vi.mock('@/api/client', () => ({
  api: { login: vi.fn(), refreshSession: vi.fn(), logout: vi.fn() },
  setAccessToken: vi.fn(),
  onAuthLost: vi.fn(),
}));

const mocked = vi.mocked(api);

const USER = { id: 1, onlysales_id: 'o', email: 'op@example.com', name: 'Op', scope: 'admin' };

describe('authStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('login stores the token + user and flips authenticated', async () => {
    mocked.login.mockResolvedValue({ access_token: 'tok', user: USER });
    const s = useAuthStore();
    await s.login('op@example.com', 'pw');
    expect(s.isAuthenticated).toBe(true);
    expect(s.user?.email).toBe('op@example.com');
    expect(vi.mocked(setAccessToken)).toHaveBeenCalledWith('tok');
  });

  it('bootstrap returns true when a session refreshes', async () => {
    mocked.refreshSession.mockResolvedValue({ access_token: 'tok', user: USER });
    const s = useAuthStore();
    const ok = await s.bootstrap();
    expect(ok).toBe(true);
    expect(s.isAuthenticated).toBe(true);
  });

  it('bootstrap returns false when no session exists', async () => {
    mocked.refreshSession.mockRejectedValue(new Error('401'));
    const s = useAuthStore();
    const ok = await s.bootstrap();
    expect(ok).toBe(false);
    expect(s.isAuthenticated).toBe(false);
  });

  it('logout clears state', async () => {
    mocked.login.mockResolvedValue({ access_token: 'tok', user: USER });
    mocked.logout.mockResolvedValue(undefined);
    const s = useAuthStore();
    await s.login('op@example.com', 'pw');
    await s.logout();
    expect(s.isAuthenticated).toBe(false);
    expect(s.user).toBeNull();
  });
});
