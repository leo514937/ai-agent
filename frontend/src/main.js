import { createApp } from 'vue';
import App from './App.vue';
import router from './router/index.js';
import './styles.css';
import { readStoredValue, writeStoredValue } from './lib/storage.js';

const themeKey = 'hmdp-theme';

if (typeof window !== 'undefined') {
  const preferredTheme = readStoredValue(window.localStorage, themeKey, 'light');
  document.documentElement.dataset.theme = preferredTheme;
  writeStoredValue(window.localStorage, themeKey, preferredTheme);
}

createApp(App).use(router).mount('#app');
