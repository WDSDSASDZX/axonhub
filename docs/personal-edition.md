# AxonHub 个人版

本版本基于原 AxonHub 的 Go 网关开发，保留原作者和 Apache-2.0 许可。
旧的全 Python 网关实验保存在 `archive/python-gateway-20261023` 分支。

## 实际分工

- Go：客户端鉴权、协议转换、SSE、重试、限流、日志、原有模型/渠道/API Key 管理。
- React：个人工作台，管理 Jet Hub 账号、模型、签到、聚合候选和直接渠道额度策略。
- Python：带认证的本机 Jet Hub 管理桥接、额度数据校验、临期排序和策略发布。
- 已安装的 dsh-providers-hub：具体平台登录、令牌续期、余额和签到接口、平台协议转换。

这是一种组合部署。平台适配器仍由 DSH 插件执行，并未把其所有平台协议移植成 Python。
Go 经 Jet Hub 的 OpenAI 网关转发模型请求；Python 不经过每一次模型请求。
DSH 中断时 Jet Hub 渠道会受影响，其他直接渠道仍可独立工作。

## 个人版精简

默认关闭团队邀请、OIDC 登录和团队/角色/项目管理写操作，同时裁剪相应导航。
GraphQL 的关闭操作同时检查别名和片段；OpenAPI GraphQL 使用同样的限制。
个人模式下，管理接口仅允许系统所有者访问。客户端 API Key 继续使用原鉴权流程。
渠道、模型、API Key、请求记录、用量和对话功能继续使用原实现。
原有的数据结构和兼容协议保留，便于维护和跟进上游；并非删除所有企业模块源码。
设置 `AXONHUB_PERSONAL_MODE=false` 可恢复原管理能力。

## 启动

需要已有 Go、Node.js 和 Python 3.10+。Python worker 仅使用标准库。

1. 在 DSH 中安装并启用 Jet Hub，确认其本机 OpenAI 网关已运行。
2. 创建私有文件 `data/personal/connection.json`，Linux 权限设为 600：

   ```json
   {
     "dsh_url": "http://127.0.0.1:3080",
     "launch_url": "填写 DSH 本次启动提供的完整授权链接"
   }
   ```

   授权链接包含登录令牌，只保存到这个被 Git 忽略的本地文件。
   地址必须是同一个本机服务。DSH 授权过期或重启后，更新链接并重启 worker。

3. 使用项目原有工具链构建前后端。若本机 pnpm 比原项目新，
   可直接运行已安装的 `frontend/node_modules/.bin/vite build`。
   将 `frontend/dist/` 复制至 `internal/server/static/dist/`，再构建
   `go build -tags=nomsgpack -o dist/axonhub-personal ./cmd/axonhub`。
4. 执行 `bash scripts/run-personal.sh`。默认仅监听本机，网页端口 8091，
   worker 端口 8093，SQLite 数据保存在 `data/personal/axonhub.db`。
   使用 `AXONHUB_SERVER_PORT`、`AXONHUB_PERSONAL_WORKER_PORT` 可改变端口。
5. 首次打开网页创建自己的管理员，进入“账号与额度”，点击“连接 Jet Hub 到网关”。
   这会创建或同步 Jet Hub 渠道；平台原始凭据不进入浏览器。

平台操作由已安装插件决定。短信平台提供验证码入口，浏览器授权平台会打开授权页。
需要额外设备能力或验证码载体的平台，可在 DSH 原生页面完成授权再回到这里刷新。
自动签到的配置沿用插件，不会在首次接入时自行开启。

## 额度策略

Jet Hub 内部按账号和模型调度，由插件采集实际到期信息。工作台可管理其聚合候选。

Python 的直接渠道策略按以下流程执行：

1. 登记 AxonHub 渠道 ID、允许的模型、余额、单位、数据来源、采集时间和到期时间。
2. 先剔除停用、用尽、过期或数据超过五分钟未确认的渠道。
3. “仅使用临期额度”要求存在临期余额；混合钱包还必须确认上游优先扣临期余额。
4. 在满足限制的候选间按到期时间排序。不同单位的余额不相加。
5. 原子发布带有效期的策略文件；Go 在原有候选筛选后读取并执行。
   策略过期时受管理渠道停止派发；未受管理渠道保留原路由。

策略在重试候选截断前应用，避免候选数量较多时漏掉应优先使用的渠道。
显式配置的模型关联优先级保持有效；受额度策略管理的请求不采用历史渠道粘滞。

网页中的直接渠道余额目前是**手动确认的数据**，五分钟后需重新确认。
它不是全自动余额采集器，也不代表供应商账单。
Python worker 默认每 30 秒重新计算，策略有效期为 90 秒；不会凭空刷新数据采集时间。
通过 `POST /admin/personal/budgets` 可写入多个额度桶，以保留临期/长期混合钱包的信息。

## 测试与来源

- Python：`PYTHONPATH=personal python3 -m unittest discover -s personal/tests -v`
- Go：`go test -tags=nomsgpack ./internal/personal ./internal/server ./internal/server/orchestrator`
- OAuth 在独立 llm 模块：`cd llm && go test ./oauth`

本地验证结果：Python 9 项测试通过；Go personal/server/orchestrator/api/middleware
和独立 OAuth 测试通过；新增工作台 ESLint 通过；前端与 Go 生产构建通过。
隔离数据库的真实 HTTP/SSE 联调验证了临期优先、永久额度保护、数据过期拒绝派发，
分别返回 200、200、503。可在专用测试实例上运行 `python3 scripts/verify-personal-routing.py` 复现，
脚本只接受 `verify.db`，会恢复原额度策略并停用其创建的测试渠道。

原 Go 基线与当前前端全量类型检查均有 190 条既有诊断，原文件位置和错误码一致。
本次新增文件没有类型错误；尚未修复这些全局遗留问题。
生产构建仍有原有的大资源包警告。各平台的真实登录与签到需使用相应账号进一步验证。

Jet Hub 参考来源：[dsh-providers-hub](https://github.com/iJetLi/dsh-providers-hub)。
已联调的本机插件版本为 2.1.261022；管理接口变化时需更新桥接适配。
本项目未复制插件发布包，插件许可由其自身 MIT LICENSE 声明。
