# DNS SOA 序列号审计 API

基于 **Python + FastAPI + SQLite** 的服务，审计 DNS 区域 SOA 记录的 32 位序列号，
比较规则严格遵循 [RFC 1982（Serial Number Arithmetic）](https://www.rfc-editor.org/rfc/rfc1982)。

## 功能

- 客户端提交**区域名**与**按观测时间先后排列**的 32 位 serial；
- 服务端在模 2³² 环形空间中逐项判定：
  - `forward`（前进）：后继值在环形正方向且严格小于半圈；
  - `backward`（倒退）：后继值在环形反方向；
  - `equal`（相等）：两值相同；
  - `incomparable`（不可比较）：两值**恰差 2³¹**，RFC 1982 规定此情形比较结果未定义；
- 对 `backward` 与 `incomparable` 节点标记 `reject_risk: true`——从服务器（slave）
  在 SOA 查询时发现 serial 未“变大”会拒绝加载/更新该区域（RFC 1035 §2.2 区域维护语义）；
- 给出 **YYYYMMDDnn** 风格的下一序列号建议（`nn` 为两位当日编号 00–99），
  并再次用 RFC 1982 校验其相对当前值确为有效前进（支持 2³² 边界回绕）；
- **当日编号耗尽**或建议路径存在**半区间（2³¹）歧义**时返回 `409 Conflict`；
- 每次审计（含 409 的记录）均落库，可按自增 ID 查询。

## 单条命令启动

需要 Docker（含 Compose 插件）。依赖安装、数据库初始化均随容器启动自动完成，
无需任何手工准备：

```bash
docker compose up --build
```

服务地址：<http://localhost:8000>

- 交互式 API 文档（Swagger UI）：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/healthz>

SQLite 数据库保存在命名卷 `soa_audit_data`（容器内 `/data/soa_audit.db`），
容器重建后审计记录不丢失。

## API

### `POST /audits` — 创建审计

请求体：

```json
{
  "zone": "example.org",
  "serials": [2026091801, 2026091805, 2026091805, 2026091802]
}
```

- `zone`：区域名，RFC 1035 点分标签（自动去除尾部点、转小写）；
- `serials`：1–1000 个 32 位无符号整数 `[0, 4294967295]`，**按观测时间从旧到新排列**，
  服务端信任该顺序。

成功响应 `201 Created`：

```json
{
  "id": 1,
  "zone": "example.org",
  "created_at": "2026-09-18T16:01:40+00:00",
  "serials": [
    {"index": 0, "observed_serial": 2026091801, "previous_serial": null,
     "state": null, "reject_risk": false, "note": "首个观测值，无可比较的前驱"},
    {"index": 1, "observed_serial": 2026091805, "previous_serial": 2026091801,
     "state": "forward", "reject_risk": false, "note": null},
    {"index": 2, "observed_serial": 2026091805, "previous_serial": 2026091805,
     "state": "equal", "reject_risk": false, "note": null},
    {"index": 3, "observed_serial": 2026091802, "previous_serial": 2026091805,
     "state": "backward", "reject_risk": true,
     "note": "序列号倒退，从服务器将拒绝加载该区域（SOA serial 未更新）"}
  ],
  "summary": {"total": 4, "equal": 1, "forward": 1, "backward": 1,
              "incomparable": 0, "reject_risk_count": 1},
  "suggestion": {"next_serial": 2026091806, "date_prefix": 2026091800,
                 "valid_forward": true, "error": null},
  "reference": "RFC 1982"
}
```

建议基于**最后一个观测值**（当前 serial）按 **UTC 日期**生成；
从服务器拒绝更新的风险节点不受建议影响。

#### `409 Conflict`

响应体结构与 201 相同（仍带 `id`，记录已入库），但 `suggestion` 中
`valid_forward=false`、`next_serial=null`，并给出错误码：

| `error.code` | 含义 |
| --- | --- |
| `DAILY_SEQUENCE_EXHAUSTED` | 当日 `nn=00..99` 相对当前值均不构成有效前进（编号已用完，或当前值的日期前缀已在今天之后） |
| `HALF_RANGE_AMBIGUITY` | 阻断候选与当前值恰差 2³¹，RFC 1982 比较结果未定义（半区间歧义） |
| `SERIAL_SPACE_OVERFLOW` | 当日前缀超出 32 位无符号范围（防御性，2099 年前不会出现） |

```bash
curl -s -X POST http://localhost:8000/audits \
  -H 'Content-Type: application/json' \
  -d '{"zone":"exhausted.test","serials":[2026091899]}'
# HTTP 409
```

其他错误：`422`（非法区域名、serial 越界、列表为空或过长）。

### `GET /audits/{id}` — 按 ID 查询

```bash
curl http://localhost:8000/audits/1
```

不存在的 ID 返回 `404`。

### 其他

| 路径 | 说明 |
| --- | --- |
| `GET /` | 服务与端点索引 |
| `GET /healthz` | 健康检查 |
| `GET /docs` | Swagger UI |

## 本地开发（不使用 Docker）

要求 Python 3.11+：

```bash
pip install -r requirements.txt
python -m pytest -q                       # 运行测试
SOA_AUDIT_DB=./data/audit.db \
  uvicorn app.main:app --reload --port 8000
```

环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SOA_AUDIT_DB` | `/data/soa_audit.db` | SQLite 文件路径，父目录不存在会自动创建 |

## 项目结构

```
.
├── app/
│   ├── main.py        # FastAPI 路由、lifespan 启动建表
│   ├── rfc1982.py     # RFC 1982 模运算比较与下一序列号建议（纯函数）
│   ├── service.py     # 审计结果组装
│   ├── schemas.py     # 请求/响应模型与输入校验
│   └── database.py    # SQLite 连接、建表、存取
├── tests/             # 22 个单元/集成测试
├── Dockerfile         # 构建期跑测试，非 root 运行，启动自动初始化
├── docker-compose.yml # 命名卷持久化 + 健康检查
└── requirements.txt
```

## RFC 1982 判定速查（SERIAL_BITS = 32）

对相邻两个 serial `s1 → s2`，取有符号环形距离
`d = (s2 - s1) mod 2³²`（大于 2³¹ 则减 2³²）：

| 距离 d | 判定 | 从服务器行为 |
| --- | --- | --- |
| `0` | `equal` | 无变化，不传输区域 |
| `0 < d < 2³¹` | `forward` | 正常接受更新 |
| `-2³¹ < d < 0` | `backward` | **拒绝更新** |
| `d = 2³¹`（恰为半圈） | `incomparable` | 结果未定义，**拒绝更新** |
