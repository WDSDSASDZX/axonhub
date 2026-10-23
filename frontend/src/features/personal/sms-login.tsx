import { useState } from 'react';
import { Button } from '@/components/ui/button';

export function SmsLogin({
  provider,
  accountId,
  rpc,
  onComplete,
}: {
  provider: string;
  accountId: string;
  rpc: (method: string, payload: Record<string, unknown>) => Promise<unknown>;
  onComplete: () => void;
}) {
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  async function send(submit: boolean) {
    setBusy(true);
    setMessage('');
    try {
      const result = (await rpc(submit ? 'login.submitSms' : 'login.sendSms', {
        provider,
        accountId,
        phone,
        ...(submit ? { code } : {}),
      })) as { error?: string; done?: boolean };
      if (result?.error) throw new Error(result.error);
      setMessage(submit ? '已提交验证码' : '验证码已发送');
      if (result?.done) onComplete();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : '短信操作失败');
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className='ph-form'>
      <label>
        手机号
        <input aria-label='手机号' autoComplete='tel' value={phone} onChange={(e) => setPhone(e.target.value)} />
      </label>
      <Button disabled={busy || !phone} onClick={() => void send(false)}>
        发送验证码
      </Button>
      <label>
        短信验证码
        <input aria-label='短信验证码' autoComplete='one-time-code' value={code} onChange={(e) => setCode(e.target.value)} />
      </label>
      <Button disabled={busy || !code} onClick={() => void send(true)}>
        完成登录
      </Button>
      {message && <p role='status'>{message}</p>}
    </div>
  );
}
