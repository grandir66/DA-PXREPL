<script setup lang="ts">
import axios from 'axios'
import { onMounted, ref } from 'vue'
import Icon from '../ui/Icon.vue'
import vmsService from '../../services/vms'
import {
  vmSnapshotsApi,
  type VmSnapshotJob,
  type VmSnapshotVmEntry,
} from '../../services/vmSnapshots'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps<{ job: VmSnapshotJob }>()
const emit = defineEmits<{ close: [] }>()

const entries = ref<VmSnapshotVmEntry[]>([])
const loading = ref(false)
const errorMsg = ref('')
const busyKey = ref('')
const actionMsg = ref('')

function fmtDate(snaptime?: number | null) {
  if (!snaptime) return '—'
  return new Date(snaptime * 1000).toLocaleString('it-IT')
}

async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    const { data } = await vmSnapshotsApi.snapshots(props.job.id)
    entries.value = data
  } catch (e: unknown) {
    errorMsg.value = axios.isAxiosError(e)
      ? String(e.response?.data?.detail || e.message)
      : t('snapSfoglia.erroreCarico')
  } finally {
    loading.value = false
  }
}

async function rollback(vm: VmSnapshotVmEntry, snapname: string) {
  const confirmed = window.confirm(
    t('snapSfoglia.confRollback', { vm: vm.vm_name || vm.vmid, nome: snapname }) + (vm.has_pvesr ? '\n' + t('snapSfoglia.confRollbackPvesr') : ''),
  )
  if (!confirmed) return
  const startVm = window.confirm(t('snapSfoglia.avviare'))
  busyKey.value = `${vm.vmid}:${snapname}`
  actionMsg.value = ''
  try {
    const resp = await vmsService.rollbackSnapshot(vm.node_id, vm.vmid, snapname, startVm, vm.vm_type)
    const resync = ((resp as any)?.data?.pvesr_resync || []) as Array<{ ok: boolean; id: string }>
    let extra = ''
    if (resync.length) {
      const okc = resync.filter((r) => r.ok).length
      extra = okc === resync.length
        ? ' ' + t('snapSfoglia.resyncOk') : ' ' + t('snapSfoglia.resyncNo', { n: resync.length - okc })
    }
    actionMsg.value = t('snapSfoglia.rollbackFatto', { vm: vm.vm_name || vm.vmid, nome: snapname }) + extra
    await load()
  } catch (e: unknown) {
    actionMsg.value = axios.isAxiosError(e)
      ? `${t('snapSfoglia.erroreRollback')}: ${e.response?.data?.detail || e.message}`
      : t('snapSfoglia.erroreRollback')
  } finally {
    busyKey.value = ''
  }
}

async function removeSnapshot(vm: VmSnapshotVmEntry, snapname: string) {
  if (!window.confirm(t('snapSfoglia.confElimina', { nome: snapname, vm: vm.vm_name || vm.vmid }))) return
  busyKey.value = `${vm.vmid}:${snapname}`
  actionMsg.value = ''
  try {
    await vmsService.deleteSnapshot(vm.node_id, vm.vmid, snapname, vm.vm_type)
    actionMsg.value = t('snapSfoglia.eliminato', { nome: snapname })
    await load()
  } catch (e: unknown) {
    actionMsg.value = axios.isAxiosError(e)
      ? `${t('comune.erroreEliminazione')}: ${e.response?.data?.detail || e.message}`
      : t('comune.erroreEliminazione')
  } finally {
    busyKey.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal-card">
      <header class="modal-head">
        <h2>{{ t('snapSfoglia.titolo', { nome: job.name }) }}</h2>
        <div>
          <button type="button" class="btn btn-sm btn-secondary mr-2" :disabled="loading" @click="load">
            {{ t('comune.aggiorna') }}
          </button>
          <button type="button" class="btn btn-sm" @click="emit('close')">✕</button>
        </div>
      </header>

      <div class="modal-body">
        <p v-if="errorMsg" class="text-danger">{{ errorMsg }}</p>
        <p v-if="actionMsg" class="action-msg">{{ actionMsg }}</p>
        <p v-if="loading" class="text-muted">{{ t('snapSfoglia.carico') }}</p>

        <div v-for="vm in entries" :key="`${vm.node_id}:${vm.vmid}`" class="vm-block">
          <div class="vm-block-head">
            <strong><code>{{ vm.vmid }}</code> {{ vm.vm_name }}</strong>
            <span class="badge vm-type">{{ vm.vm_type === 'lxc' ? 'CT' : 'VM' }}</span>
            <span class="text-muted">@ {{ vm.node_name }}</span>
            <span v-if="vm.has_pvesr" class="badge badge-warn" :title="t('snapSfoglia.pvesr')"><Icon name="alert-triangle" :size="14" /> pvesr</span>
          </div>
          <p v-if="vm.error" class="text-danger">{{ vm.error }}</p>
          <p v-else-if="!vm.snapshots.length" class="text-muted">{{ t('snapSfoglia.nessuno') }}</p>
          <table v-else class="data-table snap-table">
            <thead>
              <tr>
                <th>{{ t('snapSfoglia.snapshot') }}</th>
                <th>{{ t('comune.data') }}</th>
                <th>{{ t('comune.descrizione') }}</th>
                <th>RAM</th>
                <th>{{ t('snapSfoglia.origine') }}</th>
                <th>{{ t('comune.azioni') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="snap in vm.snapshots" :key="snap.name">
                <td><code>{{ snap.name }}</code></td>
                <td>{{ fmtDate(snap.snaptime) }}</td>
                <td class="snap-desc">{{ snap.description || '—' }}</td>
                <td>{{ snap.vmstate ? t('comune.si') : '—' }}</td>
                <td>
                  <span v-if="snap.is_module" class="badge badge-ok" :title="t('snapSfoglia.moduloAiuto', { label: snap.label })">
                    {{ t('snapSfoglia.modulo', { label: snap.label }) }}
                  </span>
                  <span v-else class="badge badge-off" :title="t('snapSfoglia.esterno')">
                    esterno
                  </span>
                </td>
                <td class="actions">
                  <button
                    class="btn btn-sm btn-warning"
                    :disabled="busyKey === `${vm.vmid}:${snap.name}`"
                    @click="rollback(vm, snap.name)"
                  >{{ t('vm.rollback') }}</button>
                  <button
                    class="btn btn-sm btn-danger"
                    :disabled="busyKey === `${vm.vmid}:${snap.name}`"
                    @click="removeSnapshot(vm, snap.name)"
                  >{{ t('comune.elimina') }}</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.55);
  display: flex; align-items: center; justify-content: center; z-index: 1000;
}
.modal-card {
  background: var(--bg-primary, #111); border-radius: 12px;
  width: min(900px, 96vw); max-height: 90vh; overflow: auto;
}
.modal-head { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; }
.modal-body { padding: 0 20px 20px; }
.vm-block { margin-bottom: 18px; }
.vm-block-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.snap-table { width: 100%; }
.snap-desc { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.actions { display: flex; gap: 6px; }
.badge { font-size: .7rem; padding: 1px 7px; border-radius: 10px; background: rgba(255,255,255,.08); }
.badge-ok { background: rgba(46, 204, 113, .18); color: #2ecc71; }
.badge-off { opacity: .6; }
.badge-warn { background: rgba(241, 196, 15, .18); color: #f1c40f; }
.vm-type { background: rgba(155, 89, 182, .18); color: #9b59b6; }
.action-msg { color: var(--success, #2ecc71); font-size: .875rem; }
.text-muted { opacity: .75; font-size: .85rem; }
.mr-2 { margin-right: 8px; }
</style>
