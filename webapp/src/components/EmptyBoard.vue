<!-- Empty-board placeholder. Shown on the board view when zero tickets are
     stored. Ingestion is backend-side (POST /tickets/sync or the poller), so
     the copy points there — not at any client surface. -->
<script setup lang="ts">
import Mono from './Mono.vue';
</script>

<template>
  <div class="empty">
    <Mono :size="11">No tickets yet</Mono>
    <p class="lead">The board fills once the backend ingests conversations from Intercom.</p>
    <ol class="steps">
      <li>Trigger one cycle now: <code>POST /tickets/sync</code> (503 if no token is set).</li>
      <li>
        Or set <code>INTERCOM_POLL_INTERVAL_SECONDS</code> in <code>backend/.env</code> to run the
        background poller.
      </li>
      <li>
        Still empty? Check <code>/health</code> — <code>intercom_configured</code> flags a missing
        token.
      </li>
    </ol>
  </div>
</template>

<style scoped>
.empty {
  flex: 1;
  align-self: center;
  margin: 60px auto;
  max-width: 520px;
  padding: 24px 28px;
  border: var(--hairline) solid var(--line);
  border-radius: 6px;
  background: var(--panel);
  color: var(--ink-2);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.empty .lead {
  margin: 0;
  font-size: 13px;
  color: var(--ink);
  line-height: 1.5;
}
.empty .steps {
  margin: 4px 0 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.55;
}
.empty .steps li {
  margin-bottom: 4px;
}
code {
  font-family: var(--font-mono);
  font-size: 10.5px;
  background: var(--chip-bg);
  padding: 1px 4px;
  border-radius: 2px;
  color: var(--ink);
}
</style>
