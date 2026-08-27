<script setup lang="ts">
import { zhCN, dateZhCN, darkTheme, NConfigProvider, NMessageProvider, NDialogProvider, NNotificationProvider } from 'naive-ui'
import { themeOverrides } from './styles/theme'

const appName = 'Paper-Copilot'
</script>

<template>
  <NConfigProvider :locale="zhCN" :date-locale="dateZhCN" :theme-overrides="themeOverrides">
    <NMessageProvider>
      <NDialogProvider>
        <NNotificationProvider>
          <div class="app-shell">
            <router-view />
          </div>
        </NNotificationProvider>
      </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>

<style>
.app-shell {
  display: flex;
  height: 100vh;
  width: 100vw;
}
</style>
