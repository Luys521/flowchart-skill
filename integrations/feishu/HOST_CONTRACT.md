# 飞书宿主交接契约（HOST_CONTRACT）

> 本文件写给**宿主智能体**（如「群聊助理小炜」、飞书智能伙伴、或任意 Agent 运行时）的开发者。
> flowchart-skill 是**被调用的能力包**：它不常驻、不持有飞书长连接、不内置模型。
> 长连接与对人交互由宿主独占；"读懂材料 → 写流程表"这一**语义步骤也由宿主完成**；
> 技能只提供确定性原子：**取材料（导出）/ build 出图 / 发布回群**。

## 一、角色分工

| 职责 | 宿主智能体 | flowchart-skill |
| --- | --- | --- |
| 飞书长连接、接收群消息、对人回复 | ✅ 独占 | ❌ 不参与（避免同 app 多连接分流） |
| 理解文档、提炼步骤、编写《流程表》 | ✅ 语义步骤 | ❌ 不代做 |
| 导出云文档为本地材料 | — | ✅ source |
| 结构校验 + 渲染三份视图 | — | ✅ build |
| 把产物回发到指定群 / 云盘 | — | ✅ publish |

## 二、三种等价接入方式（任选）

### 方式 A：直接命令行（最简单，宿主会执行命令即可）

```bat
:: 1) 导出文档（用户身份）
python -m sources.doc_export "<文档URL或token>" -o "<任务目录>\materials" --name 源文档

:: 2) 宿主自己读懂材料，在 <任务目录>\<流程名>\flowtable.md 写流程表（照 templates/flowtable-skeleton.md）

:: 3) build 出图
python scripts\build.py "<任务目录>\<流程名>\flowtable.md"

:: 4) 回发到群（chat_id 来自收到的消息事件；--no-drive 只回群、不传云盘）
python -m publishers.feishu_push "<任务目录>\<流程名>\<流程名>-flow.html" --chat-id <chat_id> --note 流程图已生成 --no-drive
```

> 直接 CLI 时，工作目录需在插件根 `integrations/feishu`（source/publisher）或技能根（build）。

### 方式 B：网关单次 JSON（统一契约，零常驻）

```bat
python scripts\serve.py --run '<请求JSON>' --plugin feishu
```

| action | args 关键字段 | 返回 |
| --- | --- | --- |
| `source` | `source`(默认 feishu_doc_export)、`ref`、`out_dir`、`name` | 材料文件路径 |
| `build` | `flowtable` | 三份产物路径 `products` |
| `publish` | `artifacts`(路径列表)、`chat_id`、`note`、`to_drive`(默认 true) | 发布回执 |
| `ping` | — | 已注册扩展快照 |

导出请求示例：

```json
{"action": "source", "args": {"ref": "https://<域名>/docx/<token>", "out_dir": "D:/task/materials", "name": "源文档"}}
```

### 方式 C：网关 HTTP（宿主在远端 / 只擅长 HTTP 时；需 `pip install fastapi uvicorn`）

```bat
python scripts\serve.py --http --host 127.0.0.1 --port 8760
:: GET  /health
:: POST /invoke   body = 方式B 的请求 JSON
```

### 便捷门面：orchestrate.py（prepare + 按需 finish/board/bitable）

```bat
:: prepare：材料就位后做确定性预检（材料目录 + 流程表）
python orchestrate.py prepare "<任务目录>\materials" "<任务目录>\<流程名>\flowtable.md"

:: finish（默认首选）：build → HTML 传云盘 → 群里收 /file/ 链接 + “需要我提供可编辑的画板吗？”
python orchestrate.py finish "<任务目录>\<流程名>\flowtable.md" --chat-id <chat_id>

:: board（用户追问“要画板”后）：docx + 可协同编辑画板，群里收 /docx/ 链接
python orchestrate.py board "<任务目录>\<流程名>\flowtable.md" --chat-id <chat_id>

:: bitable（需 delivery.enable_bitable=true）：独立多维表格，群里收 /base/ 链接
python orchestrate.py bitable "<任务目录>\<流程名>\flowtable.md" --chat-id <chat_id>
```

