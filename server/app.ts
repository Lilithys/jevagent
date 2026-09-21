import express, { type Request, type Response, type NextFunction } from 'express';
import { z } from 'zod';
import { randomUUID } from 'node:crypto';
import { join, resolve } from 'node:path';
import {
  appSchema,
  rawActionSchema,
  now,
  labApps,
  type Demonstration,
  type Decision,
} from '../shared/types.js';
import { Store } from './store.js';
import { seed } from './seed.js';
import { BrowserRuntime } from './browser.js';
import { Policy } from './policy.js';
import { Engine } from './engine.js';
import { extractSkill, validateUrl, sensitive } from './learning.js';
import { retrieve } from './semantic.js';

export function createApp(options: { dataDir: string; baseUrl: string; apiKey?: string }) {
  const { dataDir, baseUrl } = options;
  const store = new Store(join(dataDir, 'skillcua.sqlite'));
  seed(store, baseUrl);
  const browser = new BrowserRuntime(),
    policy = new Policy(options.apiKey);
  const origins = [
    ...new Set([
      baseUrl,
      ...(process.env.ALLOWED_ORIGINS || '')
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
    ]),
  ];
  const engine = new Engine(store, browser, policy, baseUrl, dataDir, origins);
  const sessions = new Map<string, Awaited<ReturnType<BrowserRuntime['record']>>>();
  const app = express();
  app.disable('x-powered-by');
  app.use((req, res, next) => {
    const origin = req.headers.origin;
    if (req.headers.host !== new URL(baseUrl).host || (origin && origin !== baseUrl)) {
      res.status(403).json({ error: '仅允许本机同源访问。请使用 ' + baseUrl });
      return;
    }
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('X-Frame-Options', 'SAMEORIGIN');
    if (req.path.startsWith('/api')) res.setHeader('Cache-Control', 'no-store');
    next();
  });
  app.use(express.json({ limit: '1mb' }));
  const requireEntity = <K extends 'skill' | 'run' | 'demonstration' | 'evaluation'>(
    kind: K,
    id: string,
  ) => {
    const value = store.get(kind, id);
    if (!value) throw Object.assign(new Error('记录不存在。'), { status: 404 });
    return value;
  };
  app.get('/api/health', (_req, res) => res.json({ ok: true, service: 'SkillCUA' }));
  app.get('/api/state', (_req, res) =>
    res.json({
      skills: store.list('skill'),
      runs: store
        .list('run')
        .filter((r) => !r.evaluationId)
        .slice(0, 60),
      demonstrations: store.list('demonstration').slice(0, 40),
      evaluations: store.list('evaluation').slice(0, 10),
      preferences: store.preferences(),
      stats: store.stats(),
      config: {
        policy: policy.provider,
        allowedOrigins: origins,
        browserChannel: browser.channel,
        authConfigured: Boolean(process.env.BROWSER_STORAGE_STATE),
      },
    }),
  );
  app.get('/api/skills/:id', (req, res) => res.json(requireEntity('skill', req.params.id)));
  app.get('/api/skills/:id/versions', (req, res) => res.json(store.versions(req.params.id)));
  app.post('/api/skills/:id/restore', (req, res) => {
    const current = requireEntity('skill', req.params.id);
    const { version } = z.object({ version: z.number().int().positive() }).parse(req.body);
    const source = store.versions(current.id).find((s) => s.version === version);
    if (!source) throw new Error('该版本不存在。');
    if (
      store
        .list('run')
        .some((r) => r.skillId === current.id && ['queued', 'running'].includes(r.status))
    )
      throw new Error('请等待此 Skill 的执行结束后再恢复版本。');
    res.json(
      store.put('skill', {
        ...current,
        workflow: source.workflow,
        version: current.version + 1,
        updatedAt: now(),
      }),
    );
  });
  app.post('/api/retrieve', async (req, res) => {
    const { task } = z.object({ task: z.string().trim().min(1).max(2000) }).parse(req.body);
    const candidates = retrieve(task, store.list('skill'), store.preferences());
    res.json({
      candidates: candidates.slice(0, 5),
      decision: await policy.select(task, candidates),
    });
  });
  const demoInput = z.object({
    name: z.string().trim().min(1).max(120),
    task: z.string().trim().min(1).max(2000),
    app: appSchema,
    mode: z.enum(['lab', 'browser']),
    startUrl: z.string().url().optional(),
  });
  function append(id: string, action: z.infer<typeof rawActionSchema>) {
    const demo = requireEntity('demonstration', id);
    if (demo.status !== 'recording') throw new Error('此教学已结束。');
    if (demo.actions.length >= 5000) throw new Error('单次录制最多 5000 个事件，请结束本次示范。');
    validateUrl(action.url, [new URL(demo.startUrl).origin]);
    if (action.target && sensitive(action.target.name)) return;
    demo.actions.push(action);
    store.put('demonstration', demo);
  }
  app.post('/api/demonstrations', async (req, res) => {
    const input = demoInput.parse(req.body);
    if (input.mode === 'lab' && input.app === 'custom') throw new Error('请选择一个练习应用。');
    const startUrl = input.mode === 'lab' ? `${baseUrl}/lab/${input.app}` : input.startUrl;
    if (!startUrl) throw new Error('请输入目标网页地址。');
    validateUrl(startUrl, origins);
    const demo: Demonstration = {
      ...input,
      startUrl,
      id: randomUUID(),
      status: 'recording',
      createdAt: now(),
      actions: [{ kind: 'navigate', url: startUrl, timestamp: Date.now() }],
    };
    store.put('demonstration', demo);
    if (input.mode === 'browser') {
      try {
        sessions.set(
          demo.id,
          await browser.record(startUrl, [new URL(startUrl).origin], (action) =>
            append(demo.id, action),
          ),
        );
      } catch (error) {
        store.put('demonstration', { ...demo, status: 'cancelled' });
        throw error;
      }
    }
    res.status(201).json(demo);
  });
  app.post('/api/demonstrations/:id/actions', (req, res) => {
    const demo = requireEntity('demonstration', req.params.id);
    if (demo.mode !== 'lab') throw new Error('浏览器录制不接受外部事件。');
    const action = rawActionSchema.parse(req.body);
    if (new URL(action.url).pathname !== `/lab/${demo.app}`)
      throw new Error('录制事件不属于当前练习页面。');
    append(demo.id, action);
    res.json({ ok: true });
  });
  app.post('/api/demonstrations/:id/finish', async (req, res) => {
    const { postcondition } = z
      .object({ postcondition: z.string().trim().min(1).max(300) })
      .parse(req.body);
    const demo = requireEntity('demonstration', req.params.id);
    if (demo.status !== 'recording') throw new Error('此教学已结束。');
    const session = sessions.get(demo.id);
    if (
      session &&
      !(await session.page.getByText(postcondition, { exact: true }).first().isVisible())
    )
      throw new Error('当前页面没有出现指定的完成文本，请先完成示范。');
    const skill = extractSkill(demo, postcondition);
    store.transaction(() => {
      store.put('skill', skill);
      store.put('demonstration', { ...demo, status: 'learned', skillId: skill.id });
    });
    await session?.close().catch(() => {});
    sessions.delete(demo.id);
    res.status(201).json(skill);
  });
  app.post('/api/demonstrations/:id/cancel', async (req, res) => {
    const demo = requireEntity('demonstration', req.params.id);
    if (demo.status === 'recording') store.put('demonstration', { ...demo, status: 'cancelled' });
    await sessions
      .get(demo.id)
      ?.close()
      .catch(() => {});
    sessions.delete(demo.id);
    res.json({ ok: true });
  });
  app.get('/api/runs/:id', (req, res) => res.json(requireEntity('run', req.params.id)));
  app.get('/api/runs/:id/screenshot', (req, res) => {
    const run = requireEntity('run', req.params.id);
    if (!run.screenshot) {
      res.status(404).json({ error: '截图尚未生成。' });
      return;
    }
    res.sendFile(resolve(dataDir, 'screenshots', `${run.id}.png`));
  });
  const runInput = z.object({
    task: z.string().trim().min(1).max(2000),
    skillId: z.string().min(1),
    parameters: z.record(z.string().max(20000)).default({}),
    variant: z.enum(['original', 'renamed', 'layout', 'ambiguous']).default('original'),
    repairEnabled: z.boolean().default(true),
    approved: z.boolean().default(false),
  });
  app.post('/api/runs', (req, res) => {
    const input = runInput.parse(req.body),
      skill = requireEntity('skill', input.skillId);
    if (store.list('run').filter((r) => ['queued', 'running'].includes(r.status)).length >= 20)
      throw new Error('队列已满，请等待当前执行完成。');
    const decision: Decision = {
      kind: 'skill',
      provider: 'local',
      choice: skill.id,
      confidence: 1,
      reason: '用户审阅并选择了该 Skill。',
      options: [{ id: skill.id, label: skill.name, score: 1 }],
      latencyMs: 0,
    };
    const { run, done } = engine.create(skill, input, decision);
    void done.catch(() => {});
    res.status(202).json(run);
  });
  app.post('/api/runs/:id/cancel', async (req, res) => {
    await engine.cancel(req.params.id);
    res.json({ ok: true });
  });
  app.post('/api/evaluations', (_req, res) => res.status(202).json(engine.evaluate()));
  app.get('/api/evaluations/:id', (req, res) =>
    res.json(requireEntity('evaluation', req.params.id)),
  );
  app.get('/lab/:app', (req, res) => {
    if (!Object.hasOwn(labApps, req.params.app)) {
      res.status(404).send('Unknown lab');
      return;
    }
    res
      .type('html')
      .send(
        labHtml(req.params.app as keyof typeof labApps, String(req.query.variant || 'original')),
      );
  });
  app.use(express.static(resolve('public')));
  app.use('/api', (_req, res) => res.status(404).json({ error: 'API 不存在。' }));
  app.use((error: unknown, _req: Request, res: Response, _next: NextFunction) => {
    if (error instanceof z.ZodError) {
      res.status(400).json({
        error:
          '输入不符合格式：' +
          error.issues.map((e) => `${e.path.join('.')}: ${e.message}`).join('; '),
      });
      return;
    }
    const typed = error as Error & { status?: number };
    res.status(typed.status || 400).json({ error: typed.message || '请求失败。' });
  });
  return {
    app,
    store,
    engine,
    browser,
    close: async () => {
      for (const session of sessions.values()) await session.close().catch(() => {});
      await browser.close();
      store.close();
    },
  };
}
import { labHtml } from './labs.js';
