<template>
  <div class="schedule-editor">
    <div class="se-kind-grid">
      <button
        v-for="opt in kindOptions"
        :key="opt.value"
        type="button"
        class="se-kind-card"
        :class="{ active: model.kind === opt.value }"
        @click="setKind(opt.value)"
      >
        <span class="se-kind-icon">{{ opt.icon }}</span>
        <span class="se-kind-label">{{ opt.label }}</span>
        <span class="se-kind-hint">{{ opt.hint }}</span>
      </button>
    </div>

    <div class="se-form" v-if="model.kind !== 'manual'">
      <!-- hourly / every_n_hours: minute -->
      <div class="se-row" v-if="model.kind === 'hourly' || model.kind === 'every_n_hours'">
        <label class="se-label">Minuto</label>
        <input
          type="number"
          min="0"
          max="59"
          class="form-input se-input-sm"
          :value="model.minute ?? 0"
          @input="patch({ minute: clampInt(($event.target as any).value, 0, 59) })"
        />
        <span class="se-hint">: {{ String(model.minute ?? 0).padStart(2, '0') }} di ogni ora</span>
      </div>

      <!-- every_n_hours: N -->
      <div class="se-row" v-if="model.kind === 'every_n_hours'">
        <label class="se-label">Ogni</label>
        <input
          type="number"
          min="1"
          max="23"
          class="form-input se-input-sm"
          :value="model.hours ?? 4"
          @input="patch({ hours: clampInt(($event.target as any).value, 1, 23) })"
        />
        <span class="se-hint">ore</span>
      </div>

      <!-- daily / weekly / monthly / every_n_days: time -->
      <div
        class="se-row"
        v-if="['daily', 'weekly', 'monthly', 'every_n_days'].includes(model.kind)"
      >
        <label class="se-label">Orario</label>
        <input
          type="time"
          class="form-input se-input-sm"
          :value="model.time || '02:00'"
          @input="patch({ time: ($event.target as any).value })"
        />
      </div>

      <!-- every_n_days: N -->
      <div class="se-row" v-if="model.kind === 'every_n_days'">
        <label class="se-label">Ogni</label>
        <input
          type="number"
          min="1"
          max="30"
          class="form-input se-input-sm"
          :value="model.days ?? 2"
          @input="patch({ days: clampInt(($event.target as any).value, 1, 30) })"
        />
        <span class="se-hint">giorni</span>
      </div>

      <!-- weekly: weekdays -->
      <div class="se-row se-row-block" v-if="model.kind === 'weekly'">
        <label class="se-label">Giorni della settimana</label>
        <div class="se-weekdays">
          <button
            v-for="d in WEEKDAYS_ORDER"
            :key="d"
            type="button"
            class="se-weekday"
            :class="{ active: (model.weekdays || []).includes(d) }"
            @click="toggleWeekday(d)"
          >
            {{ WEEKDAY_LABELS_IT[d] }}
          </button>
        </div>
      </div>

      <!-- monthly: day_of_month -->
      <div class="se-row" v-if="model.kind === 'monthly'">
        <label class="se-label">Giorno del mese</label>
        <input
          type="number"
          min="1"
          max="31"
          class="form-input se-input-sm"
          :value="model.day_of_month ?? 1"
          @input="patch({ day_of_month: clampInt(($event.target as any).value, 1, 31) })"
        />
      </div>

      <!-- advanced: cron raw -->
      <div class="se-row se-row-block" v-if="model.kind === 'advanced'">
        <label class="se-label">Espressione cron</label>
        <input
          type="text"
          class="form-input"
          :value="model.cron || ''"
          @input="patch({ cron: ($event.target as any).value })"
          placeholder="minuto ora giorno mese giorno_settimana"
        />
        <span class="se-hint">Es. <code>0 */4 * * *</code></span>
      </div>
    </div>

    <div class="se-preview">
      <div class="se-preview-row">
        <span class="se-preview-label">Riepilogo</span>
        <span class="se-preview-value" :class="{ 'is-error': !!preview.error }">
          {{ preview.human || '—' }}
        </span>
      </div>
      <div class="se-preview-row" v-if="preview.cron">
        <span class="se-preview-label">Cron</span>
        <code class="se-preview-cron">{{ preview.cron }}</code>
      </div>
      <div class="se-preview-row" v-if="preview.error">
        <span class="se-preview-label">Errore</span>
        <span class="se-preview-value is-error">{{ preview.error }}</span>
      </div>
      <div class="se-next" v-if="preview.next_runs.length">
        <span class="se-preview-label">Prossime 5 esecuzioni (UTC)</span>
        <ul>
          <li v-for="(t, i) in preview.next_runs" :key="i">{{ formatRun(t) }}</li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import scheduleService, {
  WEEKDAYS_ORDER,
  WEEKDAY_LABELS_IT,
  type ScheduleConfig,
  type ScheduleKind,
  type WeekDay,
  type TranslateResponse,
} from '../../services/schedule'

const props = defineProps<{
  modelValue: ScheduleConfig | null | undefined
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: ScheduleConfig): void
  (e: 'cron', value: string | null): void
}>()

const kindOptions: Array<{
  value: ScheduleKind
  label: string
  hint: string
  icon: string
}> = [
  { value: 'manual', label: 'Manuale', hint: 'Solo on-demand', icon: '✋' },
  { value: 'hourly', label: 'Orario', hint: 'Ogni ora', icon: '⏰' },
  { value: 'every_n_hours', label: 'Ogni N ore', hint: 'Es. ogni 4h', icon: '🕒' },
  { value: 'daily', label: 'Giornaliero', hint: 'Una volta al giorno', icon: '📅' },
  { value: 'weekly', label: 'Settimanale', hint: 'Giorni scelti', icon: '🗓️' },
  { value: 'every_n_days', label: 'Ogni N giorni', hint: 'Es. ogni 2 giorni', icon: '⏭️' },
  { value: 'monthly', label: 'Mensile', hint: 'Un giorno fisso', icon: '🗓' },
  { value: 'advanced', label: 'Avanzato', hint: 'Cron raw', icon: '⚙️' },
]

