import { chromium, type Browser, type BrowserContext, type Page } from 'playwright';
import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { rawActionSchema, type RawAction, type Observation, type Target } from '../shared/types.js';
import { validateUrl, sensitive } from './learning.js';

export class BrowserRuntime {
  private browser?: Promise<Browser>;
  private recorder = readFileSync(resolve('public/recorder.js'), 'utf8');
  channel = process.env.BROWSER_CHANNEL || 'chrome';
  async launch(headless = true): Promise<Browser> {
    try {
      return await chromium.launch({
        headless,
        ...(this.channel !== 'chromium' ? { channel: this.channel } : {}),
      });
    } catch {
      throw new Error(
        '无法启动浏览器。请安装 Chrome，或运行 npm run browser:install 并设置 BROWSER_CHANNEL=chromium。',
      );
    }
  }
  async getBrowser() {
    if (!this.browser)
      this.browser = this.launch().catch((error) => {
        this.browser = undefined;
        throw error;
      });
    return this.browser;
  }
  async context(
    origins: string[],
    headed = false,
    recording = false,
  ): Promise<{ context: BrowserContext; page: Page; close: () => Promise<void> }> {
    const browser = headed ? await this.launch(false) : await this.getBrowser();
    const statePath = process.env.BROWSER_STORAGE_STATE;
    let storageState: Awaited<ReturnType<BrowserContext['storageState']>> | undefined;
    if (statePath && existsSync(statePath)) {
      const state = JSON.parse(readFileSync(statePath, 'utf8')) as Awaited<
        ReturnType<BrowserContext['storageState']>
      >;
      const hosts = origins.map((origin) => new URL(origin).hostname);
      // Import only explicitly relevant origin state into each isolated context.
      storageState = {
        cookies: state.cookies.filter((cookie) =>
          hosts.some(
            (host) =>
              host === cookie.domain.replace(/^\./, '') ||
              host.endsWith(`.${cookie.domain.replace(/^\./, '')}`),
          ),
        ),
        origins: state.origins.filter((origin) => origins.includes(origin.origin)),
      };
    }
    const context = await browser.newContext({
      viewport: { width: 1200, height: 850 },
      acceptDownloads: false,
      serviceWorkers: 'block',
      storageState,
    });
    await context.route('**/*', (route) => {
      const request = route.request();
      if (request.isNavigationRequest()) {
        try {
          validateUrl(request.url(), origins);
        } catch {
          return route.abort('blockedbyclient');
        }
      }
      return route.continue();
    });
    await context.addInitScript({
      content: `window.__skillcua_recording=${recording};\n${this.recorder}`,
    });
    const page = await context.newPage();
    page.on('dialog', (dialog) => {
      void dialog.dismiss();
    });
    context.on('page', (popup) => {
      if (popup !== page) void popup.close();
    });
    return {
      context,
      page,
      close: async () => {
        await context.close();
        if (headed) await browser.close();
      },
    };
  }
  async observe(page: Page): Promise<Observation> {
    return page.evaluate(() =>
      (window as unknown as { SkillCUA: { snapshot: () => Observation } }).SkillCUA.snapshot(),
    );
  }
  locator(page: Page, target: Target) {
    return page.getByRole(target.role, { name: target.name, exact: true });
  }
  async record(
    startUrl: string,
    origins: string[],
    onAction: (action: RawAction) => void,
    headless = false,
  ) {
    const session = await this.context(origins, !headless, true);
    await session.context.exposeBinding('__skillcua_emit', ({ frame }, event: unknown) => {
      if (frame !== session.page.mainFrame()) return;
      const parsed = rawActionSchema.safeParse(event);
      if (!parsed.success || (parsed.data.target && sensitive(parsed.data.target.name))) return;
      validateUrl(parsed.data.url, origins);
      onAction(parsed.data);
    });
    try {
      await session.page.goto(startUrl, { waitUntil: 'domcontentloaded' });
      return session;
    } catch (error) {
      await session.close();
      throw error;
    }
  }
  async close() {
    if (this.browser) await (await this.browser).close();
  }
}
