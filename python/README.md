# AxonHub Python

基于 [AxonHub](https://github.com/looplj/axonhub) 的设计实现的精简 Python 网关。
这里逐步实现异步转发、客户端鉴权、渠道选择和请求记录；原 Go 版本仍在仓库根目录。

需要 Python 3.12+ 和 uv：

```bash
cd python
uv sync --locked
uv run axonhub
```

服务默认绑定 `127.0.0.1:8091`，健康检查为 `GET /health`。

```bash
uv run pytest
uv run ruff check .
```
