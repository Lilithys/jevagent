import { describe, it, expect, afterEach } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { extractSkill, validateUrl } from '../../server/learning.js';
import { embed, cosine, retrieve, repairCandidates } from '../../server/semantic.js';
import { Policy } from '../../server/policy.js';
import { Store } from '../../server/store.js';
import { exampleSkills } from '../../server/seed.js';
import { type Demonstration } from '../../shared/types.js';

const origin = 'http://127.0.0.1:3210';
function demo(): Demonstration {
  return {
    id: 'demo',
    name: '我的周报',
    task: '生成项目周报',
    app: 'notion',
    startUrl: `${origin}/lab/notion`,
    mode: 'lab',
    status: 'recording',
    createdAt: new Date().toISOString(),
    actions: [
      {
        kind: 'click',
        target: { role: 'button', name: 'Weekly report template' },
        url: `${origin}/lab/notion`,
        timestamp: 1,
      },
      {
        kind: 'fill',
        target: { role: 'textbox', name: 'Report title' },
        value: 'W',
        url: `${origin}/lab/notion`,
        timestamp: 2,
      },
      {
        kind: 'fill',
        target: { role: 'textbox', name: 'Report title' },
        value: 'Weekly update',
        url: `${origin}/lab/notion`,
        timestamp: 3,
      },
      {
        kind: 'fill',
        target: { role: 'textbox', name: 'Report content' },
        value: 'Some progress',
        url: `${origin}/lab/notion`,
        timestamp: 4,
      },
      {
        kind: 'click',
        target: { role: 'button', name: 'Submit' },
        url: `${origin}/lab/notion`,
        timestamp: 5,
      },
    ],
  };
}
describe('demonstration learning', () => {
  it('coalesces typing into semantic steps and parameterizes values', () => {
    const skill = extractSkill(demo(), 'Report published successfully');
    expect(skill.workflow).toHaveLength(5);
    expect(skill.workflow[0].kind).toBe('navigate');
    expect(skill.parameters).toEqual([
      { key: 'report_title', label: 'Report title', defaultValue: 'Weekly update', required: true },
      {
        key: 'report_content',
        label: 'Report content',
        defaultValue: 'Some progress',
        required: true,
      },
    ]);
    expect(JSON.stringify(skill.workflow)).not.toContain('Weekly update');
  });
  it('does not collapse edits separated by meaningful actions', () => {
    const d = demo();
    d.actions.push(d.actions[2]);
    const skill = extractSkill(d, 'Done');
    expect(skill.parameters.map((p) => p.key)).toContain('report_title_2');
  });
  it('rejects empty demonstrations and missing result criteria', () => {
    expect(() => extractSkill({ ...demo(), actions: [] }, 'Done')).toThrow('有效操作');
    expect(() => extractSkill(demo(), ' ')).toThrow('验证文本');
  });
  it('never persists recognized sensitive input fields', () => {
    const d = demo();
    d.actions.push({
      kind: 'fill',
      target: { role: 'textbox', name: 'API key' },
      value: 'a-secret',
      url: origin,
      timestamp: 10,
    });
    expect(JSON.stringify(extractSkill(d, 'Done'))).not.toContain('a-secret');
  });
  it('requires semantic targets for non-navigation actions', () => {
    const d = demo();
    d.actions.push({ kind: 'click', url: origin, timestamp: 9 });
    expect(() => extractSkill(d, 'Done')).toThrow('语义目标');
  });
});
describe('retrieval and personalization', () => {
  const skills = exampleSkills(origin);
  it.each([
    ['帮我完成本周的项目周报', 'notion'],
    ['Create a GitHub bug issue', 'github'],
    ['在 Jira 创建工单', 'jira'],
  ])('retrieves %s', (task, expected) =>
    expect(retrieve(task, skills)[0].skill.app).toBe(expected),
  );
  it('embeddings are normalized and deterministic', () => {
    expect(embed('weekly report')).toEqual(embed('weekly report'));
    expect(cosine(embed('weekly report'), embed('weekly report'))).toBeCloseTo(1);
  });
  it('does not let unrelated preferences overwhelm an explicit task', () => {
    expect(retrieve('create github issue', skills, { notion: 10000 })[0].skill.app).toBe('github');
  });
  it('abstains on unrelated goals instead of inventing a plan', async () => {
    const policy = new Policy('');
    expect(
      (await policy.select('预订明天去巴黎的机票', retrieve('预订明天去巴黎的机票', skills)))
        .choice,
    ).toBe('ask');
  });
});
describe('repair boundaries', () => {
  it('finds a same-role synonym but excludes destructive and disabled controls', () => {
    const result = repairCandidates({ role: 'button', name: 'Submit' }, [
      { role: 'button', name: 'Publish', disabled: false },
      { role: 'link', name: 'Submit', disabled: false },
      { role: 'button', name: 'Delete', disabled: false },
      { role: 'button', name: 'Send', disabled: true },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0].element.name).toBe('Publish');
  });
  it('preserves equally plausible candidates so the executor can abstain', () => {
    const result = repairCandidates({ role: 'button', name: 'Submit' }, [
      { role: 'button', name: 'Publish', disabled: false },
      { role: 'button', name: 'Send', disabled: false },
    ]);
    expect(result[0].score).toBe(result[1].score);
  });
});
describe('origin checks', () => {
  it('accepts only exact allowed http origins', () => {
    expect(validateUrl(`${origin}/lab/notion`, [origin]).origin).toBe(origin);
    for (const url of [
      'file:///etc/passwd',
      'javascript:alert(1)',
      `${origin}.evil.test/`,
      'http://user:pass@127.0.0.1:3210/',
      'http://127.0.0.1:8000/',
    ])
      expect(() => validateUrl(url, [origin])).toThrow();
  });
});
describe('Jev typed policy contract', () => {
  const options = [
    { id: 'execute', label: 'Execute', score: 1 },
    { id: 'ask', label: 'Ask', score: 0 },
  ];
  it('uses the official choice request and validates the returned option', async () => {
    let payload: Record<string, unknown> = {};
    const request = async (_url: unknown, init: RequestInit) => {
      payload = JSON.parse(init.body as string);
      return new Response(
        JSON.stringify({ answers: { decision: { choice: 'execute', confidence: 0.96 } } }),
      );
    };
    const decision = await new Policy('test-only', request as typeof fetch).choose(
      'action',
      'state',
      options,
      'execute',
      'local',
    );
    expect(decision.provider).toBe('jev');
    expect(decision.choice).toBe('execute');
    expect(payload.questions).toEqual({
      decision: expect.objectContaining({
        type: 'choice',
        criteria: { execute: 'Execute', ask: 'Ask' },
      }),
    });
  });
  it.each([
    { choice: 'unknown', confidence: 1 },
    { choice: 'execute', confidence: 0.1 },
    { choice: 'execute', confidence: 7 },
    { choice: 'execute' },
  ])('stops on invalid or uncertain responses: %j', async (answer) => {
    const request = async () => new Response(JSON.stringify({ answers: { decision: answer } }));
    expect(
      (
        await new Policy('test-only', request as typeof fetch).choose(
          'action',
          'state',
          options,
          'execute',
          'local',
        )
      ).choice,
    ).toBe('ask');
  });
  it('stops on provider outages instead of silently switching policies', async () => {
    const request = async () => {
      throw new Error('timeout');
    };
    const result = await new Policy('test-only', request as typeof fetch).choose(
      'repair',
      'state',
      options,
      'execute',
      'local',
    );
    expect(result.choice).toBe('ask');
    expect(result.provider).toBe('jev');
    expect(result.reason).toContain('timeout');
  });
});
describe('durable skill memory', () => {
  const cleanup: string[] = [];
  afterEach(() => {
    cleanup.splice(0).forEach((path) => rmSync(path, { force: true, recursive: true }));
  });
  it('persists versions and preferences through restart', () => {
    const dir = mkdtempSync(join(tmpdir(), 'skillcua-'));
    cleanup.push(dir);
    const path = join(dir, 'test.sqlite');
    const store = new Store(path);
    const skill = exampleSkills(origin)[0];
    store.put('skill', skill);
    store.put('skill', { ...skill, version: 2 });
    store.preference('github');
    store.close();
    const reopened = new Store(path);
    expect(reopened.versions(skill.id).map((s) => s.version)).toEqual([2, 1]);
    expect(reopened.preferences()).toEqual({ github: 1 });
    reopened.close();
  });
  it('rolls back partial writes', () => {
    const store = new Store(':memory:');
    expect(() =>
      store.transaction(() => {
        store.put('skill', exampleSkills(origin)[0]);
        throw new Error('rollback');
      }),
    ).toThrow();
    expect(store.list('skill')).toHaveLength(0);
    store.close();
  });
  it('does not fabricate metrics for an unused workspace', () => {
    const store = new Store(':memory:');
    expect(store.stats()).toMatchObject({
      total: 0,
      successRate: null,
      reuseRate: null,
      stepsReduction: null,
    });
    store.close();
  });
});
