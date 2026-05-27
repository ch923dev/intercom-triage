<!-- Stats dashboard (roadmap 1.3) — the four success metrics (spec §8) rolled
     up server-side and rendered dependency-free: category breakdown, volume
     trend (sparkline), resolution-source mix (resolved_source, invariant #10),
     and time-to-resolve distribution. Bars/sparkline are plain divs sized off
     the store's max-count getters; no charting library. -->
<script setup lang="ts">
import { computed, onMounted } from 'vue';
import Mono from './Mono.vue';
import { useCategoriesStore } from '@/stores/categories';
import { useStatsStore, WINDOW_OPTIONS } from '@/stores/stats';

const stats = useStatsStore();
const categories = useCategoriesStore();

onMounted(() => {
  if (!stats.loaded) void stats.refresh();
});

/** Map a category id to its swatch color (falls back to the neutral line
 *  token for uncategorized / unknown ids). */
function categoryColor(id: number | null): string {
  if (id === null) return 'var(--ink-3)';
  const cat = categories.byId.get(id);
  return cat?.color ?? 'var(--ink-3)';
}

/** Width % for a bar given a value and the metric's max. Guards divide-by-0
 *  (an all-zero metric renders empty bars, not NaN). A non-zero value always
 *  draws a sliver so it stays visible. */
function barPct(value: number, max: number): number {
  if (max <= 0) return 0;
  return Math.max((value / max) * 100, value > 0 ? 4 : 0);
}

const mix = computed(() => stats.data?.resolution_mix ?? null);

/** Resolution-mix rows for the segmented bar + legend. */
const mixRows = computed(() => {
  const m = mix.value;
  if (!m) return [];
  return [
    { key: 'open', label: 'Open', count: m.open, color: 'var(--ink-3)' },
    { key: 'manual', label: 'Manual', count: m.manual, color: 'var(--accent)' },
    {
      key: 'intercom_closed',
      label: 'Intercom closed',
      count: m.intercom_closed,
      color: 'var(--ink-2)',
    },
    {
      key: 'non_actionable',
      label: 'Non-actionable',
      count: m.non_actionable,
      color: 'var(--line)',
    },
    {
      key: 'ai_resolved',
      label: 'AI resolved',
      count: m.ai_resolved,
      color: 'var(--accent-soft-2)',
    },
  ];
});

const mixTotal = computed(() => mixRows.value.reduce((s, r) => s + r.count, 0));

function mixPct(count: number): number {
  if (mixTotal.value <= 0) return 0;
  return (count / mixTotal.value) * 100;
}

/** Format the median resolve time as a human-readable duration. */
const medianLabel = computed(() => {
  const h = stats.data?.median_resolve_hours;
  if (h === null || h === undefined) return '—';
  if (h < 1) return `${Math.round(h * 60)} min`;
  if (h < 24) return `${h.toFixed(1)} h`;
  return `${(h / 24).toFixed(1)} d`;
});

/** Short day label for the volume sparkline (e.g. "05-12"). */
function dayLabel(iso: string): string {
  return iso.slice(5);
}
</script>

<template>
  <div class="stats-page">
    <header class="stats-head">
      <div class="title-row">
        <Mono :size="12">Dashboard</Mono>
        <div class="window-seg">
          <button
            v-for="w in WINDOW_OPTIONS"
            :key="w"
            :class="{ active: stats.windowDays === w }"
            @click="stats.setWindow(w)"
          >
            <span class="mono">{{ w }}d</span>
          </button>
        </div>
        <button class="ghost" :disabled="stats.loading" @click="stats.refresh()">
          <span class="mono">{{ stats.loading ? 'Loading…' : 'Refresh' }}</span>
        </button>
      </div>
      <Mono v-if="stats.data" class="subtle">
        {{ stats.data.total_tickets }} tickets · last {{ stats.data.window_days }} days
      </Mono>
    </header>

    <div v-if="stats.error" class="status error mono">Backend unreachable — {{ stats.error }}</div>
    <div v-else-if="!stats.loaded && stats.loading" class="status mono">Loading…</div>
    <div v-else-if="stats.data && stats.data.total_tickets === 0" class="status mono">
      No tickets in this window.
    </div>

    <div v-else-if="stats.data" class="grid">
      <!-- 1 — Category breakdown -->
      <section class="card">
        <Mono class="card-title">Category breakdown</Mono>
        <ul class="bars">
          <li
            v-for="c in stats.data.category_breakdown"
            :key="c.category_id ?? 'none'"
            class="bar-row"
          >
            <span class="bar-label" :title="c.category_name">{{ c.category_name }}</span>
            <span class="bar-track">
              <span
                class="bar-fill"
                :style="{
                  width: barPct(c.count, stats.maxCategoryCount) + '%',
                  background: categoryColor(c.category_id),
                }"
              />
            </span>
            <span class="bar-count mono">{{ c.count }}</span>
          </li>
        </ul>
      </section>

      <!-- 2 — Resolution mix -->
      <section class="card">
        <Mono class="card-title">Resolution mix</Mono>
        <div class="mix-bar">
          <span
            v-for="r in mixRows"
            :key="r.key"
            class="mix-seg"
            :style="{ width: mixPct(r.count) + '%', background: r.color }"
            :title="`${r.label}: ${r.count}`"
          />
        </div>
        <ul class="legend">
          <li v-for="r in mixRows" :key="r.key" class="legend-row">
            <span class="swatch" :style="{ background: r.color }" />
            <span class="legend-label">{{ r.label }}</span>
            <span class="legend-count mono">{{ r.count }}</span>
          </li>
        </ul>
        <Mono class="subtle">{{ stats.resolvedTotal }} resolved of {{ mixTotal }}</Mono>
      </section>

      <!-- 3 — Volume trend -->
      <section class="card span-2">
        <Mono class="card-title">Volume trend</Mono>
        <div class="spark">
          <span
            v-for="p in stats.data.volume_trend"
            :key="p.date"
            class="spark-col"
            :title="`${p.date}: ${p.count}`"
          >
            <span
              class="spark-fill"
              :style="{ height: barPct(p.count, stats.maxVolumeCount) + '%' }"
            />
          </span>
        </div>
        <div class="spark-axis">
          <Mono class="subtle">{{ dayLabel(stats.data.volume_trend[0]?.date ?? '') }}</Mono>
          <Mono class="subtle">
            {{ dayLabel(stats.data.volume_trend[stats.data.volume_trend.length - 1]?.date ?? '') }}
          </Mono>
        </div>
      </section>

      <!-- 4 — Time-to-resolve distribution -->
      <section class="card span-2">
        <div class="card-title-row">
          <Mono class="card-title">Time to resolve</Mono>
          <Mono class="subtle">median {{ medianLabel }}</Mono>
        </div>
        <ul class="bars">
          <li v-for="b in stats.data.resolve_time_buckets" :key="b.label" class="bar-row">
            <span class="bar-label">{{ b.label }}</span>
            <span class="bar-track">
              <span
                class="bar-fill accent"
                :style="{ width: barPct(b.count, stats.maxResolveBucketCount) + '%' }"
              />
            </span>
            <span class="bar-count mono">{{ b.count }}</span>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>

