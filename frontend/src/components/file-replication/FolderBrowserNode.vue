<script setup lang="ts">
import type { BrowseEntry } from '../../services/fileEndpoints'
import type { PathSelectionState } from '../../utils/pathSelection'

defineProps<{
  entry: BrowseEntry
  depth: number
  expanded: Record<string, boolean>
  childrenCache: Record<string, BrowseEntry[]>
  single: boolean
  dirsOnly: boolean
  shareOnly: boolean
  selectPath: (entry: BrowseEntry) => string
  canSelectEntry: (entry: BrowseEntry) => boolean
  selectionStateFor: (entry: BrowseEntry) => PathSelectionState
}>()

const emit = defineEmits<{
  expand: [entry: BrowseEntry]
  select: [entry: BrowseEntry]
}>()
</script>

<template>
  <li class="fb-node">
    <div class="fb-row" :class="{ excluded: entry.is_excluded }">
      <button
        v-if="entry.is_dir"
        type="button"
        class="fb-expand"
        @click="emit('expand', entry)"
      >
        {{ expanded[entry.path] ? '▾' : '▸' }}
      </button>
      <span v-else class="fb-expand-spacer" />
      <label
        class="fb-label"
        :class="{
          'fb-disabled': !canSelectEntry(entry) && selectionStateFor(entry) === 'none',
          'fb-included': selectionStateFor(entry) === 'included',
        }"
      >
        <input
          :type="single ? 'radio' : 'checkbox'"
          :name="single ? 'fb-single-pick' : undefined"
          :disabled="!canSelectEntry(entry) && selectionStateFor(entry) !== 'selected'"
          :checked="selectionStateFor(entry) !== 'none'"
          @change="emit('select', entry)"
        />
        <span>{{ entry.name }}</span>
        <span v-if="selectionStateFor(entry) === 'included'" class="fb-badge">inclusa</span>
        <span v-else-if="entry.is_excluded" class="fb-badge">escluso</span>
      </label>
    </div>
    <ul v-if="entry.is_dir && expanded[entry.path]" class="fb-children">
      <FolderBrowserNode
        v-for="child in childrenCache[entry.path] || []"
        :key="child.path"
        :entry="child"
        :depth="depth + 1"
        :expanded="expanded"
        :children-cache="childrenCache"
        :single="single"
        :dirs-only="dirsOnly"
        :share-only="shareOnly"
        :select-path="selectPath"
        :can-select-entry="canSelectEntry"
        :selection-state-for="selectionStateFor"
        @expand="emit('expand', $event)"
        @select="emit('select', $event)"
      />
    </ul>
  </li>
</template>

<style scoped>
.fb-node { list-style: none; }
.fb-children { list-style: none; margin: 0; padding-left: 20px; }
.fb-row { display: flex; align-items: center; gap: 6px; padding: 2px 0; }
.fb-row.excluded { opacity: 0.55; }
.fb-expand { background: none; border: none; cursor: pointer; width: 20px; color: inherit; }
.fb-expand-spacer { width: 20px; display: inline-block; }
.fb-label { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.fb-label.fb-disabled { opacity: 0.5; cursor: not-allowed; }
.fb-label.fb-included { opacity: 0.85; }
.fb-badge { font-size: 0.7rem; opacity: 0.7; }
</style>
