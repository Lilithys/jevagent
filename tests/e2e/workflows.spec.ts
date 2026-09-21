import { test, expect, type APIRequestContext } from '@playwright/test';
import type { Run, Skill } from '../../shared/types.js';
import { BrowserRuntime } from '../../server/browser.js';
import type { RawAction } from '../../shared/types.js';

async function waitRun(request: APIRequestContext, id: string): Promise<Run> {
  let run: Run;
  await expect
    .poll(
      async () => {
        run = await (await request.get(`/api/runs/${id}`)).json();
        return run.status;
      },
      { timeout: 40000 },
    )
    .not.toMatch(/queued|running/);
  return run!;
}
async function runSkill(
  request: APIRequestContext,
  skillId: string,
  variant = 'original',
  repairEnabled = true,
  parameters = {},
) {
  const response = await request.post('/api/runs', {
    data: { task: 'Run integration workflow', skillId, variant, repairEnabled, parameters },
  });
  expect(response.status()).toBe(202);
  return waitRun(request, (await response.json()).id);
}
test('overview renders meaningful empty metrics and works on mobile', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/');
  await expect(page.getByText('每次示范，都让下一次更简单。')).toBeVisible();
  await expect(page.getByRole('button', { name: /生成 Notion 周报/ })).toBeVisible();
  await page.screenshot({ path: 'test-results/overview-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/overview-mobile.png', fullPage: true });
  expect(errors).toEqual([]);
});
test('all three original example workflows really execute and verify', async ({ request }) => {
  for (const app of ['github', 'jira', 'notion']) {
    const run = await runSkill(request, `example-${app}`);
    expect(run.status, run.error).toBe('succeeded');
    expect(run.verified).toBe(true);
    expect(run.screenshot).toBeTruthy();
    expect(run.steps.every((s) => s.status === 'succeeded')).toBe(true);
  }
});
test('button rename fails in baseline, repairs in adaptive mode, persists revision', async ({
  request,
}) => {
  const initial: Skill = await (await request.get('/api/skills/example-notion')).json();
  // Restore the original version to make this test repeatable across persisted test runs.
  if (initial.version > 1)
    await request.post('/api/skills/example-notion/restore', { data: { version: 1 } });
  const baseline = await runSkill(request, 'example-notion', 'renamed', false);
  expect(baseline.status).toBe('failed');
  expect(baseline.verified).toBe(false);
  const adaptive = await runSkill(request, 'example-notion', 'renamed');
  expect(adaptive.status, adaptive.error).toBe('succeeded');
  expect(adaptive.repairs).toBe(1);
  const skill: Skill = await (await request.get('/api/skills/example-notion')).json();
  expect(skill.version).toBe(adaptive.skillVersion + 1);
  expect(skill.workflow.at(-1)?.target?.name).toBe('Publish');
  const reused = await runSkill(request, skill.id, 'renamed');
  expect(reused.repairs).toBe(0);
  expect(reused.status).toBe('succeeded');
  const versions: Skill[] = await (await request.get(`/api/skills/${skill.id}/versions`)).json();
  expect(versions.length).toBeGreaterThan(1);
});
test('ambiguous buttons stop without creating a repaired version', async ({ request }) => {
  await request.post('/api/skills/example-notion/restore', { data: { version: 1 } });
  const before: Skill = await (await request.get('/api/skills/example-notion')).json();
  const run = await runSkill(request, 'example-notion', 'ambiguous');
  expect(run.status).toBe('failed');
  expect(run.steps.at(-1)?.decision?.choice).toBe('ask');
  const after: Skill = await (await request.get('/api/skills/example-notion')).json();
  expect(after.version).toBe(before.version);
});
test('layout changes preserve semantic execution', async ({ request }) => {
  const run = await runSkill(request, 'example-github', 'layout');
  expect(run.status, run.error).toBe('succeeded');
  expect(run.repairs).toBe(0);
});
test('teaching captures actual user DOM events, extracts parameters and reuses new content', async ({
  page,
  request,
}) => {
  await page.goto('/');
  await page.getByRole('button', { name: '教学模式', exact: true }).click();
  await page.getByRole('textbox', { name: '技能名称', exact: true }).fill('我的个性化周报');
  await page.getByRole('button', { name: '开始教学' }).click();
  const frame = page.frameLocator('iframe[title="教学练习页面"]');
  await frame.getByRole('button', { name: 'Weekly report template' }).click();
  await frame
    .getByRole('textbox', { name: 'Report title', exact: true })
    .pressSequentially('Original title', { delay: 10 });
  await frame
    .getByRole('textbox', { name: 'Report content', exact: true })
    .fill('Original content');
  await frame.getByRole('button', { name: 'Submit', exact: true }).click();
  await expect(frame.getByRole('status')).toHaveText('Report published successfully');
  await page.getByRole('button', { name: '完成示范并提取技能' }).click();
  await expect(
    page.getByRole('heading', { name: '我的个性化周报', exact: true, level: 2 }),
  ).toBeVisible();
  const state = await (await request.get('/api/state')).json();
  const skill = state.skills.find((s: Skill) => s.name === '我的个性化周报') as Skill;
  expect(skill.source).toBe('demonstration');
  expect(skill.rawActionCount).toBeGreaterThan(skill.workflow.length);
  expect(skill.parameters.map((p) => p.key)).toEqual(['report_title', 'report_content']);
  const run = await runSkill(request, skill.id, 'renamed', true, {
    report_title: 'A new week',
    report_content: 'A different project update',
  });
  expect(run.verified, run.error).toBe(true);
  expect(run.repairs).toBe(1);
  await page.screenshot({ path: 'test-results/learned-skill.png', fullPage: true });
});
test('UI can retrieve, edit parameters and launch an observable run', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '工作台', exact: true }).click();
  await page.getByRole('textbox', { name: '这次想完成什么？' }).fill('create a github issue');
  await page.getByRole('button', { name: '检索技能', exact: true }).click();
  await expect(page.getByText(/已找到匹配技能 · 创建 GitHub Issue/)).toBeVisible();
  await page.getByRole('textbox', { name: /Issue title/ }).fill('New integration issue');
  await page.getByRole('button', { name: '确认并执行工作流' }).click();
  await expect(page.getByText('已验证 · 完成条件已通过')).toBeVisible({ timeout: 40000 });
  await page.screenshot({ path: 'test-results/execution-trace.png', fullPage: true });
});
test('API rejects foreign origins, invalid URLs, missing fields and nonexistent IDs', async ({
  request,
}) => {
  expect(
    (
      await request.post('/api/retrieve', {
        headers: { Origin: 'https://evil.example' },
        data: { task: 'weekly report' },
      })
    ).status(),
  ).toBe(403);
  expect(
    (
      await request.post('/api/demonstrations', {
        data: {
          name: 'x',
          task: 'x',
          app: 'custom',
          mode: 'browser',
          startUrl: 'http://example.com',
        },
      })
    ).status(),
  ).toBe(400);
  expect((await request.post('/api/runs', { data: {} })).status()).toBe(400);
  expect((await request.get('/api/skills/not-found')).status()).toBe(404);
});
test('browser recorder captures semantic select values and excludes passwords', async () => {
  const runtime = new BrowserRuntime();
  const actions: RawAction[] = [];
  const session = await runtime.record(
    'http://127.0.0.1:3211/lab/jira',
    ['http://127.0.0.1:3211'],
    (action) => actions.push(action),
    true,
  );
  try {
    await session.page.getByRole('button', { name: 'Create ticket', exact: true }).click();
    await session.page
      .getByRole('textbox', { name: 'Summary', exact: true })
      .fill('Recorded ticket');
    await session.page
      .getByRole('combobox', { name: 'Priority', exact: true })
      .selectOption('High');
    await session.page.evaluate(() => {
      const label = document.createElement('label');
      label.textContent = 'Password';
      const input = document.createElement('input');
      input.type = 'password';
      label.append(input);
      document.body.append(label);
    });
    await session.page.getByLabel('Password', { exact: true }).fill('not-to-be-stored');
    await expect.poll(() => actions.length).toBe(3);
    expect(actions[2]).toMatchObject({
      kind: 'select',
      target: { role: 'combobox', name: 'Priority' },
      value: 'High',
    });
    expect(JSON.stringify(actions)).not.toContain('not-to-be-stored');
    const observation = await runtime.observe(session.page);
    expect(observation.elements.some((e) => e.name === 'Password')).toBe(false);
    expect(JSON.stringify(observation)).not.toContain('Recorded ticket');
  } finally {
    await session.close();
    await runtime.close();
  }
});
test('a failed completion check never commits a tentative repair', async ({ request }) => {
  const start = await request.post('/api/demonstrations', {
    data: { app: 'notion', name: 'Unverified repair test', task: 'weekly report', mode: 'lab' },
  });
  const demo = await start.json();
  const source: Skill = await (await request.get('/api/skills/example-notion')).json();
  const steps = [
    { kind: 'click', target: { role: 'button', name: 'Weekly report template' } },
    { kind: 'fill', target: { role: 'textbox', name: 'Report title' }, value: 'Title' },
    { kind: 'fill', target: { role: 'textbox', name: 'Report content' }, value: 'Body' },
    { kind: 'click', target: { role: 'button', name: 'Submit' } },
  ];
  for (const step of steps)
    await request.post(`/api/demonstrations/${demo.id}/actions`, {
      data: { ...step, url: source.startUrl, timestamp: Date.now() },
    });
  const learned: Skill = await (
    await request.post(`/api/demonstrations/${demo.id}/finish`, {
      data: { postcondition: 'This success text never appears' },
    })
  ).json();
  const run = await runSkill(request, learned.id, 'renamed');
  expect(run.status).toBe('failed');
  expect(run.repairs).toBe(1);
  expect(run.verified).toBe(false);
  const unchanged: Skill = await (await request.get(`/api/skills/${learned.id}`)).json();
  expect(unchanged.version).toBe(1);
  expect(unchanged.workflow.at(-1)?.target?.name).toBe('Submit');
});
