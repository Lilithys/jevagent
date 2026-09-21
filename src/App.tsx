import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import {
  Activity,
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronRight,
  Circle,
  Code2,
  Download,
  Eye,
  FlaskConical,
  GitBranch,
  Layers3,
  Loader2,
  MousePointer2,
  Play,
  Plus,
  Radio,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Square,
  Terminal,
  WandSparkles,
  X,
} from 'lucide-react';
import {
  labApps,
  type AppId,
  type Candidate,
  type Decision,
  type Demonstration,
  type Evaluation,
  type Run,
  type Skill,
  type Summary,
} from '../shared/types';
import { api, download } from './api';

type View = 'overview' | 'workspace' | 'teach' | 'skills' | 'runs' | 'evaluation' | 'settings';
const nav = [
  { id: 'overview', label: '总览', icon: Layers3 },
  { id: 'workspace', label: '工作台', icon: Terminal },
  { id: 'teach', label: '教学模式', icon: MousePointer2 },
  { id: 'skills', label: '技能库', icon: BookOpen },
  { id: 'runs', label: '执行记录', icon: Activity },
  { id: 'evaluation', label: '评测实验室', icon: FlaskConical },
] as const;
const variants: Record<Run['variant'], string> = {
  original: '原始页面',
  renamed: '按钮更名',
  layout: '布局调整',
  ambiguous: '歧义按钮',
};
const statuses: Record<Run['status'], string> = {
  queued: '等待执行',
  running: '正在执行',
  succeeded: '已验证',
  failed: '已停止',
  cancelled: '已取消',
};
const percentage = (value: number | null | undefined) =>
  value == null ? '—' : `${Math.round(value * 100)}%`;
const formatTime = (value: string) =>
  new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
