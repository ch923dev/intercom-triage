// Auth store — in-memory access token + current user. The refresh token lives
// only in an httpOnly cookie the browser manages; nothing sensitive is stored
// in localStorage. On load, bootstrap() silently refreshes any live session.

import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { api, setAccessToken, onAuthLost } from '@/api/client';
import type { User } from '@/types/auth';

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  const isAuthenticated = computed(() => user.value !== null);

  async function login(email: string, password: string): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      const resp = await api.login({ email, password });
      setAccessToken(resp.access_token);
      user.value = resp.user;
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Login failed';
      throw e;
    } finally {
      loading.value = false;
    }
  }

  /** Silent session restore on app load. True if a session was refreshed. */
  async function bootstrap(): Promise<boolean> {
    try {
      const resp = await api.refreshSession();
      setAccessToken(resp.access_token);
      user.value = resp.user;
      return true;
    } catch {
      setAccessToken(null);
      user.value = null;
      return false;
    }
  }

  async function logout(): Promise<void> {
    try {
      await api.logout();
    } finally {
      setAccessToken(null);
      user.value = null;
    }
  }

  /** Called by the api layer when a refresh fails mid-session. */
  function handleAuthLost(): void {
    setAccessToken(null);
    user.value = null;
  }
  onAuthLost(handleAuthLost);

  return { user, loading, error, isAuthenticated, login, bootstrap, logout };
});
