<template>
  <component
    :is="resolved"
    :size="size"
    :stroke-width="1.75"
    :class="['icon', `icon-${name}`]"
    aria-hidden="true"
  />
</template>

<script setup lang="ts">
import { computed, type Component } from 'vue'
import {
  House, Server, Network, Monitor, Database, Archive, ArrowRightLeft, Shield, Scale,
  FileText, Settings, LogOut, RefreshCw, Plus, Minus, X, Pencil, Trash2, Play, Pause,
  Square, Check, CircleCheck, CircleX, TriangleAlert, CircleHelp, Info, Search, Filter,
  Menu, ChevronDown, ChevronUp, ChevronLeft, ChevronRight, ArrowUp, ArrowDown, Eye, EyeOff,
  Download, Upload, Cpu, HardDrive, Wifi, Activity, Package, Box, Clock, Calendar, Bell,
  User, Users, Lock, LockOpen, Globe, Terminal, ExternalLink, List, Grid3x3, Copy,
  RotateCcw, Gauge, Folder, TrendingUp, TrendingDown, Thermometer, Power, Circle, Hash,
  MemoryStick, Layers, Zap, Save, Key, Mail, Send, Clipboard, History, GitBranch, Share2,
  Link, Plug, Eraser, Tag, Waypoints, Boxes,
  Wrench, Camera, Square as SquareIcon, BarChart3, Lightbulb, Hand, ScrollText,
  AlarmClock, SkipForward, CalendarDays, CalendarRange,
} from 'lucide-vue-next'

// Mappa nome-kebab → componente lucide. Backend a icone lucide con API invariata
// (`<Icon name="server" :size="16" />`). Tutti i nomi già usati nel codebase sono
// preservati; nomi mancanti ricadono su "help-circle". Nuove icone: aggiungi qui.
const MAP: Record<string, Component> = {
  // Navigazione / layout
  home: House, server: Server, cluster: Network, network: Network, monitor: Monitor,
  database: Database, archive: Archive, 'arrow-right-left': ArrowRightLeft, shield: Shield,
  scale: Scale, 'file-text': FileText, settings: Settings, 'log-out': LogOut, menu: Menu,
  grid: Grid3x3, list: List, layers: Layers, folder: Folder,
  // Azioni
  refresh: RefreshCw, 'rotate-ccw': RotateCcw, plus: Plus, minus: Minus, x: X,
  pencil: Pencil, trash: Trash2, play: Play, pause: Pause, stop: Square, copy: Copy,
  download: Download, upload: Upload, save: Save, search: Search, filter: Filter,
  send: Send, mail: Mail, clipboard: Clipboard, share: Share2, link: Link, external: ExternalLink,
  // Stato / feedback
  check: Check, 'check-circle': CircleCheck, 'x-circle': CircleX,
  'alert-triangle': TriangleAlert, 'help-circle': CircleHelp, info: Info, bell: Bell,
  circle: Circle, activity: Activity, gauge: Gauge, power: Power, zap: Zap,
  // Chevron / arrow
  'chevron-down': ChevronDown, 'chevron-up': ChevronUp, 'chevron-left': ChevronLeft,
  'chevron-right': ChevronRight, 'arrow-up': ArrowUp, 'arrow-down': ArrowDown,
  'trending-up': TrendingUp, 'trending-down': TrendingDown,
  // Hardware / risorse
  cpu: Cpu, microchip: Cpu, 'hard-drive': HardDrive, memory: MemoryStick, wifi: Wifi,
  thermometer: Thermometer, plug: Plug, globe: Globe, terminal: Terminal,
  // Contenuti / entità
  package: Package, box: Box, clock: Clock, calendar: Calendar, history: History,
  user: User, users: Users, lock: Lock, unlock: LockOpen,
  key: Key, eye: Eye, 'eye-off': EyeOff, hash: Hash, 'git-branch': GitBranch,
  eraser: Eraser, tag: Tag, waypoints: Waypoints, boxes: Boxes,
  wrench: Wrench, camera: Camera, square: SquareIcon, chart: BarChart3,
  lightbulb: Lightbulb, hand: Hand, 'scroll-text': ScrollText,
  'alarm-clock': AlarmClock, 'skip-forward': SkipForward,
  'calendar-days': CalendarDays, 'calendar-range': CalendarRange,
}

const props = withDefaults(
  defineProps<{
    name: string
    size?: number | string
  }>(),
  { size: 16 }
)

const resolved = computed<Component>(() => MAP[props.name] || CircleHelp)
</script>

<style scoped>
.icon {
  display: inline-block;
  vertical-align: middle;
  flex-shrink: 0;
}
</style>