const defaultsByKind: Record<ScheduleKind, ScheduleConfig> = {
  manual: { kind: 'manual' },
  hourly: { kind: 'hourly', minute: 0 },
  every_n_hours: { kind: 'every_n_hours', hours: 4, minute: 0 },
  daily: { kind: 'daily', time: '02:00' },
  weekly: { kind: 'weekly', time: '02:00', weekdays: ['mon'] },
  every_n_days: { kind: 'every_n_days', days: 2, time: '02:00' },
  monthly: { kind: 'monthly', day_of_month: 1, time: '02:00' },
  advanced: { kind: 'advanced', cron: '0 2 * * *' },
}

const model = ref<ScheduleConfig>(
  props.modelValue && props.modelValue.kind
    ? { ...props.modelValue }
    : { kind: 'manual' }
)

const preview = ref<TranslateResponse>({
  config: model.value,
  cron: null,
  human: '—',
  valid: true,
  next_runs: [],
})

watch(
  () => props.modelValue,
  v => {
    if (v && v.kind && JSON.stringify(v) !== JSON.stringify(model.value)) {
      model.value = { ...v }
    }
  },
  { deep: true }
)

watch(
  model,
  async v => {
    emit('update:modelValue', v)
    try {
      const r = await scheduleService.translate({ config: v })
      preview.value = r.data
      emit('cron', r.data.cron ?? null)
    } catch (e: any) {
      preview.value = {
        config: v,
        cron: null,
        human: '—',
        valid: false,
        error: e?.response?.data?.detail || e?.message || String(e),
        next_runs: [],
      }
      emit('cron', null)
    }
  },
  { deep: true, immediate: true }
)

function setKind(k: ScheduleKind) {
  // Mantieni i campi compatibili con il nuovo kind dove possibile
  const next: ScheduleConfig = { ...defaultsByKind[k] }
  if (model.value.time && (k === 'daily' || k === 'weekly' || k === 'monthly' || k === 'every_n_days'))
    next.time = model.value.time
  if (model.value.minute != null && (k === 'hourly' || k === 'every_n_hours'))
    next.minute = model.value.minute
  model.value = next
}

function patch(part: Partial<ScheduleConfig>) {
  model.value = { ...model.value, ...part }
}

function toggleWeekday(d: WeekDay) {
  const cur = new Set(model.value.weekdays || [])
  if (cur.has(d)) cur.delete(d)
  else cur.add(d)
  // mantieni ordine canonico
  patch({ weekdays: WEEKDAYS_ORDER.filter(w => cur.has(w)) })
}

function clampInt(v: any, min: number, max: number) {
  const n = parseInt(v, 10)
  if (Number.isNaN(n)) return min
  return Math.min(max, Math.max(min, n))
}

function formatRun(iso: string) {
  try {
    const d = new Date(iso)
    return d.toLocaleString('it-IT', { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return iso
  }
}
</script>

<style scoped>
.schedule-editor {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.se-kind-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--space-2);
}

.se-kind-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: var(--space-3);
  background: var(--color-bg-element);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text-primary);
  cursor: pointer;
  text-align: left;
  transition: border-color 0.15s, background 0.15s;
}
.se-kind-card:hover {
  border-color: var(--color-border-hover);
  background: var(--color-bg-hover);
}
.se-kind-card.active {
  border-color: var(--color-primary);
  background: var(--color-primary-dim);
}
.se-kind-icon {
  font-size: 1.1rem;
}
.se-kind-label {
  font-weight: 600;
  font-size: 0.85rem;
}
.se-kind-hint {
  font-size: 0.7rem;
  color: var(--color-text-secondary);
}

.se-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-3);
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}
.se-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.se-row-block {
  flex-direction: column;
  align-items: flex-start;
}
.se-label {
  min-width: 160px;
  font-size: 0.8rem;
  color: var(--color-text-secondary);
}
.se-input-sm {
  max-width: 110px;
}
.se-hint {
  font-size: 0.75rem;
  color: var(--color-text-secondary);
}

.se-weekdays {
  display: flex;
  gap: var(--space-1);
  flex-wrap: wrap;
}
.se-weekday {
  padding: 6px 12px;
  background: var(--color-bg-element);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  color: var(--color-text-secondary);
  font-weight: 600;
  font-size: 0.78rem;
  cursor: pointer;
  transition: all 0.15s;
}
.se-weekday:hover {
  border-color: var(--color-border-hover);
}
.se-weekday.active {
  background: var(--color-primary-dim);
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.se-preview {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
  background: var(--color-bg-surface);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-md);
}
.se-preview-row {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  font-size: 0.85rem;
}
.se-preview-label {
  min-width: 140px;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-text-secondary);
}
.se-preview-value {
  color: var(--color-text-primary);
}
.se-preview-value.is-error {
  color: var(--color-danger-fg);
}
.se-preview-cron {
  font-family: var(--font-mono);
  background: var(--color-bg-element);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  font-size: 0.8rem;
}
.se-next ul {
  margin: var(--space-1) 0 0;
  padding-left: var(--space-5);
  font-size: 0.78rem;
  color: var(--color-text-secondary);
  font-family: var(--font-mono);
}
</style>
