import { randomUUID } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import type { Page } from 'playwright';
import {
  now,
  type Skill,
  type Run,
  type Decision,
  type Target,
  type Evaluation,
} from '../shared/types.js';
import type { Store } from './store.js';
import { BrowserRuntime } from './browser.js';
import { Policy } from './policy.js';
import { repairCandidates } from './semantic.js';
import { validateUrl } from './learning.js';
import { exampleSkills } from './seed.js';

export type RunInput = {
  task: string;
  parameters: Record<string, string>;
  variant: Run['variant'];
  repairEnabled: boolean;
  approved: boolean;
};
export class Engine {
  private queue: Promise<unknown> = Promise.resolve();
  private cancelled = new Set<string>();
  private closers = new Map<string, () => Promise<void>>();
  constructor(
    public store: Store,
    public browser: BrowserRuntime,
    public policy: Policy,
    public baseUrl: string,
    private dataDir: string,
    private origins: string[],
  ) {}
  create(
    skill: Skill,
    input: RunInput,
    decision: Decision,
    evaluationId?: string,
  ): { run: Run; done: Promise<Run> } {
    validateUrl(skill.startUrl, this.origins);
    if (skill.origin !== new URL(skill.startUrl).origin)
      throw new Error('Skill origin 与起始地址不匹配。');
    const isLab =
      skill.origin === this.baseUrl &&
      /^\/lab\/(github|jira|notion)$/.test(new URL(skill.startUrl).pathname);
    if (!isLab && !input.approved) throw new Error('真实网页执行需要先审阅参数并确认。');
    if (!isLab && input.variant !== 'original') throw new Error('页面变体仅用于本地练习环境。');
    const parameters: Record<string, string> = {};
    for (const parameter of skill.parameters) {
      parameters[parameter.key] = input.parameters[parameter.key] ?? parameter.defaultValue;
      if (parameter.required && !parameters[parameter.key]?.trim())
        throw new Error(`缺少参数：${parameter.label}`);
    }
    const run: Run = {
      id: randomUUID(),
      task: input.task,
      skillId: skill.id,
      skillName: skill.name,
      skillVersion: skill.version,
      app: skill.app,
      createdAt: now(),
      status: 'queued',
      parameters,
      variant: input.variant,
      repairEnabled: input.repairEnabled,
      repairs: 0,
      reused: false,
      decision,
      steps: [],
      verified: false,
      evaluationId,
    };
    this.store.put('run', run);
    const done = this.queue.then(() => this.execute(run, structuredClone(skill), isLab));
    this.queue = done.catch(() => {});
    return { run, done };
  }
  async cancel(id: string) {
    const run = this.store.get('run', id);
    if (!run) throw new Error('找不到执行记录。');
    if (!['queued', 'running'].includes(run.status)) return;
    this.cancelled.add(id);
    await this.closers.get(id)?.();
    if (run.status === 'queued')
      this.store.put('run', { ...run, status: 'cancelled', finishedAt: now() });
  }
  private async execute(run: Run, skill: Skill, isLab: boolean): Promise<Run> {
    const started = Date.now();
    let page: Page | undefined;
    let close: (() => Promise<void>) | undefined;
    const save = () => this.store.put('run', run);
    try {
      if (this.cancelled.has(run.id)) throw new Error('执行已取消。');
      run.status = 'running';
      run.reused = (this.store.get('skill', skill.id)?.attempts ?? 0) > 0;
      save();
      const session = await this.browser.context([skill.origin]);
      page = session.page;
      close = session.close;
      this.closers.set(run.id, close);
      let preconditionChecked = false;
      const workingPolicy = run.evaluationId ? new Policy('') : this.policy;
      for (const [index, step] of skill.workflow.entries()) {
        if (this.cancelled.has(run.id)) throw new Error('执行已取消。');
        const trace: Run['steps'][number] = {
          index,
          description: step.description,
          status: 'running',
          startedAt: now(),
        };
        const stepStart = Date.now();
        run.steps.push(trace);
        save();
        try {
          if (step.kind === 'navigate') {
            const url = validateUrl(step.url!, [skill.origin]);
            if (isLab) {
              url.searchParams.delete('record');
              url.searchParams.set('variant', run.variant);
            }
            await page.goto(url.toString(), { waitUntil: 'domcontentloaded', timeout: 20000 });
            if (!preconditionChecked) {
              if (
                await page
                  .getByText(skill.postcondition, { exact: true })
                  .isVisible()
                  .catch(() => false)
              )
                throw new Error('完成标志在执行前已经存在，无法验证本次任务。');
              preconditionChecked = true;
            }
          } else {
            validateUrl(page.url(), [skill.origin]);
            trace.before = await this.browser.observe(page);
            let target = step.target!;
            let locator = this.browser.locator(page, target);
            await locator.waitFor({ state: 'visible', timeout: 1200 }).catch(() => {});
            const count = await locator.count();
            if (count !== 1) {
              if (!run.repairEnabled)
                throw new Error(`目标未唯一匹配：${target.name} (${count})；基线不启用修复。`);
              const observation = await this.browser.observe(page);
              const candidates = repairCandidates(target, observation.elements);
              if (
                count > 1 ||
                !candidates[0] ||
                (candidates[1] && candidates[0].score - candidates[1].score < 0.1)
              ) {
                trace.decision = {
                  kind: 'repair',
                  provider: 'local',
                  choice: 'ask',
                  confidence: 0,
                  options: candidates.map((c, i) => ({
                    id: `target_${i}`,
                    label: c.element.name,
                    score: c.score,
                  })),
                  latencyMs: 0,
                  reason: '目标缺失或候选有歧义；停止执行，等待新的示范。',
                };
                throw new Error('无法安全修复：目标缺失或存在多个相似候选，请重新示范。');
              }
              const best = candidates[0];
              trace.decision = await workingPolicy.choose(
                'repair',
                `Expected ${target.role}: ${target.name}`,
                [
                  {
                    id: 'repair',
                    label: `Use ${best.element.role}: ${best.element.name}`,
                    score: best.score,
                  },
                  { id: 'ask', label: 'Stop and ask for a new demonstration', score: 0 },
                ],
                'repair',
                '同角色语义匹配达到阈值，且没有相近的其他候选。',
              );
              if (trace.decision.choice !== 'repair') throw new Error(trace.decision.reason);
              const replacement: Target = { role: best.element.role, name: best.element.name };
              trace.repair = { from: target, to: replacement, score: best.score };
              target = replacement;
              locator = this.browser.locator(page, target);
              if ((await locator.count()) !== 1) throw new Error('修复目标在重新观察后不再唯一。');
              step.target = target;
              step.description = step.description.replace(trace.repair.from.name, target.name);
              run.repairs += 1;
            } else {
              trace.decision = await workingPolicy.choose(
                'action',
                `Workflow step: ${step.description}. Exact visible match: ${target.role}: ${target.name}`,
                [
                  { id: 'execute', label: step.description, score: 1 },
                  { id: 'ask', label: 'Stop and ask for guidance', score: 0 },
                ],
                'execute',
                '语义角色与名称精确匹配。',
              );
              if (trace.decision.choice !== 'execute') throw new Error(trace.decision.reason);
            }
            if (step.kind === 'click') await locator.click({ timeout: 5000 });
            else if (step.kind === 'fill')
              await locator.fill(run.parameters[step.parameter!] ?? '', { timeout: 5000 });
            else if (step.kind === 'select')
              await locator.selectOption(run.parameters[step.parameter!] ?? '', { timeout: 5000 });
            else if (step.kind === 'check')
              await locator.setChecked(step.checked ?? true, { timeout: 5000 });
          }
          validateUrl(page.url(), [skill.origin]);
          trace.after = await this.browser.observe(page);
          trace.status = 'succeeded';
          trace.durationMs = Date.now() - stepStart;
          save();
        } catch (error) {
          trace.status = 'failed';
          trace.error = error instanceof Error ? error.message : String(error);
          trace.durationMs = Date.now() - stepStart;
          save();
          throw error;
        }
      }
      await page
        .getByText(skill.postcondition, { exact: true })
        .first()
        .waitFor({ state: 'visible', timeout: 5000 });
      run.verified = true;
      run.status = 'succeeded';
    } catch (error) {
      run.status = this.cancelled.has(run.id) ? 'cancelled' : 'failed';
      run.error = error instanceof Error ? error.message : String(error);
    } finally {
      if (page && !page.isClosed()) {
        try {
          mkdirSync(join(this.dataDir, 'screenshots'), { recursive: true });
          await page.screenshot({
            path: join(this.dataDir, 'screenshots', `${run.id}.png`),
            timeout: 3000,
          });
          run.screenshot = `/api/runs/${run.id}/screenshot`;
        } catch {
          /* Screenshot failure must not replace the action outcome. */
        }
      }
      await close?.().catch(() => {});
      this.closers.delete(run.id);
      this.cancelled.delete(run.id);
      run.finishedAt = now();
      run.durationMs = Date.now() - started;
      this.store.transaction(() => {
        if (!run.evaluationId && run.status !== 'cancelled') {
          const current = this.store.get('skill', skill.id);
          if (current) {
            current.attempts += 1;
            current.lastUsed = now();
            if (run.status === 'succeeded') {
              current.successes += 1;
              this.store.preference(current.app);
              if (run.repairs && current.version === run.skillVersion) {
                current.workflow = skill.workflow;
                current.version += 1;
                current.updatedAt = now();
              }
            }
            this.store.put('skill', current);
          }
        }
        save();
      });
    }
    return run;
  }
  evaluate(): Evaluation {
    if (this.store.list('evaluation').some((e) => e.status === 'running'))
      throw new Error('已有评测正在进行。');
    const evaluation: Evaluation = {
      id: randomUUID(),
      status: 'running',
      createdAt: now(),
      rows: [],
    };
    this.store.put('evaluation', evaluation);
    void this.evaluateAll(evaluation);
    return evaluation;
  }
  private async evaluateAll(evaluation: Evaluation) {
    try {
      for (const skill of exampleSkills(this.baseUrl)) {
        for (const variant of ['original', 'renamed', 'layout', 'ambiguous'] as const) {
          const decision: Decision = {
            kind: 'skill',
            provider: 'local',
            choice: skill.id,
            confidence: 1,
            reason: '受控评测：固定相同 Skill 和参数，每个条件使用全新页面。',
            options: [],
            latencyMs: 0,
          };
          const input = {
            task: skill.description,
            parameters: {},
            variant,
            approved: true,
            repairEnabled: false,
          };
          const baseline = await this.create(skill, input, decision, evaluation.id).done;
          const adaptive = await this.create(
            skill,
            { ...input, repairEnabled: true },
            decision,
            evaluation.id,
          ).done;
          evaluation.rows.push({
            app: skill.app,
            variant,
            baseline: baseline.verified,
            adaptive: adaptive.verified,
            baselineRunId: baseline.id,
            adaptiveRunId: adaptive.id,
            repairAttempted: adaptive.steps.some((s) => s.decision?.kind === 'repair'),
            repaired: adaptive.repairs > 0 && adaptive.verified,
            safelyAbstained:
              variant === 'ambiguous' &&
              !adaptive.verified &&
              adaptive.steps.some((s) => s.decision?.choice === 'ask'),
          });
          this.store.put('evaluation', evaluation);
        }
      }
      const executable = evaluation.rows.filter((r) => r.variant !== 'ambiguous');
      const repairs = evaluation.rows.filter((r) => r.variant === 'renamed');
      const ambiguous = evaluation.rows.filter((r) => r.variant === 'ambiguous');
      evaluation.metrics = {
        total: evaluation.rows.length,
        baselineSuccess: executable.filter((r) => r.baseline).length / executable.length,
        adaptiveSuccess: executable.filter((r) => r.adaptive).length / executable.length,
        repairSuccess: repairs.filter((r) => r.repaired).length / repairs.length,
        safeAbstention: ambiguous.filter((r) => r.safelyAbstained).length / ambiguous.length,
      };
      evaluation.status = 'completed';
    } catch (error) {
      evaluation.status = 'failed';
      evaluation.error = error instanceof Error ? error.message : String(error);
    }
    evaluation.finishedAt = now();
    this.store.put('evaluation', evaluation);
  }
}