function Brand({ app, small = false }: { app: AppId; small?: boolean }) {
  return (
    <span className={`app-brand ${app} ${small ? 'small' : ''}`}>
      {app === 'notion' ? (
        'N'
      ) : app === 'github' ? (
        <GitBranch size={small ? 17 : 22} />
      ) : app === 'jira' ? (
        <span className="jira-mark">◆</span>
      ) : (
        <Code2 size={20} />
      )}
    </span>
  );
}
function Badge({ children, tone = '' }: { children: ReactNode; tone?: string }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
function Empty({ title, text, children }: { title: string; text: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Layers3 size={26} />
      </div>
      <h3>{title}</h3>
      <p>{text}</p>
      {children}
    </div>
  );
}
function Spinner() {
  return <Loader2 size={16} className="spin" />;
}
function Stat({
  label,
  value,
  note,
  icon,
}: {
  label: string;
  value: ReactNode;
  note: string;
  icon: ReactNode;
}) {
  return (
    <div className="stat">
      <div className="stat-label">
        {label}
        {icon}
      </div>
      <div className="stat-value">{value}</div>
      <div className="stat-note">{note}</div>
    </div>
  );
}

export default function App() {
  const [view, setView] = useState<View>('overview');
  const [data, setData] = useState<Summary | null>(null);
  const [error, setError] = useState('');
  const [selectedSkill, setSelectedSkill] = useState('example-notion');
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [activeDemo, setActiveDemo] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    setData(await api<Summary>('/state'));
  }, []);
  useEffect(() => {
    void refresh().catch((e) => setError(e.message));
    const timer = setInterval(() => {
      void refresh().catch(() => {});
    }, 1500);
    return () => clearInterval(timer);
  }, [refresh]);
  const act = async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    try {
      const value = await fn();
      await refresh();
      return value;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  const choose = (skill: Skill) => {
    setSelectedSkill(skill.id);
    setView('workspace');
  };
  const openRun = (id: string) => {
    setSelectedRun(id);
    setView('runs');
  };
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="logo"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setView('overview');
          }}
        >
          <span className="logo-symbol">
            <Layers3 size={22} />
          </span>
          SkillCUA
          <span className="logo-dot" />
        </a>
        <div className="workspace-switch">
          <span className="avatar">P</span>
          <div>
            <b>Personal workspace</b>
            <small>本地研究空间</small>
          </div>
          <span className="key-hint">⌘</span>
        </div>
        <div className="nav-caption">WORKSPACE</div>
        <nav>
          {nav.map((item) => (
            <button
              key={item.id}
              className={`nav-item ${view === item.id ? 'active' : ''}`}
              onClick={() => setView(item.id)}
            >
              <item.icon size={18} />
              {item.label}
              {item.id === 'skills' && (
                <span className="nav-count">{data?.skills.length ?? 0}</span>
              )}
              {item.id === 'teach' && activeDemo && <span className="record-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-card">
            <span className="status-dot" />
            <b>Local-first, skill-driven.</b>
            <p>从一次示范，到每一次复用。</p>
            <div>
              <span>POLICY</span>
              <Badge>{data?.config.policy === 'jev' ? 'Jev API' : 'Local · 无需 API key'}</Badge>
            </div>
          </div>
          <button
            className={`nav-item ${view === 'settings' ? 'active' : ''}`}
            onClick={() => setView('settings')}
          >
            <Settings2 size={18} />
            设置与连接
            <ArrowUpRight size={14} className="push" />
          </button>
          <div className="sidebar-foot">
            SkillCUA Research Preview <span>v1.0</span>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div>
            <span className="muted">Workspace</span>
            <ChevronRight size={13} />
            <b>{view === 'settings' ? '设置与连接' : nav.find((n) => n.id === view)?.label}</b>
          </div>
          <div className="top-right">
            <span className="status-dot" />
            浏览器工作流学习
            <span className="top-divider" />
            <Badge tone="outline">RESEARCH MVP</Badge>
            <span className="user-avatar">P</span>
          </div>
        </header>
        <main>
          {!data ? (
            <Empty
              title={error ? '暂时无法连接服务' : '正在连接你的工作空间'}
              text={error || '加载技能与执行记录…'}
            >
              <button
                className="button"
                onClick={() => void refresh().catch((e) => setError(e.message))}
              >
                重试
              </button>
            </Empty>
          ) : (
            <>
              {view === 'overview' && (
                <Overview
                  data={data}
                  choose={choose}
                  teach={() => setView('teach')}
                  library={() => setView('skills')}
                  openRun={openRun}
                />
              )}
              {view === 'workspace' && (
                <Workspace
                  data={data}
                  selectedSkill={selectedSkill}
                  selectSkill={setSelectedSkill}
                  act={act}
                  openRun={openRun}
                />
              )}
              {view === 'teach' && (
                <Teach
                  data={data}
                  activeId={activeDemo}
                  setActiveId={setActiveDemo}
                  act={act}
                  learned={(skill) => {
                    setSelectedSkill(skill.id);
                    setView('skills');
                  }}
                />
              )}
              {view === 'skills' && (
                <Library
                  data={data}
                  selectedId={selectedSkill}
                  select={setSelectedSkill}
                  choose={choose}
                  act={act}
                  teach={() => setView('teach')}
                />
              )}
              {view === 'runs' && (
                <Runs data={data} selectedId={selectedRun} select={setSelectedRun} act={act} />
              )}
              {view === 'evaluation' && <Evaluations data={data} act={act} openRun={openRun} />}
              {view === 'settings' && <Settings data={data} />}
            </>
          )}
        </main>
        <footer className="main-footer">
          <span>
            <span className="mini-dot" /> BUILT TO LEARN. DESIGNED TO ADAPT.
          </span>
          <span>Observe → Learn → Execute → Improve</span>
        </footer>
      </div>
      {error && (
        <div className="toast" role="alert">
          <Circle size={17} />
          <span>{error}</span>
          <button aria-label="关闭提示" onClick={() => setError('')}>
            <X size={18} />
          </button>
        </div>
      )}
    </div>
  );
}
type Act = <T>(fn: () => Promise<T>) => Promise<T | undefined>;
function PageTitle({
  eyebrow,
  title,
  text,
  children,
}: {
  eyebrow: string;
  title: string;
  text: string;
  children?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{text}</p>
      </div>
      {children}
    </div>
  );
}

function Overview({
  data,
  choose,
  teach,
  library,
  openRun,
}: {
  data: Summary;
  choose: (s: Skill) => void;
  teach: () => void;
  library: () => void;
  openRun: (id: string) => void;
}) {
  const examples = ['notion', 'github', 'jira']
    .map((app) => data.skills.find((s) => s.id === `example-${app}`))
    .filter(Boolean) as Skill[];
  return (
    <>
      <PageTitle
        eyebrow="YOUR PERSONAL LEARNING AGENT"
        title="每次示范，都让下一次更简单。"
        text="把你的工作习惯，变成 Agent 可以理解、复用和改进的技能。"
      >
        <button className="button primary" onClick={teach}>
          <Plus size={17} />
          教授新技能
        </button>
      </PageTitle>
      <section className="hero">
        <div className="hero-content">
          <Badge tone="hero-tag">
            <Sparkles size={12} /> ADAPTIVE COMPUTER USE
          </Badge>
          <h2>
            不止会操作。
            <br />
            更懂你如何完成工作。
          </h2>
          <p>
            观察一次示范，学习一套方法。
            <br />
            让重复的工作流，成为不断进化的技能。
          </p>
          <button className="button dark" onClick={() => examples[0] && choose(examples[0])}>
            运行第一个工作流
            <ArrowRight size={16} />
          </button>
          <span className="hero-note">3 个练习应用 · 本地运行 · 可追溯执行</span>
        </div>
        <div className="learning-map" aria-label="观察、学习、执行、修复的技能循环">
          <div className="map-top-label">
            <span className="status-dot" /> THE LEARNING LOOP
          </div>
          <div className="map-line horizontal" />
          <div className="map-line vertical" />
          <div className="map-node node-observe">
            <div className="node-icon">
              <Eye size={19} />
            </div>
            <div>
              <small>01 / OBSERVE</small>
              <b>观察你的操作</b>
            </div>
            <span className="node-dots">···</span>
          </div>
          <div className="map-node node-learn">
            <div className="node-icon">
              <BookOpen size={19} />
            </div>
            <div>
              <small>02 / LEARN</small>
              <b>沉淀语义技能</b>
            </div>
            <span className="node-check">
              <Check size={13} />
            </span>
          </div>
          <div className="map-node node-execute">
            <div className="node-icon">
              <Play size={19} />
            </div>
            <div>
              <small>03 / EXECUTE</small>
              <b>自主选择与执行</b>
            </div>
            <ArrowUpRight size={16} />
          </div>
          <div className="map-repair">
            <GitBranch size={14} />
            <span>Repair & improve</span>
            <span className="repair-plus">+</span>
          </div>
          <div className="map-caption">Your workflow, learned.</div>
        </div>
      </section>
      <div className="stats-grid">
        <Stat
          label="可用技能"
          value={
            <>
              {data.skills.length}
              <span>skills</span>
            </>
          }
          note={`${data.skills.filter((s) => s.source === 'demonstration').length} 个来自你的示范`}
          icon={<BookOpen size={16} />}
        />
        <Stat
          label="执行成功率"
          value={percentage(data.stats.successRate)}
          note={
            data.stats.total
              ? `${data.stats.successful} / ${data.stats.total} 次通过结果验证`
              : '运行工作流后开始统计'
          }
          icon={<CheckCircle2 size={16} />}
        />
        <Stat
          label="技能再次复用率"
          value={percentage(data.stats.reuseRate)}
          note={`示范事件压缩 ${percentage(data.stats.stepsReduction)} · 不含评测`}
          icon={<GitBranch size={16} />}
        />
        <Stat
          label="已验证的修复"
          value={
            <>
              {data.stats.repairs}
              <span>repairs</span>
            </>
          }
          note="成功验证后保存为新版本"
          icon={<WandSparkles size={16} />}
        />
      </div>
      <section className="section">
        <div className="section-heading">
          <div>
            <h2>
              从一个熟悉的任务开始 <span className="number-tag">03</span>
            </h2>
            <p>精选示例技能，可直接在隔离的练习环境中体验。</p>
          </div>
          <button className="text-button" onClick={library}>
            查看技能库
            <ArrowRight size={14} />
          </button>
        </div>
        <div className="skill-grid">
          {examples.map((skill) => (
            <SkillCard key={skill.id} skill={skill} onClick={() => choose(skill)} />
          ))}
        </div>
      </section>
      <section className="section recent-section">
        <div className="section-heading">
          <div>
            <h2>最近的执行</h2>
            <p>每一次选择和修复，都有迹可循。</p>
          </div>
          <Badge tone="outline">LIVE ACTIVITY</Badge>
        </div>
        {data.runs.length ? (
          <div className="table-wrap">
            <RunTable runs={data.runs.slice(0, 4)} open={openRun} />
          </div>
        ) : (
          <div className="recent-empty">
            <span className="empty-orbit">
              <Activity size={21} />
            </span>
            <div>
              <b>准备好开始第一次学习了吗？</b>
              <p>运行示例或教授新技能，你的执行轨迹将显示在这里。</p>
            </div>
            <button className="text-button" onClick={() => examples[0] && choose(examples[0])}>
              开始体验
              <ArrowRight size={15} />
            </button>
          </div>
        )}
      </section>
    </>
  );
}
function SkillCard({ skill, onClick }: { skill: Skill; onClick: () => void }) {
  return (
    <button className="skill-card" onClick={onClick}>
      <div className="card-top">
        <Brand app={skill.app} />
        <Badge>
          {skill.source === 'example' ? '示例技能' : '已学习'}
          <span className="badge-dot" />v{skill.version}
        </Badge>
      </div>
      <h3>{skill.name}</h3>
      <p>
        {skill.app === 'notion'
          ? '打开模板，整理项目进展，发布本周周报。'
          : skill.app === 'github'
            ? '填写问题描述，用你的方式创建项目 Issue。'
            : skill.app === 'jira'
              ? '录入任务详情与优先级，让工作有序推进。'
              : skill.description}
      </p>
      <div className="card-bottom">
        <span>
          <Layers3 size={13} />
          {skill.workflow.length} 个语义步骤
        </span>
        <span className="card-arrow">
          <ArrowUpRight size={16} />
        </span>
      </div>
    </button>
  );
}

function Workspace({
  data,
  selectedSkill,
  selectSkill,
  act,
  openRun,
}: {
  data: Summary;
  selectedSkill: string;
  selectSkill: (s: string) => void;
  act: Act;
  openRun: (id: string) => void;
}) {
  const [task, setTask] = useState('帮我完成本周的 Notion 项目周报');
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [parameters, setParameters] = useState<Record<string, string>>({});
  const [variant, setVariant] = useState<Run['variant']>('original');
  const [repairEnabled, setRepair] = useState(true);
  const [busy, setBusy] = useState(false);
  const skill = data.skills.find((s) => s.id === selectedSkill);
  useEffect(() => {
    setParameters(Object.fromEntries(skill?.parameters.map((p) => [p.key, p.defaultValue]) ?? []));
  }, [skill?.id]);
  async function search() {
    setBusy(true);
    const result = await act(() =>
      api<{ candidates: Candidate[]; decision: Decision }>('/retrieve', { task }),
    );
    if (result) {
      setCandidates(result.candidates);
      setDecision(result.decision);
      if (result.decision.choice !== 'ask') selectSkill(result.decision.choice);
    }
    setBusy(false);
  }
  async function execute() {
    if (!skill) return;
    setBusy(true);
    const run = await act(() =>
      api<Run>('/runs', {
        task,
        skillId: skill.id,
        parameters,
        variant,
        repairEnabled,
        approved: true,
      }),
    );
    setBusy(false);
    if (run) openRun(run.id);
  }
  const local = skill && skill.startUrl.includes('/lab/');
  return (
    <>
      <PageTitle
        eyebrow="THE EXECUTION WORKSPACE"
        title="描述目标，让技能接手。"
        text="检索适合的技能，确认输入，再交给浏览器执行。"
      />
      <div className="query-box">
        <label htmlFor="task-query">
          <Sparkles size={17} />
          这次想完成什么？
        </label>
        <div className="query-input">
          <input
            id="task-query"
            value={task}
            onChange={(e) => setTask(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && void search()}
            placeholder="例如：帮我完成本周的项目周报"
          />
          <button
            className="button primary"
            disabled={busy || !task.trim()}
            onClick={() => void search()}
          >
            {busy ? <Spinner /> : <Search size={16} />}检索技能
          </button>
        </div>
        <div className="suggestions">
          <span>试试</span>
          {['生成 Notion 周报', '创建 GitHub Issue', '创建 Jira 工单'].map((s) => (
            <button key={s} onClick={() => setTask(s)}>
              {s}
              <ArrowUpRight size={12} />
            </button>
          ))}
        </div>
      </div>
      {decision && (
        <div className={`decision-banner ${decision.choice === 'ask' ? 'attention' : ''}`}>
          <GitBranch size={19} />
          <div>
            <b>
              {decision.choice === 'ask'
                ? '需要你进一步选择或示范'
                : `已找到匹配技能 · ${data.skills.find((s) => s.id === decision.choice)?.name}`}
            </b>
            <p>{decision.reason}</p>
          </div>
          <Badge>
            {decision.provider === 'jev' ? 'JEV CONFIDENCE' : 'LOCAL SCORE'}{' '}
            {percentage(decision.confidence)}
          </Badge>
        </div>
      )}
      <div className="work-grid">
        <section className="panel">
          <div className="panel-heading">
            <h2>选择技能</h2>
            <span className="muted">{data.skills.length} available</span>
          </div>
          <div className="candidate-list">
            {(candidates.length ? candidates.map((c) => c.skill) : data.skills).map((s) => (
              <button
                className={`candidate ${s.id === selectedSkill ? 'selected' : ''}`}
                key={s.id}
                onClick={() => selectSkill(s.id)}
              >
                <Brand app={s.app} small />
                <div>
                  <b>{s.name}</b>
                  <small>
                    {s.workflow.length} 步 · v{s.version} ·{' '}
                    {s.source === 'example' ? '示例' : '示范学习'}
                  </small>
                </div>
                {candidates.length ? (
                  <span className="score">
                    {percentage(candidates.find((c) => c.skill.id === s.id)?.score)}
                  </span>
                ) : (
                  s.id === selectedSkill && <CheckCircle2 size={17} />
                )}
              </button>
            ))}
          </div>
          <div className="panel-note">
            <ShieldCheck size={16} />
            不确定的检索或修复会停止并交还给你。
          </div>
        </section>
        {skill && (
          <section className="panel parameter-panel">
            <div className="panel-heading">
              <h2>任务参数</h2>
              <Badge>v{skill.version}</Badge>
            </div>
            <div className="panel-body">
              {skill.parameters.map((p) => (
                <label className="field" key={p.key}>
                  {p.label}
                  <span className="field-key">{`{{${p.key}}}`}</span>
                  {p.defaultValue.length > 90 || /content|description|body/i.test(p.key) ? (
                    <textarea
                      value={parameters[p.key] ?? ''}
                      onChange={(e) => setParameters({ ...parameters, [p.key]: e.target.value })}
                      rows={4}
                    />
                  ) : (
                    <input
                      value={parameters[p.key] ?? ''}
                      onChange={(e) => setParameters({ ...parameters, [p.key]: e.target.value })}
                    />
                  )}
                </label>
              ))}
              <div className="two-fields">
                <label className="field">
                  练习页面变体
                  <select
                    value={variant}
                    disabled={!local}
                    onChange={(e) => setVariant(e.target.value as Run['variant'])}
                  >
                    {Object.entries(variants).map(([key, label]) => (
                      <option key={key} value={key}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="switch-field">
                  <input
                    type="checkbox"
                    checked={repairEnabled}
                    onChange={(e) => setRepair(e.target.checked)}
                  />
                  <span>
                    <b>自动修复</b>
                    <small>按钮更名时寻找语义替代</small>
                  </span>
                </label>
              </div>
              <div className="verify-note">
                <ShieldCheck size={16} />
                <div>
                  完成验证<span>{skill.postcondition}</span>
                </div>
              </div>
              {!local && (
                <p className="notice">
                  此技能操作真实网页。下方按钮确认执行以上参数及技能库中的完整步骤；请确保目标窗口已具备必要的访问权限。
                </p>
              )}
              <button
                className="button primary full"
                disabled={busy || !task.trim()}
                onClick={() => void execute()}
              >
                {busy ? <Spinner /> : <Play size={16} />}确认并执行工作流
                <ArrowRight size={15} />
              </button>
              <div className="center-note">
                {local ? '仅操作本地练习页面，不会提交到外部服务' : skill.startUrl}
              </div>
            </div>
          </section>
        )}
      </div>
    </>
  );
}

function Teach({
  data,
  activeId,
  setActiveId,
  act,
  learned,
}: {
  data: Summary;
  activeId: string | null;
  setActiveId: (id: string | null) => void;
  act: Act;
  learned: (s: Skill) => void;
}) {
  const [app, setApp] = useState<AppId>('notion');
  const [name, setName] = useState<string>(labApps.notion.title);
  const [task, setTask] = useState<string>(labApps.notion.task);
  const [mode, setMode] = useState<'lab' | 'browser'>('lab');
  const [url, setUrl] = useState('');
  const [postcondition, setPostcondition] = useState<string>(labApps.notion.success);
  const [busy, setBusy] = useState(false);
  const frame = useRef<HTMLIFrameElement>(null);
  const queue = useRef(Promise.resolve());
  const [recordError, setRecordError] = useState('');
  const demo = data.demonstrations.find((d) => d.id === activeId && d.status === 'recording');
  useEffect(() => {
    function record(event: MessageEvent) {
      if (
        !activeId ||
        event.origin !== location.origin ||
        event.source !== frame.current?.contentWindow ||
        event.data?.source !== 'skillcua-recorder'
      )
        return;
      queue.current = queue.current
        .then(async () => {
          await api(`/demonstrations/${activeId}/actions`, event.data.action);
        })
        .catch((error) => setRecordError(error.message));
    }
    window.addEventListener('message', record);
    return () => window.removeEventListener('message', record);
  }, [activeId]);
  function changeApp(value: AppId) {
    setApp(value);
    if (value !== 'custom') {
      setName(labApps[value].title);
      setTask(labApps[value].task);
      setPostcondition(labApps[value].success);
    }
  }
  async function start() {
    setBusy(true);
    setRecordError('');
    const result = await act(() =>
      api<Demonstration>('/demonstrations', {
        app,
        name,
        task,
        mode,
        startUrl: mode === 'browser' ? url : undefined,
      }),
    );
    if (result) setActiveId(result.id);
    setBusy(false);
  }
  async function finish() {
    if (!demo) return;
    setBusy(true);
    await queue.current;
    const result = await act(() =>
      api<Skill>(`/demonstrations/${demo.id}/finish`, { postcondition }),
    );
    setBusy(false);
    if (result) {
      setActiveId(null);
      learned(result);
    }
  }
  async function cancel() {
    if (!demo) return;
    await act(() => api(`/demonstrations/${demo.id}/cancel`, {}));
    setActiveId(null);
  }
  return (
    <>
      <PageTitle
        eyebrow="LEARN FROM DEMONSTRATION"
        title="做一遍，教会你的 Agent。"
        text="按你习惯的顺序操作，SkillCUA 会把示范抽象为可复用的语义步骤。"
      />
      <div className="teaching-steps">
        {['描述任务', '示范操作', '提取技能'].map((s, i) => (
          <div key={s} className={i === (demo ? 1 : 0) ? 'current' : ''}>
            <span>{String(i + 1).padStart(2, '0')}</span>
            {s}
            {i < 2 && <ChevronRight size={16} />}
          </div>
        ))}
      </div>
      {!demo ? (
        <div className="teach-setup">
          <section className="panel">
            <div className="panel-heading">
              <h2>新建示范</h2>
              <Badge>TEACHING MODE</Badge>
            </div>
            <div className="panel-body">
              <div className="segmented">
                <button
                  className={mode === 'lab' ? 'active' : ''}
                  onClick={() => {
                    setMode('lab');
                    if (app === 'custom') changeApp('notion');
                  }}
                >
                  本地练习环境
                </button>
                <button
                  className={mode === 'browser' ? 'active' : ''}
                  onClick={() => setMode('browser')}
                >
                  真实浏览器
                </button>
              </div>
              <label className="field">
                应用
                <select value={app} onChange={(e) => changeApp(e.target.value as AppId)}>
                  {Object.entries(labApps).map(([key, value]) => (
                    <option key={key} value={key}>
                      {value.name}
                    </option>
                  ))}
                  {mode === 'browser' && <option value="custom">自定义网页</option>}
                </select>
              </label>
              <label className="field">
                技能名称
                <input value={name} onChange={(e) => setName(e.target.value)} />
              </label>
              <label className="field">
                任务描述
                <textarea value={task} onChange={(e) => setTask(e.target.value)} rows={2} />
              </label>
              {mode === 'browser' && (
                <label className="field">
                  起始地址
                  <input
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="https://your-app.example.com/tasks"
                  />
                  <small>需将精确 origin 加入 .env 的 ALLOWED_ORIGINS。</small>
                </label>
              )}
              <label className="field">
                完成后出现的文本
                <input value={postcondition} onChange={(e) => setPostcondition(e.target.value)} />
                <small>作为执行后的结果验证条件，必须是页面上的完整文本。</small>
              </label>
              <button
                className="button primary full"
                disabled={
                  busy ||
                  !name.trim() ||
                  !task.trim() ||
                  !postcondition.trim() ||
                  (mode === 'browser' && !url)
                }
                onClick={() => void start()}
              >
                {busy ? <Spinner /> : <Radio size={16} />}开始教学
                <ArrowRight size={16} />
              </button>
            </div>
          </section>
          <div className="teaching-explainer">
            <div className="explainer-icon">
              <MousePointer2 size={30} />
            </div>
            <h2>记住意图，复用方法。</h2>
            <p>
              点击「提交」比点击一个坐标更有意义。
              <br />
              教学模式捕获元素的角色和名称，
              <br />
              把一次操作，变成一套方法。
            </p>
            <div className="semantic-example">
              <div>
                <span>OBSERVE</span>
                <code>button · Submit</code>
              </div>
              <ArrowDown size={18} />
              <div>
                <span>LEARN</span>
                <code>Click(Submit button)</code>
              </div>
              <ArrowDown size={18} />
              <div>
                <span>REUSE</span>
                <code>Fill(title, {'{{title}}'})</code>
              </div>
            </div>
            <p className="small-text">
              录制仅在教学期间启用。密码、验证码和识别出的密钥字段会被忽略。其他填写内容保存在本机，提取后可作为默认参数修改。
            </p>
          </div>
        </div>
      ) : (
        <>
          <div className="recording-bar">
            <span className="record-dot" />
            <div>
              <b>正在学习 · {demo.name}</b>
              <span>{demo.actions.length} 个原始事件已捕获</span>
            </div>
            <button className="button" disabled={busy} onClick={() => void cancel()}>
              <Square size={13} />
              取消
            </button>
            <button
              className="button primary"
              disabled={busy || Boolean(recordError)}
              onClick={() => void finish()}
            >
              {busy ? <Spinner /> : <WandSparkles size={16} />}完成示范并提取技能
            </button>
          </div>
          {recordError && (
            <p role="alert" className="notice">
              录制失败：{recordError}。请取消并重新开始，以免丢失步骤。
            </p>
          )}
          <div className="record-grid">
            <div className="browser-frame">
              <div className="browser-toolbar">
                <span />
                <span />
                <span />
                <div>{demo.startUrl}</div>
                <ShieldCheck size={14} />
              </div>
              {demo.mode === 'lab' ? (
                <iframe
                  title="教学练习页面"
                  ref={frame}
                  src={`${demo.startUrl}?record=${demo.id}`}
                />
              ) : (
                <Empty
                  title="已打开独立浏览器窗口"
                  text="在新窗口中完成任务，返回这里结束教学。仅记录当前主页面。"
                />
              )}
            </div>
            <section className="panel capture-panel">
              <div className="panel-heading">
                <h2>实时观察</h2>
                <Radio size={15} />
              </div>
              <div className="capture-events">
                {demo.actions.slice(-18).map((a, i) => (
                  <div className="capture-event" key={`${a.timestamp}-${i}`}>
                    <span className="event-dot" />
                    <div>
                      <code>{a.kind}</code>
                      <b>{a.target?.name || '打开页面'}</b>
                      <small>{a.target?.role || new URL(a.url).pathname}</small>
                    </div>
                    <Check size={12} />
                  </div>
                ))}
              </div>
              <div className="panel-note">输入事件会在提取时合并；填写内容会抽为参数。</div>
            </section>
          </div>
        </>
      )}
    </>
  );
}

function Library({
  data,
  selectedId,
  select,
  choose,
  act,
  teach,
}: {
  data: Summary;
  selectedId: string;
  select: (id: string) => void;
  choose: (s: Skill) => void;
  act: Act;
  teach: () => void;
}) {
  const [query, setQuery] = useState('');
  const [tab, setTab] = useState<'workflow' | 'json' | 'versions'>('workflow');
  const [versions, setVersions] = useState<Skill[]>([]);
  const skill = data.skills.find((s) => s.id === selectedId);
  useEffect(() => {
    if (skill)
      void api<Skill[]>(`/skills/${skill.id}/versions`)
        .then(setVersions)
        .catch(() => setVersions([]));
  }, [skill?.id, skill?.version]);
  return (
    <>
      <PageTitle
        eyebrow="SEMANTIC SKILL MEMORY"
        title="你的方法，积累成技能。"
        text="语义步骤、参数和版本历史，共同构成 Agent 的工作记忆。"
      >
        <button className="button primary" onClick={teach}>
          <Plus size={16} />
          教授新技能
        </button>
      </PageTitle>
      <div className="library-grid">
        <section>
          <div className="search-field">
            <Search size={16} />
            <input
              aria-label="搜索技能库"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索技能、应用…"
            />
          </div>
          <div className="library-list">
            {data.skills
              .filter((s) => `${s.name} ${s.app}`.toLowerCase().includes(query.toLowerCase()))
              .map((s) => (
                <button
                  className={`library-item ${s.id === selectedId ? 'selected' : ''}`}
                  key={s.id}
                  onClick={() => select(s.id)}
                >
                  <div className="card-top">
                    <Brand app={s.app} small />
                    <Badge>v{s.version}</Badge>
                  </div>
                  <h3>{s.name}</h3>
                  <p>
                    {s.source === 'example' ? '精选示例' : '从示范中学习'} · {s.workflow.length} 步
                  </p>
                  <span className="library-meta">
                    {s.attempts ? `${s.successes} / ${s.attempts} 次执行成功` : '尚未执行'}
                    <ChevronRight size={15} />
                  </span>
                </button>
              ))}
          </div>
        </section>
        {skill ? (
          <section className="panel skill-detail">
            <div className="skill-detail-header">
              <div>
                <Badge tone="green">
                  {skill.source === 'example' ? 'EXAMPLE SKILL' : 'LEARNED SKILL'}
                </Badge>
                <h2>{skill.name}</h2>
                <p>{skill.description}</p>
              </div>
              <button
                className="icon-button"
                aria-label="导出技能 JSON"
                onClick={() => download(`${skill.id}.json`, skill)}
              >
                <Download size={18} />
              </button>
            </div>
            <div className="skill-meta">
              <span>
                <Layers3 size={14} />
                {skill.workflow.length} 语义步骤
              </span>
              <span>
                <Code2 size={14} />
                {skill.parameters.length} 可复用参数
              </span>
              <span>
                <GitBranch size={14} />
                版本 {skill.version}
              </span>
            </div>
            <div className="tabs">
              {(['workflow', 'json', 'versions'] as const).map((t) => (
                <button className={tab === t ? 'active' : ''} key={t} onClick={() => setTab(t)}>
                  {t === 'workflow' ? '语义工作流' : t === 'json' ? 'Skill JSON' : '版本历史'}
                </button>
              ))}
            </div>
            {tab === 'workflow' ? (
              <div className="panel-body">
                <ol className="workflow-list">
                  {skill.workflow.map((step, i) => (
                    <li key={step.id}>
                      <span className="step-number">{String(i + 1).padStart(2, '0')}</span>
                      <div>
                        <b>{step.description}</b>
                        <code>
                          {step.kind}
                          {step.target ? ` · ${step.target.role}("${step.target.name}")` : ''}
                          {step.parameter ? ` → {{${step.parameter}}}` : ''}
                        </code>
                      </div>
                    </li>
                  ))}
                </ol>
                <div className="verify-note">
                  <ShieldCheck size={17} />
                  <div>
                    完成条件<span>{skill.postcondition}</span>
                  </div>
                </div>
                <div className="origin-note">
                  目标来源 <code>{skill.origin}</code>
                </div>
              </div>
            ) : tab === 'json' ? (
              <pre className="json-view">{JSON.stringify(skill, null, 2)}</pre>
            ) : (
              <div className="panel-body version-list">
                {versions.map((v) => (
                  <div key={v.version}>
                    <GitBranch size={18} />
                    <div>
                      <b>Version {v.version}</b>
                      <small>
                        {formatTime(v.updatedAt)} · {v.workflow.length} 步
                      </small>
                    </div>
                    {v.version === skill.version ? (
                      <Badge tone="green">当前版本</Badge>
                    ) : (
                      <button
                        className="button small-button"
                        onClick={() =>
                          void act(() => api(`/skills/${skill.id}/restore`, { version: v.version }))
                        }
                      >
                        恢复此工作流
                      </button>
                    )}
                  </div>
                ))}
                <p className="small-text">恢复会创建一个新版本，保留完整历史与执行统计。</p>
              </div>
            )}
            <div className="detail-footer">
              <button className="button primary" onClick={() => choose(skill)}>
                <Play size={15} />
                使用这个技能
                <ArrowRight size={15} />
              </button>
            </div>
          </section>
        ) : (
          <Empty title="选择一个技能" text="查看参数化的工作流和版本历史。" />
        )}
      </div>
    </>
  );
}

function RunTable({ runs, open }: { runs: Run[]; open: (id: string) => void }) {
  return (
    <table>
      <thead>
        <tr>
          <th>工作流</th>
          <th>环境</th>
          <th>状态</th>
          <th>修复</th>
          <th>时间</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {runs.map((run) => (
          <tr
            key={run.id}
            onClick={() => open(run.id)}
            tabIndex={0}
            onKeyDown={(e) => e.key === 'Enter' && open(run.id)}
          >
            <td>
              <div className="table-task">
                <Brand app={run.app} small />
                <div>
                  <b>{run.skillName}</b>
                  <small>
                    v{run.skillVersion} · {run.steps.length} steps
                  </small>
                </div>
              </div>
            </td>
            <td>{variants[run.variant]}</td>
            <td>
              <Badge
                tone={run.status === 'succeeded' ? 'green' : run.status === 'failed' ? 'amber' : ''}
              >
                {['running', 'queued'].includes(run.status) && <Spinner />}
                {statuses[run.status]}
              </Badge>
            </td>
            <td>{run.repairs ? `${run.repairs} 处` : '—'}</td>
            <td className="time-cell">{formatTime(run.createdAt)}</td>
            <td>
              <ArrowUpRight size={15} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
function Runs({
  data,
  selectedId,
  select,
  act,
}: {
  data: Summary;
  selectedId: string | null;
  select: (id: string | null) => void;
  act: Act;
}) {
  const [run, setRun] = useState<Run | null>(null);
  useEffect(() => {
    if (!selectedId) {
      setRun(null);
      return;
    }
    let alive = true;
    const load = () =>
      api<Run>(`/runs/${selectedId}`)
        .then((r) => {
          if (alive) setRun(r);
        })
        .catch(() => {});
    void load();
    const timer = setInterval(() => void load(), 900);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [selectedId]);
  return (
    <>
      <PageTitle
        eyebrow="OBSERVABLE EXECUTION"
        title={run ? run.skillName : '每一步，都有迹可循。'}
        text={
          run
            ? `执行 ${run.id.slice(0, 8)} · ${variants[run.variant]} · Skill v${run.skillVersion}`
            : '查看页面状态、决策理由、自动修复和最终验证结果。'
        }
      >
        {run ? (
          <button className="button" onClick={() => select(null)}>
            返回全部记录
          </button>
        ) : (
          <Badge tone="outline">{data.runs.length} RUNS</Badge>
        )}
      </PageTitle>
      {run ? (
        <Trace run={run} act={act} />
      ) : data.runs.length ? (
        <div className="table-wrap">
          <RunTable runs={data.runs} open={select} />
        </div>
      ) : (
        <Empty title="还没有执行记录" text="到工作台运行一个技能，完整轨迹会保存在这里。" />
      )}
    </>
  );
}
function Trace({ run, act }: { run: Run; act: Act }) {
  const active = ['running', 'queued'].includes(run.status);
  return (
    <>
      <div className={`run-status-bar ${run.status}`}>
        <span className="run-status-icon">
          {active ? (
            <Spinner />
          ) : run.verified ? (
            <CheckCircle2 size={22} />
          ) : (
            <ShieldCheck size={22} />
          )}
        </span>
        <div>
          <b>
            {statuses[run.status]}
            {run.verified ? ' · 完成条件已通过' : ''}
          </b>
          <span>
            {run.error ||
              (active
                ? '浏览器正在执行语义工作流，轨迹会实时更新。'
                : `执行用时 ${((run.durationMs || 0) / 1000).toFixed(1)}s · ${run.repairs} 处修复`)}
          </span>
        </div>
        {active ? (
          <button
            className="button"
            onClick={() => void act(() => api(`/runs/${run.id}/cancel`, {}))}
          >
            <Square size={14} />
            停止执行
          </button>
        ) : (
          <button className="button" onClick={() => download(`trace-${run.id}.json`, run)}>
            <Download size={15} />
            导出轨迹
          </button>
        )}
      </div>
      <div className="trace-grid">
        <section className="panel">
          <div className="panel-heading">
            <h2>执行轨迹</h2>
            <Badge>LIVE TRACE</Badge>
          </div>
          <div className="trace-list">
            <div className="trace-step">
              <div className="trace-symbol">
                <GitBranch size={16} />
              </div>
              <div>
                <b>选择技能</b>
                <p>{run.decision.reason}</p>
                <Badge>{run.decision.provider === 'jev' ? 'Jev' : 'Local / user'}</Badge>
              </div>
            </div>
            {run.steps.map((step) => (
              <div className={`trace-step ${step.status}`} key={step.index}>
                <div className="trace-symbol">
                  {step.status === 'running' ? (
                    <Spinner />
                  ) : step.status === 'succeeded' ? (
                    <Check size={16} />
                  ) : (
                    <X size={16} />
                  )}
                </div>
                <div className="trace-content">
                  <div className="trace-title">
                    <b>{step.description}</b>
                    <small>{step.durationMs == null ? '执行中' : `${step.durationMs}ms`}</small>
                  </div>
                  {step.repair && (
                    <div className="repair-detail">
                      <WandSparkles size={14} />
                      <code>{step.repair.from.name}</code>
                      <ArrowRight size={12} />
                      <code>{step.repair.to.name}</code>
                    </div>
                  )}
                  {step.error && <p className="trace-error">{step.error}</p>}
                  {step.decision && <p>{step.decision.reason}</p>}
                  {step.before && (
                    <details>
                      <summary>页面观察 · {step.before.elements.length} 个元素</summary>
                      <pre>{JSON.stringify(step.before, null, 2)}</pre>
                    </details>
                  )}
                </div>
              </div>
            ))}
            {run.verified && (
              <div className="trace-step succeeded">
                <div className="trace-symbol">
                  <ShieldCheck size={17} />
                </div>
                <div>
                  <b>验证完成</b>
                  <p>
                    {run.repairs
                      ? '新的语义目标已验证，修复已保存为新版本。'
                      : '页面显示预期完成文本。'}
                  </p>
                </div>
              </div>
            )}
          </div>
        </section>
        <section className="panel result-panel">
          <div className="panel-heading">
            <h2>浏览器结果</h2>
            <Eye size={16} />
          </div>
          {run.screenshot ? (
            <a href={run.screenshot} target="_blank" rel="noreferrer">
              <img src={run.screenshot} alt="执行完成或停止时的浏览器截图" />
            </a>
          ) : (
            <Empty
              title={active ? '正在执行…' : '暂无截图'}
              text="执行结束后显示浏览器的实际页面。"
            />
          )}
          <div className="result-details">
            <div>
              <span>策略提供方</span>
              <b>
                {run.steps.some((s) => s.decision?.provider === 'jev') ? 'Jev API' : 'Local policy'}
              </b>
            </div>
            <div>
              <span>自动修复</span>
              <b>{run.repairEnabled ? '已启用' : '已关闭 · 基线'}</b>
            </div>
            <div>
              <span>结果验证</span>
              <b>{run.verified ? '通过' : '未通过 / 待验证'}</b>
            </div>
          </div>
        </section>
      </div>
    </>
  );
}

function Evaluations({
  data,
  act,
  openRun,
}: {
  data: Summary;
  act: Act;
  openRun: (id: string) => void;
}) {
  const latest = data.evaluations[0];
  const [busy, setBusy] = useState(false);
  async function evaluate() {
    setBusy(true);
    await act(() => api<Evaluation>('/evaluations', {}));
    setBusy(false);
  }
  const running = latest?.status === 'running';
  return (
    <>
      <PageTitle
        eyebrow="REPRODUCIBLE BY DESIGN"
        title="让结果说话。"
        text="用同一技能、同一输入，比较固定回放与自适应执行。"
      >
        <button
          className="button primary"
          disabled={busy || running}
          onClick={() => void evaluate()}
        >
          {busy || running ? <Spinner /> : <Play size={16} />}运行完整评测
        </button>
      </PageTitle>
      <div className="evaluation-intro">
        <div className="eval-icon">
          <FlaskConical size={29} />
        </div>
        <div>
          <h2>3 个任务 × 4 种页面条件 × 2 种策略</h2>
          <p>
            24 次真实 Playwright 执行。每次使用独立浏览器页面，评测记录与日常工作流统计分开保存。
          </p>
        </div>
        <Badge tone="outline">LOCAL BENCHMARK</Badge>
      </div>
      <div className="stats-grid">
        <Stat
          label="固定回放成功率"
          value={percentage(latest?.metrics?.baselineSuccess)}
          note="不启用语义修复 · 9 个可执行任务"
          icon={<Play size={16} />}
        />
        <Stat
          label="自适应执行成功率"
          value={percentage(latest?.metrics?.adaptiveSuccess)}
          note="启用语义修复 · 9 个可执行任务"
          icon={<Sparkles size={16} />}
        />
        <Stat
          label="按钮更名修复率"
          value={percentage(latest?.metrics?.repairSuccess)}
          note="3 个更名任务 · 须通过结果验证"
          icon={<WandSparkles size={16} />}
        />
        <Stat
          label="歧义安全停止率"
          value={percentage(latest?.metrics?.safeAbstention)}
          note="3 个歧义任务 · 停止才算正确"
          icon={<ShieldCheck size={16} />}
        />
      </div>
      {running && (
        <div className="eval-progress">
          <div>
            <Spinner />
            <b>正在运行受控实验</b>
            <span>{latest.rows.length} / 12 组已完成</span>
          </div>
          <progress value={latest.rows.length} max={12} />
          <p>页面更名测试会先等待原始目标超时，再检查修复策略。通常需要 1–3 分钟。</p>
        </div>
      )}
      {latest?.error && (
        <p className="notice" role="alert">
          {latest.error}
        </p>
      )}
      {latest?.rows.length ? (
        <section className="section">
          <div className="section-heading">
            <div>
              <h2>实验结果</h2>
              <p>{formatTime(latest.createdAt)} · 每个结果均可打开对应轨迹。</p>
            </div>
            <button
              className="button"
              onClick={() => download(`evaluation-${latest.id}.json`, latest)}
            >
              <Download size={15} />
              导出结果
            </button>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>任务</th>
                  <th>页面条件</th>
                  <th>固定回放</th>
                  <th>自适应执行</th>
                  <th>适应结果</th>
                </tr>
              </thead>
              <tbody>
                {latest.rows.map((row) => (
                  <tr key={`${row.app}-${row.variant}`}>
                    <td>
                      <div className="table-task">
                        <Brand app={row.app} small />
                        <b>{row.app}</b>
                      </div>
                    </td>
                    <td>{variants[row.variant]}</td>
                    <td>
                      <button className="table-link" onClick={() => openRun(row.baselineRunId)}>
                        <Badge tone={row.baseline ? 'green' : 'amber'}>
                          {row.baseline ? '通过验证' : '已停止'}
                        </Badge>
                        <ArrowUpRight size={12} />
                      </button>
                    </td>
                    <td>
                      <button className="table-link" onClick={() => openRun(row.adaptiveRunId)}>
                        <Badge tone={row.adaptive ? 'green' : 'amber'}>
                          {row.adaptive ? '通过验证' : '已停止'}
                        </Badge>
                        <ArrowUpRight size={12} />
                      </button>
                    </td>
                    <td>
                      {row.repaired
                        ? '语义修复成功'
                        : row.safelyAbstained
                          ? '✓ 正确识别歧义'
                          : row.adaptive
                            ? '直接复用'
                            : '未完成'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : (
        !running && (
          <Empty
            title="先测量，再下结论。"
            text="运行评测后，所有指标由实际轨迹计算，不使用预填的展示数字。"
          />
        )
      )}
      <div className="methodology">
        <h3>
          <BarChart3 size={18} />
          如何解读这些数字
        </h3>
        <p>
          原始页面测试基本执行能力，布局调整测试语义定位，按钮更名测试修复能力。歧义页面单独衡量正确停止，不计入任务成功率。基线是固定语义回放，不代表通用
          LLM Agent；当前结果只覆盖这三个受控练习应用。评测始终使用本地策略，不消耗 Jev API。
        </p>
      </div>
    </>
  );
}

function Settings({ data }: { data: Summary }) {
  return (
    <>
      <PageTitle
        eyebrow="YOUR LOCAL ENVIRONMENT"
        title="保持简单，随时扩展。"
        text="本地模式开箱即用。准备好后，再连接真实浏览器和 Jev 决策服务。"
      />
      <div className="settings-grid">
        <section className="panel">
          <div className="panel-heading">
            <h2>
              <GitBranch size={18} />
              决策策略
            </h2>
            <Badge tone="green">
              {data.config.policy === 'jev' ? 'Jev API 已配置' : 'Local policy'}
            </Badge>
          </div>
          <div className="panel-body">
            <h3>有限候选，明确决策。</h3>
            <p className="body-copy">
              本地策略使用可解释的语义特征分数，不调用模型。配置 Jev
              后，技能选择、动作确认和修复选择会调用真实 API；低置信度、超时或无效响应会停止执行。
            </p>
            <pre className="config-code">{`# 项目根目录 .env\nTYPESAFE_API_KEY=your_key_here\nJEV_MODEL=jev-latest`}</pre>
            <p className="small-text">
              修改后重启服务。密钥只从服务端环境读取，不发送给浏览器。Jev
              会收到任务描述、技能名称与描述、操作名称及候选标签；不会收到字段值或截图。
            </p>
          </div>
        </section>
        <section className="panel">
          <div className="panel-heading">
            <h2>
              <MousePointer2 size={18} />
              浏览器运行时
            </h2>
            <Badge>{data.config.browserChannel}</Badge>
          </div>
          <div className="panel-body">
            <h3>Playwright · 语义定位</h3>
            <p className="body-copy">
              通过元素角色与可访问名称定位页面。教学只在明确启动后启用，外部页面使用新的独立浏览器窗口。
            </p>
            <pre className="config-code">{`BROWSER_CHANNEL=chrome\nALLOWED_ORIGINS=https://your-app.example.com\nBROWSER_STORAGE_STATE=./data/auth.json`}</pre>
            <div className="origin-list">
              <b>当前授权来源</b>
              {data.config.allowedOrigins.map((origin) => (
                <code key={origin}>
                  <span className="status-dot" />
                  {origin}
                </code>
              ))}
            </div>
            <p className="small-text">
              运行 npm run auth -- https://your-app.example.com
              可在独立窗口自行登录并保存登录态。通过 BROWSER_STORAGE_STATE
              显式启用；每次执行只载入目标来源的凭据。跨域流程及任意桌面操作不在当前 MVP 范围内。
            </p>
          </div>
        </section>
        <section className="panel data-panel">
          <div className="panel-heading">
            <h2>
              <ShieldCheck size={18} />
              记忆与可追溯性
            </h2>
            <Badge>LOCAL-FIRST</Badge>
          </div>
          <div className="panel-body data-columns">
            <div>
              <b>SQLite 持久化</b>
              <p>技能、示范、执行轨迹和偏好写入 data/skillcua.sqlite。</p>
            </div>
            <div>
              <b>验证后才更新</b>
              <p>修复只有通过完成条件，才会写入新的 Skill 版本。</p>
            </div>
            <div>
              <b>可导出、可恢复</b>
              <p>技能和轨迹可导出为 JSON，历史工作流可恢复为新版本。</p>
            </div>
          </div>
        </section>
      </div>
    </>
  );
}
