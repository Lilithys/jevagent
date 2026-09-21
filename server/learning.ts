import { randomUUID } from 'node:crypto';
import {
  now,
  type Demonstration,
  type Skill,
  type Step,
  type Parameter,
  type RawAction,
  labApps,
} from '../shared/types.js';

export const sensitive = (name: string) =>
  /password|密码|secret|token|api.?key|信用卡|credit.?card|验证码|one.?time/i.test(name);
export function validateUrl(url: string, allowedOrigins: string[]): URL {
  const parsed = new URL(url);
  if (
    !['http:', 'https:'].includes(parsed.protocol) ||
    parsed.username ||
    parsed.password ||
    !allowedOrigins.includes(parsed.origin)
  )
    throw new Error('目标地址未获授权，请先在 ALLOWED_ORIGINS 中配置精确 origin。');
  return parsed;
}
export function extractSkill(demo: Demonstration, postcondition: string): Skill {
  if (!postcondition.trim()) throw new Error('必须指定完成后页面上出现的验证文本。');
  const compacted: RawAction[] = [];
  for (const action of demo.actions) {
    if (action.target && sensitive(action.target.name)) continue;
    if (action.kind !== 'navigate' && !action.target) throw new Error('操作缺少语义目标。');
    const previous = compacted.at(-1);
    const sameTarget =
      previous?.target?.role === action.target?.role &&
      previous?.target?.name === action.target?.name &&
      previous?.url === action.url;
    if (
      previous &&
      sameTarget &&
      ['fill', 'select', 'check'].includes(action.kind) &&
      previous.kind === action.kind
    )
      compacted[compacted.length - 1] = action;
    else compacted.push(action);
  }
  if (!compacted.some((a) => a.kind !== 'navigate'))
    throw new Error('尚未记录有效操作，请先完成一次示范。');
  if (compacted[0]?.kind !== 'navigate')
    compacted.unshift({ kind: 'navigate', url: demo.startUrl, timestamp: Date.now() });
  const parameters: Parameter[] = [];
  const workflow: Step[] = compacted.map((action, index) => {
    const step: Step = {
      id: `step-${index + 1}`,
      kind: action.kind,
      target: action.target,
      description: '',
    };
    if (action.kind === 'navigate') {
      step.url = action.url;
      step.description = `打开 ${new URL(action.url).pathname}`;
    } else if (action.kind === 'fill' || action.kind === 'select') {
      const label = action.target!.name;
      const slug =
        label
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, '_')
          .replace(/^_|_$/g, '') || `field_${index}`;
      let key = slug,
        suffix = 2;
      while (parameters.some((p) => p.key === key)) key = `${slug}_${suffix++}`;
      parameters.push({
        key,
        label,
        defaultValue: action.value ?? '',
        required: Boolean(action.value),
      });
      step.parameter = key;
      step.description = `${action.kind === 'fill' ? '填写' : '选择'} ${label}`;
    } else if (action.kind === 'check') {
      step.checked = action.checked ?? true;
      step.description = `${step.checked ? '勾选' : '取消勾选'} ${action.target!.name}`;
    } else step.description = `点击 ${action.target!.name}`;
    return step;
  });
  return {
    id: randomUUID(),
    name: demo.name,
    description: demo.task,
    app: demo.app,
    triggers: [demo.task, ...(demo.app !== 'custom' ? [labApps[demo.app].task] : [])],
    origin: new URL(demo.startUrl).origin,
    startUrl: demo.startUrl,
    workflow,
    parameters,
    postcondition: postcondition.trim(),
    version: 1,
    createdAt: now(),
    updatedAt: now(),
    source: 'demonstration',
    demonstrationId: demo.id,
    rawActionCount: demo.actions.length,
    successes: 0,
    attempts: 0,
    lastUsed: null,
  };
}
