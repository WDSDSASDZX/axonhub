import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';

type Candidate = { provider: string; realId: string; realName: string; state: string; expiryWired: boolean };
type Model = { canonicalId: string; name: string; candidates: Candidate[]; order: string[] };
type Catalog = { models: Model[]; orderMode: 'expiry' | 'manual' };

export function AggregatePanel({ rpc }: { rpc: (method: string, payload?: Record<string, unknown>) => Promise<unknown> }) {
  const [catalog, setCatalog] = useState<Catalog>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function load() {
    setCatalog((await rpc('aggregate.catalog', { force: true })) as Catalog);
  }
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : '操作失败');
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    void run(load);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  async function move(model: Model, index: number) {
    const candidates = [...model.candidates];
    [candidates[index - 1], candidates[index]] = [candidates[index], candidates[index - 1]];
    await rpc('aggregate.setOrder', {
      canonicalId: model.canonicalId,
      order: candidates.map((c) => c.provider + String.fromCharCode(0) + c.realId),
    });
    await load();
  }
  return (
    <section className='ph-card'>
      <div className='ph-section'>
        <div>
          <h2>跨渠道模型聚合</h2>
          <p>将同一个模型的多个渠道组成候选池，由 Jet Hub 按临期额度或手动顺序选择。</p>
        </div>
        <div className='ph-actions'>
          <Button variant='outline' disabled={busy} onClick={() => void run(load)}>
            刷新候选
          </Button>
          <Button
            variant='outline'
            disabled={busy || !catalog}
            onClick={() =>
              void run(async () => {
                await rpc('aggregate.setOrderMode', { mode: catalog?.orderMode === 'expiry' ? 'manual' : 'expiry' });
                await load();
              })
            }
          >
            {catalog?.orderMode === 'manual' ? '当前手动排序 · 切换临期优先' : '当前临期优先 · 切换手动排序'}
          </Button>
        </div>
      </div>
      {error && (
        <p role='alert' className='ph-error'>
          {error}
        </p>
      )}
      {!catalog?.models.length ? (
        <p className='ph-empty'>暂无聚合模型。请先登录支持的渠道并刷新。</p>
      ) : (
        catalog.models.map((model) => (
          <div className='ph-reading' key={model.canonicalId}>
            <strong>{model.name}</strong>
            <small className='block'>{model.canonicalId}</small>
            {model.candidates.map((candidate, i) => (
              <div className='ph-model' key={candidate.provider + '/' + candidate.realId}>
                <div>
                  <strong>{candidate.provider}</strong>
                  <small>{candidate.realName || candidate.realId}</small>
                  <small>
                    {candidate.state === 'allowed'
                      ? '参与轮换'
                      : candidate.state === 'default-rejected'
                        ? '额度到期信息未知，默认不参与'
                        : '已排除'}
                  </small>
                </div>
                <div className='ph-actions'>
                  {catalog.orderMode === 'manual' && (
                    <Button variant='outline' disabled={busy || i === 0} onClick={() => void run(() => move(model, i))}>
                      上移
                    </Button>
                  )}
                  <label>
                    <input
                      type='checkbox'
                      disabled={busy}
                      checked={candidate.state === 'allowed'}
                      onChange={(e) => {
                        const checked = e.target.checked;
                        void run(async () => {
                          await rpc(candidate.expiryWired ? 'aggregate.setRejected' : 'aggregate.setAllowed', {
                            canonicalId: model.canonicalId,
                            provider: candidate.provider,
                            realId: candidate.realId,
                            ...(candidate.expiryWired ? { rejected: !checked } : { allowed: checked }),
                          });
                          await load();
                        });
                      }}
                    />{' '}
                    参与轮换
                  </label>
                </div>
              </div>
            ))}
          </div>
        ))
      )}
    </section>
  );
}