<style scoped>
.stats-page {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}
.stats-head {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 16px;
}
.title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.subtle {
  color: var(--ink-3);
}
.window-seg {
  display: inline-flex;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  overflow: hidden;
}
.window-seg button {
  padding: 4px 10px;
  border: 0;
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
}
.window-seg button.active {
  background: var(--ink);
  color: var(--bg);
}
.ghost {
  padding: 4px 10px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: transparent;
  color: var(--ink);
  cursor: pointer;
}
.ghost:disabled {
  opacity: 0.5;
  cursor: default;
}
.status {
  padding: 40px 20px;
  text-align: center;
  color: var(--ink-3);
}
.status.error {
  color: var(--accent);
}
.grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}
.card {
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-card);
  background: var(--panel);
  padding: 16px;
}
.card.span-2 {
  grid-column: 1 / -1;
}
.card-title {
  display: block;
  color: var(--ink-2);
  margin-bottom: 12px;
}
.card-title-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 12px;
}
/* Horizontal bar list (category breakdown + time-to-resolve) */
.bars {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.bar-row {
  display: grid;
  grid-template-columns: 120px 1fr 36px;
  align-items: center;
  gap: 8px;
}
.bar-label {
  font-size: 12px;
  color: var(--ink-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.bar-track {
  height: 12px;
  background: var(--chip-bg);
  border-radius: var(--radius-pill);
  overflow: hidden;
}
.bar-fill {
  display: block;
  height: 100%;
  border-radius: var(--radius-pill);
  transition: width 160ms ease;
}
.bar-fill.accent {
  background: var(--accent);
}
.bar-count {
  text-align: right;
  color: var(--ink-2);
}
/* Resolution-mix segmented bar + legend */
.mix-bar {
  display: flex;
  height: 16px;
  border-radius: var(--radius-pill);
  overflow: hidden;
  background: var(--chip-bg);
  margin-bottom: 12px;
}
.mix-seg {
  height: 100%;
  transition: width 160ms ease;
}
.legend {
  list-style: none;
  margin: 0 0 8px;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.legend-row {
  display: grid;
  grid-template-columns: 14px 1fr auto;
  align-items: center;
  gap: 8px;
}
.swatch {
  width: 10px;
  height: 10px;
  border-radius: 2px;
}
.legend-label {
  font-size: 12px;
  color: var(--ink-2);
}
.legend-count {
  color: var(--ink-2);
}
/* Volume sparkline — equal-width columns growing from the baseline. */
.spark {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 96px;
}
.spark-col {
  flex: 1;
  height: 100%;
  display: flex;
  align-items: flex-end;
  background: var(--line-soft);
  border-radius: var(--radius-chip);
  overflow: hidden;
}
.spark-fill {
  width: 100%;
  background: var(--accent);
  border-radius: var(--radius-chip) var(--radius-chip) 0 0;
  transition: height 160ms ease;
}
.spark-axis {
  display: flex;
  justify-content: space-between;
  margin-top: 6px;
  color: var(--ink-3);
}
</style>
