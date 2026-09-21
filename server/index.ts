import 'dotenv/config';
import express from 'express';
import { resolve } from 'node:path';
import { createServer as createHttpServer } from 'node:http';
import { createApp } from './app.js';

const port = Number(process.env.PORT || 3210);
const baseUrl = `http://127.0.0.1:${port}`;
const service = createApp({ dataDir: resolve(process.env.DATA_DIR || 'data'), baseUrl });
const server = createHttpServer(service.app);
let closeVite: (() => Promise<void>) | undefined;
if (process.env.NODE_ENV === 'production') {
  service.app.use(express.static(resolve('dist')));
  service.app.get('/{*path}', (_req, res) => res.sendFile(resolve('dist/index.html')));
} else {
  const { createServer } = await import('vite');
  const vite = await createServer({
    server: { middlewareMode: true, hmr: { server } },
    appType: 'spa',
  });
  closeVite = () => vite.close();
  service.app.use(vite.middlewares);
}
server.listen(port, '127.0.0.1', () => console.log(`\n  SkillCUA is ready → ${baseUrl}\n`));
async function stop() {
  server.close();
  await closeVite?.();
  await service.close();
  process.exit(0);
}
process.on('SIGINT', () => void stop());
process.on('SIGTERM', () => void stop());
