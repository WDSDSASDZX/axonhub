import { useEffect, useRef, useState } from 'react';
import { useAuthStore } from '@/stores/authStore';
import { Button } from '@/components/ui/button';
import { Main } from '@/components/layout/main';
import { AggregatePanel } from './aggregate';
import './personal.css';
import { SmsLogin } from './sms-login';

type Row = Record<string, unknown>;
type Budget = {
  channel_id: number;
  source: string;
  observed_at: string;
  models: string[];
  protect_permanent: boolean;
  upstream_expiry_first: boolean;
  enabled?: boolean;
  buckets: { remaining: number; unit: string; expires_at?: string }[];
};
type Policy = { expires_at: string; rules: { channel_id: number; eligible: boolean; reason: string; priority: number }[] };
type Status = { dsh_url: string; budgets: Budget[]; policy: Policy };
const providers = [
  ['codearts', '华为 CodeArts'],
  ['buddy', '腾讯 CodeBuddy'],
  ['workbuddy', 'WorkBuddy'],
  ['lobsterai', '有道 LobsterAI'],
  ['qoder', 'Qoder'],
  ['qodercn', 'Qoder 中国版'],
  ['trae', 'TRAE'],
  ['cline', 'Cline'],
  ['loomy', '讯飞 Loomy'],
  ['raccoon', '商汤 Raccoon'],
  ['minimax', 'MiniMax'],
  ['minimaxintl', 'MiniMax 国际版'],
  ['zcode', 'ZCode'],
  ['gemini', 'Gemini Code Assist'],
  ['officeace', 'OfficeAce'],
  ['accio', 'Accio'],
  ['modelscope', 'ModelScope'],
  ['autoclaw', 'AutoClaw'],
  ['astudio', 'AStudio'],
  ['opencode', 'OpenCode'],
  ['autoclawintl', 'AutoClaw 国际版'],
  ['codely', 'Codely'],
];
function rows(value: unknown, key: string): Row[] {
  if (!value || typeof value !== 'object') return [];
  const list = (value as Row)[key];
  return Array.isArray(list) ? (list as Row[]) : [];
}
const text = (value: unknown, fallback = '—') => (value == null ? fallback : String(value));
const when = (value: unknown) => (value ? new Date(value as string | number).toLocaleString() : '未知');

