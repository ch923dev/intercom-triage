<!-- Ticket detail flyout. Right-side modal opened by selecting a card or an
     alarm banner's "Open" action. Composes the detail panes from focused
     child components in ./ticket/. -->
<script setup lang="ts">
import { computed, watch } from 'vue';
import Mono from './Mono.vue';
import { useAttachmentsStore } from '@/stores/attachments';
import { useCategoriesStore } from '@/stores/categories';
import { useTicketsStore } from '@/stores/tickets';
import { useViewStore } from '@/stores/view';
import TicketAttachmentBin from './ticket/TicketAttachmentBin.vue';
import TicketCategoryPicker from './ticket/TicketCategoryPicker.vue';
import TicketConversation from './ticket/TicketConversation.vue';
import TicketEntryForm from './ticket/TicketEntryForm.vue';
import TicketEntryTimeline from './ticket/TicketEntryTimeline.vue';
import TicketFollowup from './ticket/TicketFollowup.vue';
import TicketHeader from './ticket/TicketHeader.vue';
import TicketLegacyNote from './ticket/TicketLegacyNote.vue';
import TicketResolution from './ticket/TicketResolution.vue';

const view = useViewStore();
const tickets = useTicketsStore();
const categories = useCategoriesStore();
const attachments = useAttachmentsStore();

const ticket = computed(
  () =>
    tickets.tickets.find((t) => t.id === view.selectedTicketId) ??
    tickets.resolvedTickets.find((t) => t.id === view.selectedTicketId) ??
    null,
);

const effectiveCategoryId = computed(() => {
  const t = ticket.value;
  if (!t) return null;
  return tickets.pendingOverrides[t.id] ?? t.category_id;
});

const category = computed(() => {
  const id = effectiveCategoryId.value;
  return id == null ? null : (categories.categories.find((c) => c.id === id) ?? null);
});

watch(
  () => ticket.value?.id,
  (id) => {
    if (id) void attachments.load(id);
  },
  { immediate: true },
);

function close() {
  view.closeFlyout();
}
</script>

<template>
  <Teleport to="body">
    <div v-if="ticket" class="scrim" @click.self="close">
      <div class="modal">
        <header>
          <Mono :size="11">{{ ticket.id }}</Mono>
          <button class="x" title="Close" @click="close">✕</button>
        </header>

        <div class="panes">
          <TicketConversation :ticket="ticket" />

          <aside class="detail-pane">
            <TicketHeader :ticket="ticket" :category="category" />

            <TicketCategoryPicker
              :ticket-id="ticket.id"
              :effective-category-id="effectiveCategoryId"
            />

            <TicketFollowup :ticket-id="ticket.id" />

            <section class="block">
              <div class="mono label">Next-step notes</div>
              <TicketLegacyNote :ticket-id="ticket.id" />
              <TicketAttachmentBin :ticket-id="ticket.id" />
              <TicketEntryTimeline :ticket-id="ticket.id" />
              <TicketEntryForm :ticket-id="ticket.id" />
            </section>

            <TicketResolution :ticket="ticket" />
          </aside>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.scrim {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.42);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 40;
}
.modal {
  width: min(980px, 95vw);
  height: min(86vh, 820px);
  background: var(--bg);
  border: var(--hairline) solid var(--line);
  border-radius: 14px;
  box-shadow: var(--shadow);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: triagePop 0.16s ease-out;
}
@keyframes triagePop {
  from {
    opacity: 0;
    transform: scale(0.985);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}
.panes {
  display: flex;
  flex: 1;
  min-height: 0;
}
.detail-pane {
  flex: 0 0 320px;
  overflow-y: auto;
  padding: 16px;
  border-left: var(--hairline) solid var(--line);
  background: var(--panel);
  display: flex;
  flex-direction: column;
  gap: 12px;
}
@media (max-width: 760px) {
  .modal {
    width: 96vw;
    height: 92vh;
  }
  .panes {
    flex-direction: column;
  }
  .detail-pane {
    flex: 0 0 auto;
    border-left: 0;
    border-top: var(--hairline) solid var(--line);
  }
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: var(--hairline) solid var(--line);
}
.x {
  border: 0;
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
  font-size: 14px;
}
.block {
  border-top: var(--hairline) solid var(--line);
  padding-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.label {
  color: var(--ink-3);
}
</style>
