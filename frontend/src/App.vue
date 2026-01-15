<template>
  <router-view></router-view>
</template>

<script setup lang="ts">
import { onMounted } from 'vue';
import { useAuthStore } from './stores/auth';

const authStore = useAuthStore();

onMounted(async () => {
  if (authStore.token) {
    try {
      await authStore.fetchUser();
    } catch (e) {
      console.error('Session expired');
    }
  }
});
</script>

<style>
/* Global styles are imported in main.ts */
</style>