export default function PersonalHub() {
  const token = useAuthStore((s) => s.auth.accessToken);
  const owner = useAuthStore((s) => s.auth.user?.isOwner);
  const [tab, setTab] = useState('accounts');
  const [provider, setProvider] = useState('codearts');
  const [accounts, setAccounts] = useState<Row[]>([]);
  const [models, setModels] = useState<Row[]>([]);
  const [balances, setBalances] = useState<Row[]>([]);
  const [status, setStatus] = useState<Status>();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [failed, setFailed] = useState(false);
  const [login, setLogin] = useState<Row>();
  const generation = useRef(0);
  const [locked, setLocked] = useState<boolean | null>(null);
  const [autoCheckin, setAutoCheckin] = useState<boolean | null>(null);
  const [form, setForm] = useState({ channel: '', models: '*', amount: '', unit: '积分', expiry: '', protect: true, guarantee: false });

  async function api(path: string, body?: unknown) {
    const response = await fetch('/admin/personal' + path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '操作失败');
    return data;
  }
  async function rpc(method: string, payload: Row = {}) {
    return api('/rpc', { method, payload });
  }
  async function refresh(selected = provider) {
    const current = ++generation.current;
    const [a, m, s] = await Promise.all([
      rpc('account.list', { provider: selected }),
      rpc('model.list', { provider: selected }),
      api('/status'),
    ]);
    if (current !== generation.current) return;
    setAccounts(rows(a, 'accounts'));
    setModels(rows(m, 'models'));
    setStatus(s);
  }
  async function run(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setMessage('正在处理…');
    setFailed(false);
    try {
      await action();
      setMessage('操作已完成');
    } catch (e) {
      setFailed(true);
      setMessage(e instanceof Error ? e.message : '操作失败');
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (!owner) return;
    setAccounts([]);
    setModels([]);
    setBalances([]);
    setLocked(null);
    setLogin(undefined);
    void run(() => refresh(provider));
    return () => {
      generation.current++; // eslint-disable-line react-hooks/exhaustive-deps -- Request counter, not a DOM ref.
    };
  }, [provider, owner]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!login?.accountId) return;
    let cancelled = false;
    let attempts = 0;
    const timer = window.setInterval(() => {
      if (++attempts > 150) {
        setFailed(true);
        setMessage('登录等待超时，请重试');
        setLogin(undefined);
        return;
      }
      void rpc('login.poll', { accountId: login.accountId })
        .then((result) => {
          if (cancelled || !result?.done) return;
          setLogin(undefined);
          if (!result.success) {
            setFailed(true);
            setMessage(text(result.error, '登录未完成'));
            return;
          }
          setMessage('登录成功');
          void refresh();
        })
        .catch((e) => {
          if (!cancelled) {
            setFailed(true);
            setMessage(e.message);
            setLogin(undefined);
          }
        });
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [login?.accountId]); // eslint-disable-line react-hooks/exhaustive-deps

  function startLogin() {
    // Open inside the click gesture, before awaiting the RPC.
    const popup = window.open('about:blank', '_blank');
    void run(async () => {
      try {
        const result = await rpc('account.create', { provider });
        setLogin(result || {});
        if (result?.loginUrl) {
          const target = new URL(result.loginUrl);
          if (!['http:', 'https:'].includes(target.protocol)) throw new Error('无效的授权地址');
          if (popup) popup.location.href = target.href;
        } else popup?.close();
        if (!result?.accountId) throw new Error('当前平台需要在 Jet Hub 原生页面完成登录');
      } catch (e) {
        popup?.close();
        throw e;
      }
    });
  }
  async function accountAction(method: string, accountId: unknown, extra: Row = {}) {
    const result = await rpc(method, { provider, accountId, ...extra });
    if (result?.success === false || result?.ok === false || result?.error) throw new Error(text(result.error, '账号操作失败'));
    await refresh();
  }
  async function move(index: number) {
    if (index < 1) return;
    const reordered = [...accounts];
    [reordered[index - 1], reordered[index]] = [reordered[index], reordered[index - 1]];
    await rpc('account.reorder', { provider, orderedIds: reordered.map((a) => a.id) });
    await refresh();
  }
  async function saveBudget() {
    if (!status || !form.channel || !form.amount) throw new Error('请填写渠道 ID 和额度');
    const next: Budget = {
      channel_id: Number(form.channel),
      source: 'manual',
      observed_at: new Date().toISOString(),
      models: form.models
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
      protect_permanent: form.protect,
      upstream_expiry_first: form.guarantee,
      buckets: [
        { remaining: Number(form.amount), unit: form.unit, ...(form.expiry ? { expires_at: new Date(form.expiry).toISOString() } : {}) },
      ],
    };
    await api('/budgets', { accounts: [...status.budgets.filter((b) => b.channel_id !== next.channel_id), next] });
    setStatus(await api('/status'));
  }
  if (!owner)
    return (
      <Main>
        <p>此页面仅供个人管理员使用。</p>
      </Main>
    );

  return (
    <Main className='personal-hub'>
      <div className='ph-heading'>
        <div>
          <span className='ph-eyebrow'>AXONHUB PERSONAL</span>
          <h1>我的模型工作台</h1>
          <p>统一管理账号、模型与额度，让可用额度用在合适的渠道。</p>
        </div>
        <Button
          disabled={busy}
          onClick={() =>
            void run(async () => {
              const result = await api('/connect', {});
              await refresh();
              window.alert('已连接 Jet Hub，渠道 ID：' + result.id + '，模型：' + result.models);
            })
          }
        >
          连接 Jet Hub 到网关
        </Button>
      </div>
      <div className='ph-notice'>平台授权和账号续期由本机 Jet Hub 处理，客户端请求由 Go 网关转发。</div>
      {message && (
        <div role={failed ? 'alert' : 'status'} className={failed ? 'ph-error' : 'ph-message'}>
          {message}
        </div>
      )}
      <div className='ph-toolbar'>
        <nav aria-label='工作台页面'>
          {[
            ['accounts', '账号与额度'],
            ['models', '模型目录'],
            ['aggregate', '跨渠道聚合'],
            ['policy', '额度策略'],
          ].map(([id, label]) => (
            <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>
              {label}
            </button>
          ))}
        </nav>
        {tab !== 'policy' && tab !== 'aggregate' && (
          <label>
            平台{' '}
            <select value={provider} disabled={busy} onChange={(e) => setProvider(e.target.value)}>
              {providers.map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {tab === 'accounts' && (
        <>
          <section className='ph-card'>
            <div className='ph-section'>
              <div>
                <h2>账号池</h2>
                <p>按顺序选择可用账号，续期由插件自动处理。</p>
              </div>
              <div className='ph-actions'>
                <Button variant='outline' disabled={busy} onClick={() => void run(() => refresh())}>
                  刷新
                </Button>
                <Button disabled={busy} onClick={startLogin}>
                  添加账号
                </Button>
              </div>
            </div>
            {login && (
              <div className='ph-notice'>
                请在授权页面完成登录。
                {Boolean(login.loginUrl) && (
                  <a href={text(login.loginUrl)} target='_blank' rel='noreferrer'>
                    打开授权页面
                  </a>
                )}
                <Button variant='outline' onClick={() => setLogin(undefined)}>
                  停止等待
                </Button>
                {Boolean(login.userCode) && <p>设备验证码：{text(login.userCode)}</p>}
                {['loomy', 'autoclaw'].includes(provider) && Boolean(login.accountId) && (
                  <SmsLogin
                    provider={provider}
                    accountId={text(login.accountId)}
                    rpc={rpc}
                    onComplete={() => {
                      setLogin(undefined);
                      void refresh();
                    }}
                  />
                )}
              </div>
            )}
            {!accounts.length ? (
              <p className='ph-empty'>此平台暂无账号。添加后可管理登录状态、优先级和额度。</p>
            ) : (
              <div className='ph-account-list'>
                {accounts.map((a, i) => (
                  <article className='ph-account' key={text(a.id)}>
                    <div>
                      <strong>{text(a.nickname, text(a.id))}</strong>
                      <small>{text(a.id)}</small>
                      <span className={a.enabled === false ? 'ph-muted' : 'ph-good'}>{a.enabled === false ? '已停用' : '已启用'}</span>
                      <small>
                        凭据到期：{when(a.expiresAt)} · {a.refreshable ? '支持自动续期' : '续期能力以平台为准'}
                      </small>
                    </div>
                    <div className='ph-actions'>
                      <Button variant='outline' disabled={busy || i === 0} onClick={() => void run(() => move(i))}>
                        上移
                      </Button>
                      <Button variant='outline' disabled={busy} onClick={() => void run(() => accountAction('account.test', a.id))}>
                        测试
                      </Button>
                      <Button variant='outline' disabled={busy} onClick={() => void run(() => accountAction('account.refresh', a.id))}>
                        续期
                      </Button>
                      <Button
                        variant='outline'
                        disabled={busy}
                        onClick={() => void run(() => accountAction('account.update', a.id, { patch: { enabled: a.enabled === false } }))}
                      >
                        {a.enabled === false ? '启用' : '停用'}
                      </Button>
                      <Button
                        variant='outline'
                        disabled={busy}
                        onClick={() => {
                          if (window.confirm('从 Jet Hub 删除此账号？')) void run(() => accountAction('account.delete', a.id));
                        }}
                      >
                        删除
                      </Button>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
          <section className='ph-card'>
            <div className='ph-section'>
              <div>
                <h2>额度与签到</h2>
                <p>余额由平台返回；积分、Token 等不同单位分别显示。</p>
              </div>
              <div className='ph-actions'>
                <Button
                  variant='outline'
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      const result = await rpc('credits.balances', { provider, force: true });
                      setBalances(rows(result, 'accounts'));
                    })
                  }
                >
                  查询余额
                </Button>
                <Button
                  variant='outline'
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      const result = await rpc('credits.claimAll', { provider });
                      const outcomes = rows(result, 'results');
                      if (outcomes.length)
                        window.alert(
                          outcomes
                            .map((r) => text(r.nickname, r.accountId as string) + ': ' + text(r.message, r.status as string))
                            .join('\n')
                        );
                    })
                  }
                >
                  领取今日额度
                </Button>
                <Button
                  variant='outline'
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      const result = await rpc('credits.permanentLock', { provider, ...(locked === null ? {} : { locked: !locked }) });
                      setLocked(Boolean(result.locked));
                    })
                  }
                >
                  {locked === null ? '查看永久额度保护' : locked ? '已保护 · 点击解锁' : '未保护 · 点击锁定'}
                </Button>
                <Button
                  variant='outline'
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      const result = await rpc('usage.autoCheckin', autoCheckin === null ? {} : { enabled: !autoCheckin });
                      setAutoCheckin(Boolean(result.enabled));
                    })
                  }
                >
                  {autoCheckin === null ? '查看自动签到' : autoCheckin ? '自动签到已开 · 点击关闭' : '自动签到已关 · 点击开启'}
                </Button>
              </div>
            </div>
            {!balances.length ? (
              <p className='ph-empty'>点击查询余额。不支持的操作会显示平台返回的原因。</p>
            ) : (
              balances.map((b, i) => (
                <div className='ph-reading' key={text(b.accountId, String(i))}>
                  <strong>{text(b.nickname, text(b.accountId))}</strong>
                  {Boolean(b.error) && <p role='alert'>{text(b.error)}</p>}
                  <Balance value={b.balance} />
                </div>
              ))
            )}
          </section>
        </>
      )}

      {tab === 'aggregate' && <AggregatePanel rpc={rpc} />}
      {tab === 'models' && (
        <section className='ph-card'>
          <div className='ph-section'>
            <div>
              <h2>模型目录</h2>
              <p>开关直接写入 Jet Hub，影响插件网关的模型可用列表。</p>
            </div>
            <Button variant='outline' disabled={busy} onClick={() => void run(() => refresh())}>
              同步目录
            </Button>
          </div>
          {!models.length ? (
            <p className='ph-empty'>当前没有可用模型，请先登录账号并刷新。</p>
          ) : (
            <div className='ph-model-grid'>
              {models.map((m) => (
                <article className='ph-model' key={text(m.id)}>
                  <div>
                    <strong>{text(m.name, text(m.id))}</strong>
                    <small>{text(m.id)}</small>
                    {Boolean(m.dead) && <small>上游已标记失效</small>}
                  </div>
                  <label>
                    <input
                      type='checkbox'
                      aria-label={'开放 ' + text(m.id)}
                      checked={!m.disabled}
                      disabled={busy}
                      onChange={(e) =>
                        void run(async () => {
                          await rpc('model.setDisabled', { provider, modelId: m.id, disabled: !e.target.checked });
                          await refresh();
                        })
                      }
                    />{' '}
                    开放
                  </label>
                </article>
              ))}
            </div>
          )}
        </section>
      )}

      {tab === 'policy' && (
        <>
          <section className='ph-card'>
            <h2>临期额度优先</h2>
            <p>Jet Hub 内部账号由插件调度；这里的策略用于 AxonHub 的直接渠道。手动额度仅供短期验证，五分钟后需重新确认。</p>
            <form
              className='ph-form'
              onSubmit={(e) => {
                e.preventDefault();
                void run(saveBudget);
              }}
            >
              <label>
                渠道 ID
                <input
                  required
                  type='number'
                  min='1'
                  value={form.channel}
                  onChange={(e) => setForm({ ...form, channel: e.target.value })}
                />
              </label>
              <label>
                模型（逗号分隔，* 为全部）
                <input required value={form.models} onChange={(e) => setForm({ ...form, models: e.target.value })} />
              </label>
              <label>
                剩余额度
                <input
                  required
                  type='number'
                  min='0'
                  step='any'
                  value={form.amount}
                  onChange={(e) => setForm({ ...form, amount: e.target.value })}
                />
              </label>
              <label>
                单位
                <input required value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} />
              </label>
              <label>
                到期时间（留空代表长期额度）
                <input type='datetime-local' value={form.expiry} onChange={(e) => setForm({ ...form, expiry: e.target.value })} />
              </label>
              <label className='ph-check'>
                <input type='checkbox' checked={form.protect} onChange={(e) => setForm({ ...form, protect: e.target.checked })} />{' '}
                仅使用临期额度
              </label>
              <label className='ph-check'>
                <input type='checkbox' checked={form.guarantee} onChange={(e) => setForm({ ...form, guarantee: e.target.checked })} />{' '}
                已确认上游优先扣临期额度
              </label>
              <Button type='submit' disabled={busy || !status}>
                保存并应用
              </Button>
            </form>
          </section>
          <section className='ph-card'>
            <h2>当前策略</h2>
            <p>数据过期或后台停止时，受策略管理的渠道会停止派发；其他渠道继续使用原路由。</p>
            {!status?.policy.rules.length ? (
              <p className='ph-empty'>尚未管理直接渠道。你仍可使用 Jet Hub 的账号池与临期调度。</p>
            ) : (
              status.policy.rules.map((r) => (
                <div className='ph-policy' key={r.channel_id}>
                  <div>
                    <strong>渠道 {r.channel_id}</strong>
                    <span className={r.eligible ? 'ph-good' : 'ph-muted'}>{r.eligible ? '可使用' : '已排除'}</span>
                    <small>{r.reason}</small>
                  </div>
                  <Button
                    variant='outline'
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        await api('/budgets', { accounts: status.budgets.filter((b) => b.channel_id !== r.channel_id) });
                        setStatus(await api('/status'));
                      })
                    }
                  >
                    解除策略管理
                  </Button>
                </div>
              ))
            )}
          </section>
        </>
      )}
    </Main>
  );
}

function Balance({ value }: { value: unknown }) {
  if (value == null) return <p>余额未知</p>;
  if (typeof value !== 'object') return <p>{text(value)}</p>;
  const labels: Record<string, string> = {
    total: '总额',
    balance: '余额',
    remaining: '剩余',
    temporary: '临期',
    permanent: '长期',
    unit: '单位',
    expiresAt: '到期时间',
    amount: '额度',
    tokens: 'Token',
  };
  return (
    <div className='ph-balance'>
      {Object.entries(value as Row)
        .filter(([, v]) => v != null)
        .map(([k, v]) =>
          typeof v === 'object' ? (
            <div key={k}>
              <span>{labels[k] || k}</span>
              <Balance value={v} />
            </div>
          ) : (
            <span key={k}>
              {labels[k] || k}：{k.toLowerCase().includes('expire') ? when(v) : text(v)}
            </span>
          )
        )}
    </div>
  );
}
