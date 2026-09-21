import type { ElementInfo, Target, Skill, Candidate } from '../shared/types.js';

const concepts: [RegExp, string][] = [
  [/周报|每周报告|weekly[ _-]?report|project update/gi, ' weeklyreport '],
  [/月报|monthly[ _-]?report/gi, ' monthlyreport '],
  [/工单|ticket/gi, ' ticket '],
  [/问题|缺陷|故障|issue|bug/gi, ' issue '],
  [/创建|生成|新建|create|generate|prepare/gi, ' create '],
  [/本周|每周|weekly|this week/gi, ' weekly '],
];
export function tokens(text: string): string[] {
  let normalized = text.toLowerCase();
  for (const [regex, replacement] of concepts) normalized = normalized.replace(regex, replacement);
  return normalized.match(/[a-z0-9]+|[\u4e00-\u9fff]{1,2}/g) ?? [];
}
// Local feature-hashing embeddings: deterministic, offline, not a neural embedding model.
export function embed(text: string, dimensions = 384): number[] {
  const vector = Array<number>(dimensions).fill(0);
  for (const token of tokens(text)) {
    let hash = 2166136261;
    for (const char of token) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
    vector[(hash >>> 0) % dimensions] += 1;
  }
  const norm = Math.hypot(...vector) || 1;
  return vector.map((v) => v / norm);
}
export const cosine = (a: number[], b: number[]) => a.reduce((sum, n, i) => sum + n * b[i], 0);
export function retrieve(
  task: string,
  skills: Skill[],
  preferences: Record<string, number> = {},
): Candidate[] {
  const query = embed(task);
  const mentionedApps = ['github', 'jira', 'notion'].filter((app) =>
    task.toLowerCase().includes(app),
  );
  const terms = new Set(tokens(task));
  return skills
    .map((skill) => {
      const text = `${skill.name} ${skill.description} ${skill.triggers.join(' ')} ${skill.app}`;
      const words = new Set(tokens(text));
      const coverage = [...terms].filter((t) => words.has(t)).length / Math.max(terms.size, 1);
      let lexicalScore = 0.6 * cosine(query, embed(text)) + 0.4 * coverage;
      if (mentionedApps.length && !mentionedApps.includes(skill.app)) lexicalScore *= 0.2;
      const preferenceBonus =
        lexicalScore >= 0.25 ? Math.min(0.06, (preferences[skill.app] ?? 0) * 0.005) : 0;
      return {
        skill,
        lexicalScore,
        preferenceBonus,
        score: Math.min(1, lexicalScore + preferenceBonus),
      };
    })
    .sort((a, b) => b.score - a.score);
}
const intentions = [
  ['submit', 'publish', 'send', '提交', '发布', '发送'],
  ['submit issue', 'create issue', '提交问题', '创建问题'],
  ['create', 'create ticket', '创建', '新建工单'],
  ['new issue', 'new ticket', '新增问题'],
  ['report title', 'title', '报告标题', '标题'],
  ['report content', 'content', '报告内容', '正文'],
];
export function similarity(a: Target, b: Target): number {
  if (a.role !== b.role) return 0;
  const left = a.name.trim().toLowerCase(),
    right = b.name.trim().toLowerCase();
  if (left === right) return 1;
  if (intentions.some((group) => group.includes(left) && group.includes(right))) return 0.94;
  const ta = new Set(tokens(left)),
    tb = new Set(tokens(right));
  const overlap = [...ta].filter((t) => tb.has(t)).length;
  return (0.8 * overlap) / Math.max(ta.size, tb.size, 1);
}
export function repairCandidates(target: Target, elements: ElementInfo[]) {
  return elements
    .filter((e) => !e.disabled && e.role === target.role)
    .map((element) => ({ element, score: similarity(target, element) }))
    .filter((c) => c.score >= 0.85)
    .sort((a, b) => b.score - a.score);
}
