<script setup lang="ts">
import axios from 'axios'
import { computed, ref, watch } from 'vue'
import { fileEndpointsApi, type BrowseEntry } from '../../services/fileEndpoints'
import {
  compactSourcePaths,
  isPathAncestor,
  normalizeBrowsePath,
  pathSelectionState,
} from '../../utils/pathSelection'
import { normalizeQnapDestShare, normalizeQnapStagingPath } from '../../utils/qnapPath'
import FolderBrowserNode from './FolderBrowserNode.vue'

const props = withDefaults(
  defineProps<{
    endpointId: number | null
    modelValue: string[]
    excludePresets?: string[]
    mode?: 'single' | 'multiple'
    dirsOnly?: boolean
    normalizeQnapPaths?: boolean
    shareOnly?: boolean
    hint?: string
  }>(),
  {
    mode: 'multiple',
    dirsOnly: true,
    normalizeQnapPaths: false,
    shareOnly: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [paths: string[]]
}>()

const entries = ref<BrowseEntry[]>([])
const expanded = ref<Record<string, boolean>>({})
const childrenCache = ref<Record<string, BrowseEntry[]>>({})
const loading = ref(false)
const error = ref('')

const single = computed(() => props.mode === 'single')

const selectedPaths = computed(() => props.modelValue || [])

function mapPath(path: string) {
  if (props.shareOnly) return normalizeQnapDestShare(path)
  return props.normalizeQnapPaths ? normalizeQnapStagingPath(path) : path
}

function selectPath(entry: BrowseEntry) {
  return mapPath(entry.path)
}

function canSelectEntry(entry: BrowseEntry) {
  if (!entry.selectable) return false
  if (props.dirsOnly && !entry.is_dir) return false
  if (props.shareOnly) {
    const normalized = mapPath(entry.path)
    const parts = normalized.replace(/^\/+/, '').split('/').filter(Boolean)
    return parts.length === 2 && parts[0] === 'share'
  }
  const path = selectPath(entry)
  return pathSelectionState(path, selectedPaths.value) !== 'included'
}

function selectionStateFor(entry: BrowseEntry) {
  return pathSelectionState(selectPath(entry), selectedPaths.value)
}

function setSelected(paths: string[]) {
  const next = single.value ? paths.slice(0, 1) : compactSourcePaths(paths)
  emit('update:modelValue', next)
}

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
  if (!canSelectEntry(entry) && selectionStateFor(entry) !== 'selected') return
  const path = selectPath(entry)
  if (single.value) {
    setSelected([path])
    return
  }

  const current = selectedPaths.value.map(normalizeBrowsePath)
  const state = pathSelectionState(path, current)

  if (state === 'selected') {
    setSelected(current.filter((p) => p !== normalizeBrowsePath(path)))
    return
  }

  const withoutDescendants = current.filter(
    (p) => !isPathAncestor(path, p) && !isPathAncestor(p, path),
  )
  withoutDescendants.push(normalizeBrowsePath(path))
  setSelected(withoutDescendants)
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

watch(
  () => props.modelValue,
  (paths) => {
    if (single.value || !paths?.length) return
    const compact = compactSourcePaths(paths)
    if (compact.length !== paths.length || compact.some((p, i) => p !== paths[i])) {
      emit('update:modelValue', compact)
    }
  },
  { deep: true },
)
</script>

<template>
  <div class="fb-wrap">
    <p v-if="hint" class="fb-hint">{{ hint }}</p>
    <p v-if="!endpointId" class="fb-hint">Seleziona un endpoint per sfogliare le cartelle.</p>
    <p v-if="error" class="fb-error">{{ error }}</p>
    <div v-if="loading" class="fb-loading">Caricamento…</div>
    <ul v-if="endpointId" class="fb-tree">
      <FolderBrowserNode
        v-for="entry in entries"
        :key="entry.path"
        :entry="entry"
        :depth="0"
        :expanded="expanded"
        :children-cache="childrenCache"
        :single="single"
        :dirs-only="dirsOnly"
        :share-only="shareOnly"
        :select-path="selectPath"
        :can-select-entry="canSelectEntry"
        :selection-state-for="selectionStateFor"
        @expand="toggleExpand"
        @select="toggleSelect"
      />
    </ul>
    <p v-if="single && modelValue.length" class="fb-selected">
      Share destinazione: <code>{{ modelValue[0] }}</code>
    </p>
    <p v-else-if="modelValue.length" class="fb-selected">
      {{ modelValue.length }} radici · i sottopercorsi sono inclusi automaticamente
    </p>
  </div>
</template>

<style scoped>
.fb-wrap {
  border: 1px solid var(--border-color, #333);
  border-radius: 8px;
  padding: 12px;
  max-height: 360px;
  overflow: auto;
}
.fb-tree {
  list-style: none;
  margin: 0;
  padding-left: 0;
}
.fb-hint,
.fb-error,
.fb-loading,
.fb-selected {
  font-size: 0.875rem;
  margin: 8px 0 0;
}
.fb-error {
  color: var(--danger, #e74c3c);
}
.fb-selected code {
  font-size: 0.85em;
  word-break: break-all;
}
</style>
