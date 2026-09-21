import { labApps, now, type Demonstration } from '../shared/types.js';
import { extractSkill } from './learning.js';
import type { Store } from './store.js';
export function exampleSkills(baseUrl: string) {
  return (Object.keys(labApps) as (keyof typeof labApps)[]).map((app) => {
    const spec = labApps[app],
      url = `${baseUrl}/lab/${app}`;
    const demo: Demonstration = {
      id: `example-${app}`,
      name: spec.title,
      task: spec.task,
      app,
      startUrl: url,
      mode: 'lab',
      status: 'learned',
      createdAt: now(),
      actions: [
        { kind: 'navigate', url, timestamp: 1 },
        { kind: 'click', target: { role: 'button', name: spec.entry }, url, timestamp: 2 },
        {
          kind: 'fill',
          target: { role: 'textbox', name: spec.titleLabel },
          value: app === 'notion' ? 'SkillCUA · 本周项目进展' : 'Improve skill retrieval',
          url,
          timestamp: 3,
        },
        {
          kind: 'fill',
          target: { role: 'textbox', name: spec.bodyLabel },
          value:
            app === 'notion'
              ? '本周完成：语义技能学习与浏览器运行时。\n下周计划：扩展工作流，完善评测。\n风险与阻塞：暂无。'
              : 'Support reusable semantic workflows and verify their outcomes.',
          url,
          timestamp: 4,
        },
        ...(app === 'jira'
          ? [
              {
                kind: 'select' as const,
                target: { role: 'combobox' as const, name: 'Priority' },
                value: 'Medium',
                url,
                timestamp: 5,
              },
            ]
          : []),
        { kind: 'click', target: { role: 'button', name: spec.submit }, url, timestamp: 6 },
      ],
    };
    const skill = extractSkill(demo, spec.success);
    return { ...skill, id: `example-${app}`, source: 'example' as const };
  });
}
export function seed(store: Store, baseUrl: string) {
  for (const skill of exampleSkills(baseUrl))
    if (!store.get('skill', skill.id)) store.put('skill', skill);
}