## 三、标准任务时序（群里收到"文档链接 + 出图"）

```text
宿主收到群消息（含文档链接）
  │  记录 chat_id（用于最后回发）
  ├─① source 导出材料 ──→ 本地 PDF/文件
  │
  ├─② 【宿主自己】读材料、写 <流程名>/flowtable.md（可让技能给候选，宿主定稿）
  │
  ├─③ build ──→ <流程名>-flow.html / .drawio / .svg（校验+几何自检不过会直接失败）
  │
  └─④ finish 回发原 chat_id：默认 HTML 云盘 /file/ 链接（在线渲染）+ 追问“需要可编辑画板吗？”
        用户要画板 → board 发 /docx/ 链接；要可编辑表格且已启用 → bitable 发 /base/ 链接
```

## 四、凭证与运行环境（宿主负责注入）

**凭证按三层取值，先到先用**（`feishu_client.FeishuClient.__init__` 的实际顺序）：

| 顺序 | 来源 | 典型场景 |
| --- | --- | --- |
| 1 | `integrations/feishu/config.yaml` 的 `app_id` | 办公电脑上试跑，手填一份 |
| 2 | `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 环境变量 | **宿主按本契约注入**（推荐） |
| 3 | `APP_ID` / `APP_SECRET` 环境变量 | **飞书托管环境**（云函数 / 应用引擎 / 官方 SDK 约定） |

> **第 3 层不是"多余兜底"，删不得**：飞书开放平台的官方示例代码用 `process.env.APP_ID`，
> 官方 SDK 的 `Config.getInternalAppSettingsByEnv()` 认的就是 `APP_ID` / `APP_SECRET` /
> `VERIFICATION_TOKEN` / `ENCRYPT_KEY` —— **托管运行时按这个约定注入**。删掉它，
> "装到飞书上"那条路会直接失效。（2026-09-24 查证飞书开放平台文档后确认）

**难点在于：技能自己看不出它站在哪一层。** 所以有 `python scripts/env_probe.py` ——
它按客观事实判档，并给出交付建议：

| 判据 | 判档 | 能力 |
| --- | --- | --- |
| `APP_ID` 与 `APP_SECRET` 都在 | `feishu-hosted` | source ✓ publish ✓ |
| 只有 `FEISHU_*` 或 `config.yaml` 有 app_id | `feishu-configured` | 可连飞书，**不保证在托管运行时里** |
| 都没有 | `local` | **只能 build**，交付 = 落文件 |

宿主若只想暴露"能做什么"，调网关的 `ping`；**要判断"我该走哪条交付路径"，读 `env_probe`** ——
`ping` 答的是"插件注册了什么"，`env_probe` 答的是"环境支不支持"，**两问不可互相推断**
（插件**未启用**时它会前置一句提醒，避免"托管可发布"这类结论漏出去唬人）。

- 用户身份（导出云文档）：先完成一次 OAuth 登录（`feishu_login` 或 `python feishu_client.py login`），
  user token 缓存在插件目录 `.token-cache.json`（已 gitignore），`offline_access` 下自动续期。
- 密钥只走环境变量，不写进技能仓库、不写进配置文件。

## 五、约定与边界

- 一次请求一次调用、进程结束即清理，技能不残留常驻连接。
- 同一飞书应用**只允许宿主一个长连接**；技能侧不要再起 ws 客户端（同 app 多连接会负载均衡、消息被分流）。
- 默认交付 HTML：上传云盘发 `/file/` 链接（单文件、内嵌子图、在线渲染）；画板 docx、多维表格
  均为用户追问才给的可选项，不默认打包 / 内嵌；PNG 仅按需快照，不作为正式交付。
- 文档正文不支持 SVG 插图；流程图在飞书的原生落点是画板（可协同编辑），或作为文件交付。
- 反向闭环：用户改多维表格 → pull 回流程表 → build 重新生成（默认出新链接，不原位改文档）。
