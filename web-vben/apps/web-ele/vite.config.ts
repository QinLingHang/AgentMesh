import { defineConfig } from '@vben/vite-config';

export default defineConfig(async () => {
  return {
    application: {},
    vite: {
      server: {
        host: '127.0.0.1',
        port: 5777,
        strictPort: true,
        proxy: {
          '/api': {
            target: 'http://127.0.0.1:8086',
            changeOrigin: true,
            ws: true,
          },
        },
      },
    },
  };
});
