import 'dotenv/config';
import { chromium } from 'playwright';
import { createInterface } from 'node:readline/promises';
import { mkdirSync, writeFileSync, chmodSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
const url = process.argv[2];
if (!url) throw new Error('用法：npm run auth -- https://your-app.example.com');
const target = new URL(url);
if (!['http:', 'https:'].includes(target.protocol) || target.username || target.password)
  throw new Error('只支持无内嵌凭据的 HTTP(S) 地址。');
const channel = process.env.BROWSER_CHANNEL || 'chrome';
const browser = await chromium.launch({
  headless: false,
  ...(channel !== 'chromium' ? { channel } : {}),
});
const context = await browser.newContext();
const readline = createInterface({ input: process.stdin, output: process.stdout });
try {
  const page = await context.newPage();
  await page.goto(target.href);
  console.log('请在打开的独立浏览器中自行登录。此过程不录制操作，也不读取密码。');
  await readline.question('登录成功并回到目标应用后，按 Enter 保存本机登录态：');
  const path = resolve(process.env.BROWSER_STORAGE_STATE || 'data/auth.json');
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  writeFileSync(path, JSON.stringify(await context.storageState()), { mode: 0o600 });
  chmodSync(path, 0o600);
  console.log(
    `登录态已保存到 ${path}。请在 .env 中设置 BROWSER_STORAGE_STATE 和 ALLOWED_ORIGINS 后重启服务。`,
  );
} finally {
  readline.close();
  await context.close();
  await browser.close();
}
