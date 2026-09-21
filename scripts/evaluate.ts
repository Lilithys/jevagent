import 'dotenv/config';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { Evaluation } from '../shared/types.js';
const base = process.env.SKILLCUA_URL || `http://127.0.0.1:${process.env.PORT || 3210}`;
const response = await fetch(`${base}/api/evaluations`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: '{}',
});
const result = (await response.json()) as Evaluation & { error?: string };
if (!response.ok) throw new Error(result.error);
console.log(`Evaluation ${result.id} started. 24 browser runs; baseline vs. adaptive.`);
let evaluation = result,
  completed = -1;
while (evaluation.status === 'running') {
  await new Promise((resolve) => setTimeout(resolve, 1000));
  evaluation = (await (await fetch(`${base}/api/evaluations/${result.id}`)).json()) as Evaluation;
  if (evaluation.rows.length !== completed) {
    completed = evaluation.rows.length;
    console.log(`${completed}/12 conditions complete`);
  }
}
const directory = resolve('reports');
mkdirSync(directory, { recursive: true });
writeFileSync(resolve(directory, 'evaluation-latest.json'), JSON.stringify(evaluation, null, 2));
if (evaluation.status !== 'completed')
  throw new Error(evaluation.error || 'Evaluation did not complete');
console.table(evaluation.metrics);
console.log(
  'Saved reports/evaluation-latest.json. This is a controlled local benchmark, not a production success-rate claim.',
);
