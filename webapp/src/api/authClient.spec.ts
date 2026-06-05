// Auth-aware request layer: Bearer injection + 401→refresh→retry.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, setAccessToken, onAuthLost } from './client';

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock);
  fetchMock.mockReset();
  setAccessToken(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(status: number, body: unknown): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

describe('auth request layer', () => {
  it('attaches the Bearer header when a token is set', async () => {
    setAccessToken('tok-1');
    fetchMock.mockResolvedValueOnce(jsonResponse(200, []));
    await api.listCategories();
    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>)['authorization']).toBe('Bearer tok-1');
    expect(init.credentials).toBe('include');
  });

  it('on 401 refreshes once then retries with the new token', async () => {
    setAccessToken('stale');
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { detail: 'expired' })) // first call
      .mockResolvedValueOnce(
        jsonResponse(200, {
          access_token: 'fresh',
          user: { id: 1, onlysales_id: 'o', email: 'e', name: null, scope: null },
        }),
      ) // /auth/refresh
      .mockResolvedValueOnce(jsonResponse(200, [])); // retry
    const result = await api.listCategories();
    expect(result).toEqual([]);
    const retryInit = fetchMock.mock.calls[2][1];
    expect((retryInit.headers as Record<string, string>)['authorization']).toBe('Bearer fresh');
  });

  it('calls onAuthLost when refresh itself fails', async () => {
    setAccessToken('stale');
    const lost = vi.fn();
    onAuthLost(lost);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { detail: 'expired' }))
      .mockResolvedValueOnce(jsonResponse(401, { detail: 'no session' })); // refresh fails
    await expect(api.listCategories()).rejects.toThrow();
    expect(lost).toHaveBeenCalledOnce();
  });
});
