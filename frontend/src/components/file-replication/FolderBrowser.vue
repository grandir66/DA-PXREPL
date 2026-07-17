<script setup lang="ts">
import axios from 'axios'
import { computed, ref, watch } from 'vue'
import { fileEndpointsApi, type BrowseEntry } from '../../services/fileEndpoints'

const props = defineProps<{
  endpointId: number | null
  modelValue: string[]
  excludePresets?: string[]
}>()

const emit = defineEmits<{
  'update:modelValue': [paths: string[]]
}>()

const rootPath = ref('/')
const entries = ref<BrowseEntry[]>([])
const expanded = ref<Record<string, boolean>>({})
const childrenCache = ref<Record<string, BrowseEntry[]>>({})
const loading = ref(false)
const error = ref('')

const selected = computed({
  get: () => new Set(props.modelValue || []),
  set: (s: Set<string>) => emit('update:modelValue', [...s]),
})

async function load(path: string) {
  if (!props.endpointId) return
  loading.value = true
  error.value = ''
  try {
    const { data } = await fileEndpointsApi.browse(props.endpointId, path)
    if (path === '/') {
      entries.value = data
    } else {
      childrenCache.value[path] = data
    }
  } catch (e: unknown) {
    if (axios.isAxiosError(e)) {
      const detail = e.response?.data?.detail
      error.value =
        typeof detail === 'string'
          ? detail
          : Array.isArray(detail)
            ? detail.map((d) => d.msg || String(d)).join('; ')
            : e.message
    } else {
      error.value = e instanceof Error ? e.message : 'Errore browse'
    }
  } finally {
    loading.value = false
  }
}

async function toggleExpand(entry: BrowseEntry) {
  if (!entry.is_dir) return
  const path = entry.path
  if (expanded.value[path]) {
    expanded.value[path] = false
    return
  }
  expanded.value[path] = true
  if (!childrenCache.value[path]) {
    await load(path)
  }
}

function toggleSelect(entry: BrowseEntry) {
  if (!entry.selectable) return
  const next = new Set(selected.value)
  if (next.has(entry.path)) next.delete(entry.path)
  else next.add(entry.path)
  selected.value = next
}

function isChecked(path: string) {
  return selected.value.has(path)
}

watch(
  () => props.endpointId,
  () => {
    entries.value = []
    childrenCache.value = {}
    expanded.value = {}
    if (props.endpointId) load('/')
  },
  { immediate: true },
)
</script>

<template>
  <div class="fb-wrap">
    <p v-if="!endpointId" class="fb-hint">Seleziona un endpoint sorgente per sfogliare le cartelle.</p>
    <p v-if="error" class="fb-error">{{ error }}</p>
    <div v-if="loading" class="fb-loading">Caricamento…</div>
    <ul v-if="endpointId" class="fb-tree">
      <li v-for="entry in entries" :key="entry.path" class="fb-node">
        <div class="fb-row" :class="{ excluded: entry.is_excluded }">
          <button
            v-if="entry.is_dir"
            type="button"
            class="fb-expand"
            @click="toggleExpand(entry)"
          >
            {{ expanded[entry.path] ? '▾' : '▸' }}
          </button>
          <span v-else class="fb-expand-spacer" />
          <label class="fb-label">
            <input
              type="checkbox"
              :disabled="!entry.selectable"
              :checked="isChecked(entry.path)"
              @change="toggleSelect(entry)"
            />
            <span>{{ entry.name }}</span>
            <span v-if="entry.is_excluded" class="fb-badge">escluso</span>
          </label>
        </div>
        <ul v-if="entry.is_dir && expanded[entry.path]" class="fb-children">
          <li v-for="child in childrenCache[entry.path] || []" :key="child.path" class="fb-node">
            <div class="fb-row" :class="{ excluded: child.is_excluded }">
              <button
                v-if="child.is_dir"
                type="button"
                class="fb-expand"
                @click="toggleExpand(child)"
              >
                {{ expanded[child.path] ? '▾' : '▸' }}
              </button>
              <span v-else class="fb-expand-spacer" />
              <label class="fb-label">
                <input
                  type="checkbox"
                  :disabled="!child.selectable"
                  :checked="isChecked(child.path)"
                  @change="toggleSelect(child)"
                />
                <span>{{ child.name }}</span>
              </label>
            </div>
          </li>
        </ul>
      </li>
    </ul>
    <p v-if="modelValue.length" class="fb-selected">
      Selezionate: {{ modelValue.length }} cartelle
    </p>
  </div>
</template>

<style scoped>
.fb-wrap { border: 1px solid var(--border-color, #333); border-radius: 8px; padding: 12px; max-height: 360px; overflow: auto; }
.fb-tree, .fb-children { list-style: none; margin: 0; padding-left: 0; }
.fb-children { padding-left: 20px; }
.fb-row { display: flex; align-items: center; gap: 6px; padding: 2px 0; }
.fb-row.excluded { opacity: 0.55; }
.fb-expand { background: none; border: none; cursor: pointer; width: 20px; color: inherit; }
.fb-expand-spacer { width: 20px; display: inline-block; }
.fb-label { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.fb-badge { font-size: 0.7rem; opacity: 0.7; }
.fb-hint, .fb-error, .fb-loading, .fb-selected { font-size: 0.875rem; margin: 8px 0 0; }
.fb-error { color: var(--danger, #e74c3c); }
</style>
