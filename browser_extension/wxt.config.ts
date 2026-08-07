import { defineConfig } from 'wxt';

export default defineConfig({
  modules: ['@wxt-dev/module-react'],
  srcDir: 'src',
  outDir: 'dist',
  manifest: () => ({
    name: 'CommandCenter 演示观察器',
    description: 'Record redacted browser actions and API evidence for the local CommandCenter.',
    permissions: [
      'storage',
      'tabs',
      'activeTab',
      'webRequest',
      'webNavigation',
      'scripting',
      'alarms',
      'downloads'
    ],
    host_permissions: ['<all_urls>'],
    web_accessible_resources: [
      {
        resources: ['injected.js'],
        matches: ['<all_urls>']
      }
    ],
    action: {
      default_popup: 'popup.html',
      default_title: 'Journey Forge Local'
    }
  }),
  vite: () => ({
    build: { sourcemap: false }
  })
});
