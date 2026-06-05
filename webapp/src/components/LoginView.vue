<script setup lang="ts">
import { ref } from 'vue';
import { useAuthStore } from '@/stores/auth';

const auth = useAuthStore();
const email = ref('');
const password = ref('');

async function onSubmit() {
  try {
    await auth.login(email.value, password.value);
  } catch {
    // auth.error is set by the store; the template renders it.
  }
}
</script>

<template>
  <div class="login">
    <form class="card" @submit.prevent="onSubmit">
      <h1 class="title mono">Intercom Triage</h1>
      <p class="subtitle">Sign in with your OnlySales account.</p>

      <label class="field">
        <span>Email</span>
        <input v-model="email" type="email" autocomplete="username" required />
      </label>

      <label class="field">
        <span>Password</span>
        <input v-model="password" type="password" autocomplete="current-password" required />
      </label>

      <p v-if="auth.error" class="error mono">{{ auth.error }}</p>

      <button type="submit" :disabled="auth.loading">
        {{ auth.loading ? 'Signing in…' : 'Sign in' }}
      </button>
    </form>
  </div>
</template>

<style scoped>
.login {
  display: grid;
  place-items: center;
  min-height: 100vh;
  background: var(--bg);
}
.card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 320px;
  padding: 24px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
}
.title {
  margin: 0;
  font-size: 18px;
  color: var(--ink);
}
.subtitle {
  margin: 0;
  color: var(--ink-2);
  font-size: 13px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  color: var(--ink-2);
}
.field input {
  padding: 8px 10px;
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: var(--radius-chip);
  color: var(--ink);
  font-family: var(--font-sans);
}
.error {
  margin: 0;
  color: var(--accent);
  font-size: 13px;
}
button {
  padding: 10px;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: var(--radius-chip);
  cursor: pointer;
  font-family: var(--font-sans);
  font-size: 13px;
}
button:disabled {
  opacity: 0.6;
  cursor: default;
}
</style>
