import { DatabaseSync } from 'node:sqlite';
import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import type { Skill, Run, Demonstration, Evaluation, Summary } from '../shared/types.js';

type Entities = { skill: Skill; run: Run; demonstration: Demonstration; evaluation: Evaluation };
export class Store {
  db: DatabaseSync;
  constructor(path: string) {
    if (path !== ':memory:') mkdirSync(dirname(path), { recursive: true });
    this.db = new DatabaseSync(path);
    this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;
      CREATE TABLE IF NOT EXISTS entities (kind TEXT NOT NULL, id TEXT NOT NULL, json TEXT NOT NULL, PRIMARY KEY(kind,id));
      CREATE TABLE IF NOT EXISTS revisions (skill_id TEXT NOT NULL, version INTEGER NOT NULL, json TEXT NOT NULL, PRIMARY KEY(skill_id,version));
      CREATE TABLE IF NOT EXISTS preferences (app TEXT PRIMARY KEY, successes INTEGER NOT NULL DEFAULT 0);`);
    for (const run of this.list('run'))
      if (['running', 'queued'].includes(run.status)) {
        this.put('run', {
          ...run,
          status: 'failed',
          error: '服务重启，执行已中断。请检查目标页面后重新运行。',
          finishedAt: new Date().toISOString(),
        });
      }
    for (const evaluation of this.list('evaluation'))
      if (evaluation.status === 'running')
        this.put('evaluation', { ...evaluation, status: 'failed', error: '服务重启，评测中断。' });
    for (const demo of this.list('demonstration'))
      if (demo.status === 'recording') this.put('demonstration', { ...demo, status: 'cancelled' });
  }
  list<K extends keyof Entities>(kind: K): Entities[K][] {
    return (
      this.db.prepare('SELECT json FROM entities WHERE kind=? ORDER BY rowid DESC').all(kind) as {
        json: string;
      }[]
    ).map((row) => JSON.parse(row.json));
  }
  get<K extends keyof Entities>(kind: K, id: string): Entities[K] | undefined {
    const row = this.db.prepare('SELECT json FROM entities WHERE kind=? AND id=?').get(kind, id) as
      { json: string } | undefined;
    return row ? JSON.parse(row.json) : undefined;
  }
  put<K extends keyof Entities>(kind: K, value: Entities[K]) {
    this.db
      .prepare(
        'INSERT INTO entities(kind,id,json) VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET json=excluded.json',
      )
      .run(kind, value.id, JSON.stringify(value));
    if (kind === 'skill') {
      const skill = value as Skill;
      this.db
        .prepare(
          'INSERT INTO revisions(skill_id,version,json) VALUES(?,?,?) ON CONFLICT(skill_id,version) DO NOTHING',
        )
        .run(skill.id, skill.version, JSON.stringify(skill));
    }
    return value;
  }
  versions(id: string): Skill[] {
    return (
      this.db
        .prepare('SELECT json FROM revisions WHERE skill_id=? ORDER BY version DESC')
        .all(id) as { json: string }[]
    ).map((row) => JSON.parse(row.json));
  }
  transaction<T>(fn: () => T): T {
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const result = fn();
      this.db.exec('COMMIT');
      return result;
    } catch (error) {
      this.db.exec('ROLLBACK');
      throw error;
    }
  }
  preference(app: string) {
    this.db
      .prepare(
        'INSERT INTO preferences(app,successes) VALUES(?,1) ON CONFLICT(app) DO UPDATE SET successes=successes+1',
      )
      .run(app);
  }
  preferences(): Record<string, number> {
    return Object.fromEntries(
      (
        this.db.prepare('SELECT * FROM preferences').all() as { app: string; successes: number }[]
      ).map((r) => [r.app, r.successes]),
    );
  }
  stats(): Summary['stats'] {
    const runs = this.list('run').filter(
      (r) => !r.evaluationId && ['succeeded', 'failed', 'cancelled'].includes(r.status),
    );
    const successful = runs.filter((r) => r.status === 'succeeded');
    const learned = this.list('skill').filter((s) => s.source === 'demonstration');
    const raw = learned.reduce((sum, s) => sum + s.rawActionCount, 0);
    const steps = learned.reduce((sum, s) => sum + s.workflow.length, 0);
    return {
      total: runs.length,
      successful: successful.length,
      successRate: runs.length ? successful.length / runs.length : null,
      reuseRate: runs.length ? runs.filter((r) => r.reused).length / runs.length : null,
      stepsReduction: raw ? Math.max(0, 1 - steps / raw) : null,
      repairs: successful.reduce((s, r) => s + r.repairs, 0),
    };
  }
  close() {
    this.db.close();
  }
}
