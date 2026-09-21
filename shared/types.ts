import { z } from 'zod';

export const appSchema = z.enum(['github', 'jira', 'notion', 'custom']);
export type AppId = z.infer<typeof appSchema>;
export const targetSchema = z.object({
  role: z.enum(['button', 'link', 'textbox', 'combobox', 'checkbox', 'radio', 'tab']),
  name: z.string().min(1).max(300),
});
export type Target = z.infer<typeof targetSchema>;
export const rawActionSchema = z.object({
  kind: z.enum(['navigate', 'click', 'fill', 'select', 'check']),
  target: targetSchema.optional(),
  value: z.string().max(20000).optional(),
  checked: z.boolean().optional(),
  url: z.string().max(2000),
  timestamp: z.number(),
});
export type RawAction = z.infer<typeof rawActionSchema>;
export type ElementInfo = Target & { disabled: boolean };
export type Observation = {
  url: string;
  title: string;
  elements: ElementInfo[];
  timestamp: string;
};
export type Step = {
  id: string;
  kind: RawAction['kind'];
  description: string;
  target?: Target;
  url?: string;
  parameter?: string;
  checked?: boolean;
};
export type Parameter = { key: string; label: string; defaultValue: string; required: boolean };
export type Skill = {
  id: string;
  name: string;
  description: string;
  app: AppId;
  triggers: string[];
  origin: string;
  startUrl: string;
  workflow: Step[];
  parameters: Parameter[];
  postcondition: string;
  version: number;
  createdAt: string;
  updatedAt: string;
  source: 'demonstration' | 'example';
  demonstrationId: string;
  rawActionCount: number;
  successes: number;
  attempts: number;
  lastUsed: string | null;
};
export type Demonstration = {
  id: string;
  name: string;
  task: string;
  app: AppId;
  startUrl: string;
  mode: 'lab' | 'browser';
  status: 'recording' | 'learned' | 'cancelled';
  actions: RawAction[];
  createdAt: string;
  skillId?: string;
};
export type Candidate = {
  skill: Skill;
  score: number;
  lexicalScore: number;
  preferenceBonus: number;
};
export type Decision = {
  kind: 'skill' | 'action' | 'repair';
  provider: 'local' | 'jev';
  choice: string;
  confidence: number;
  reason: string;
  options: { id: string; label: string; score: number }[];
  latencyMs: number;
};
export type TraceStep = {
  index: number;
  description: string;
  status: 'running' | 'succeeded' | 'failed';
  startedAt: string;
  durationMs?: number;
  before?: Observation;
  after?: Observation;
  error?: string;
  repair?: { from: Target; to: Target; score: number };
  decision?: Decision;
};
export type Run = {
  id: string;
  task: string;
  skillId: string;
  skillName: string;
  skillVersion: number;
  app: AppId;
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
  createdAt: string;
  finishedAt?: string;
  durationMs?: number;
  parameters: Record<string, string>;
  variant: 'original' | 'renamed' | 'layout' | 'ambiguous';
  repairEnabled: boolean;
  repairs: number;
  reused: boolean;
  decision: Decision;
  steps: TraceStep[];
  error?: string;
  screenshot?: string;
  verified: boolean;
  evaluationId?: string;
};
export type EvaluationRow = {
  app: AppId;
  variant: Run['variant'];
  baseline: boolean;
  adaptive: boolean;
  baselineRunId: string;
  adaptiveRunId: string;
  repairAttempted: boolean;
  repaired: boolean;
  safelyAbstained: boolean;
};
export type Evaluation = {
  id: string;
  status: 'running' | 'completed' | 'failed';
  createdAt: string;
  finishedAt?: string;
  rows: EvaluationRow[];
  error?: string;
  metrics?: {
    baselineSuccess: number;
    adaptiveSuccess: number;
    repairSuccess: number;
    safeAbstention: number;
    total: number;
  };
};
export type Summary = {
  skills: Skill[];
  runs: Run[];
  demonstrations: Demonstration[];
  evaluations: Evaluation[];
  preferences: Record<string, number>;
  stats: {
    total: number;
    successful: number;
    successRate: number | null;
    reuseRate: number | null;
    stepsReduction: number | null;
    repairs: number;
  };
  config: {
    policy: 'local' | 'jev';
    allowedOrigins: string[];
    browserChannel: string;
    authConfigured: boolean;
  };
};
export const labApps = {
  github: {
    name: 'GitHub',
    title: '创建 GitHub Issue',
    task: '在 GitHub 创建问题 issue bug',
    entry: 'New issue',
    titleLabel: 'Issue title',
    bodyLabel: 'Description',
    submit: 'Submit issue',
    renamed: 'Create issue',
    success: 'Issue created successfully',
  },
  jira: {
    name: 'Jira',
    title: '创建 Jira Ticket',
    task: '在 Jira 创建任务 ticket 工单',
    entry: 'Create ticket',
    titleLabel: 'Summary',
    bodyLabel: 'Description',
    submit: 'Create',
    renamed: 'Create ticket',
    success: 'Ticket created successfully',
  },
  notion: {
    name: 'Notion',
    title: '生成 Notion 周报',
    task: '在 Notion 生成本周项目周报 weekly report project update',
    entry: 'Weekly report template',
    titleLabel: 'Report title',
    bodyLabel: 'Report content',
    submit: 'Submit',
    renamed: 'Publish',
    success: 'Report published successfully',
  },
} as const;
export const now = () => new Date().toISOString();
