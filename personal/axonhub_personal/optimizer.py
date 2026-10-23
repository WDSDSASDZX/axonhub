"""Expiry-aware channel policies. Amounts in different units are never added."""
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

def instant(value):
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("时间必须包含时区")
    return parsed.astimezone(timezone.utc)

def validate(accounts):
    if not isinstance(accounts, list) or len(accounts) > 500:
        raise ValueError("accounts 必须是数组，最多 500 项")
    seen = set()
    for a in accounts:
        if not isinstance(a, dict):
            raise ValueError("账号必须为对象")
        cid = a.get("channel_id")
        if type(cid) is not int or cid <= 0 or cid in seen:
            raise ValueError("channel_id 必须为不重复的正整数")
        seen.add(cid)
        if not isinstance(a.get("models", ["*"]), list) or not a.get("models", ["*"]) or not all(isinstance(m, str) and m for m in a.get("models", ["*"])):
            raise ValueError("models 必须为模型名称数组")
        if a.get("source") not in ("manual", "provider"):
            raise ValueError("必须注明 manual 或 provider 数据来源")
        stamp = instant(a["observed_at"])
        if stamp is None:
            raise ValueError("缺少采集时间")
        if not isinstance(a.get("buckets"), list):
            raise ValueError("缺少额度桶")
        for name in ("protect_permanent", "upstream_expiry_first", "enabled"):
            if name in a and type(a[name]) is not bool:
                raise ValueError("策略开关必须为布尔值")
        for b in a["buckets"]:
            if not isinstance(b, dict):
                raise ValueError("额度桶必须为对象")
            amount = b.get("remaining")
            if type(amount) not in (int, float) or not math.isfinite(amount) or amount < 0:
                raise ValueError("余额必须是有限非负数，未知余额不能写成 0")
            if not b.get("unit") or not isinstance(b["unit"], str):
                raise ValueError("每个额度桶必须有单位")
            instant(b.get("expires_at"))
    return accounts

def optimize(accounts, now=None):
    now = now or datetime.now(timezone.utc)
    validate(accounts)
    ranked = []
    for a in accounts:
        protected = a.get("protect_permanent", False)
        fresh = timedelta(0) <= now - instant(a["observed_at"]) <= timedelta(seconds=300)
        live = [b for b in a["buckets"] if b["remaining"] > 0 and
                (instant(b.get("expires_at")) is None or instant(b["expires_at"]) > now)]
        expiring = [b for b in live if instant(b.get("expires_at")) is not None]
        # A mixed wallet is not safe merely because it contains temporary credit.
        safe = bool(expiring) and (not any(b.get("expires_at") is None for b in live)
                                 or a.get("upstream_expiry_first") is True)
        eligible = a.get("enabled", True) and bool(live) and fresh and (not protected or safe)
        reason = ("额度信息已过期，请重新采集" if not fresh else
                  "账号已停用" if not a.get("enabled", True) else
                  "没有可用额度" if not live else
                  "无法保证只消耗临期额度" if protected and not safe else
                  "优先使用即将到期的额度" if expiring else "长期额度，排在临期额度之后")
        expiry = min((instant(b["expires_at"]) for b in expiring), default=datetime.max.replace(tzinfo=timezone.utc))
        ranked.append((expiry, a["channel_id"], {
            "channel_id": a["channel_id"], "models": a.get("models", ["*"]),
            "eligible": bool(eligible), "require_fresh": True, "reason": reason,
        }))
    ranked.sort(key=lambda x: (x[0], x[1]))
    rules = [dict(row[2], priority=i) for i, row in enumerate(ranked)]
    return {"version": 1, "generated_at": now.isoformat(), "expires_at": (now + timedelta(seconds=90)).isoformat(), "rules": rules}

def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(value, f, ensure_ascii=False, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)

