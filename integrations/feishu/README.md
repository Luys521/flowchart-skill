# 飞书插件（integrations/feishu）

把"材料 → 《流程表》 → 流程图"这条链路接到飞书：从飞书拉材料（云文档导出、审批），
把产物发布到飞书。**交付分层**：默认只主动发 **HTML 的云盘链接（在线渲染）+ 一句"需要我提供可编辑的画板吗？"**；
可协同编辑的画板云文档、多维表格都在用户**追问时才给**（默认不打包、不内嵌）。
本插件是**可整体插拔**的，且**出厂默认关闭**——
未启用时核心零 import 飞书、零凭证也能正常在本地跑。

## 一、双令牌模型（先理解这个）

| 凭证 | 身份 | 承担的能力 | 如何获得 |
|---|---|---|---|
| `tenant_access_token` | 应用（机器人） | 群消息 IM、云盘 Drive、多维表格 Bitable、审批 | 用 app_id/app_secret 自动获取，自动缓存续期 |
| `user_access_token` | **用户本人** | **云文档导出**（导出权限属用户身份，应用身份调用会被拒 code=99991672） | 一次性浏览器 OAuth 登录，缓存 access/refresh，到期自动刷新 |

> 探针已实测：云文档导出必须用户身份；消息、云盘上传、多维表格用应用身份即可。

## 二、启用插件（默认关闭）

三选一（显式关闭优先于启用）：

```text
# 方式 A：环境变量（推荐，临时启用）
set FLOWCHART_PLUGIN_FEISHU=1

# 方式 B：复制配置模板并把 enabled 改为 true
copy config.example.yaml config.yaml

# 方式 C：技能根 config.yaml
# integrations:
#   feishu: {enabled: true}
```

## 三、配置应用凭证

敏感值走环境变量，**不要把 app_secret 写进文件或提交仓库**：

```text
set FEISHU_APP_ID=cli_a98683c2c5ccd01c
set FEISHU_APP_SECRET=********
```

（`cmd` 下需要同一条命令内使用：`set FEISHU_APP_SECRET=xxxx&& python ...`）

## 四、开通权限

应用身份权限（开发者后台「权限管理」，机器人需被拉进目标群）：

- 消息与文件：`im:message`（发消息）、`im:resource`（上传图片/文件）
- 云盘：`drive:drive`（上传/管理云盘文件、协作者授权）
- 云文档与画板：`docx:document`（建文档/写块）、`board:whiteboard`（建画板/写节点连线）
- 知识库：`wiki:wiki:readonly`（仅当要导出 wiki 节点时，用于解析节点）
- 审批：`approval:approval`，**并在审批后台把应用授权给目标审批定义**

用户身份权限（OAuth scope，在「权限管理」开通）：

- `offline_access`：获取 refresh_token，支持无人值守自动续期
- `docs:document:export`：云文档导出（已开通，数据范围与用户权限一致）

配置改动后记得**创建版本并发布**，否则不生效。

## 五、用户授权登录（导出前做一次）

1. 在开发者后台「安全设置 → 重定向 URL」加入白名单（与本地回调完全一致）：

   ```text
   http://127.0.0.1:8765/callback
   ```

2. 运行登录，浏览器里完成授权：

   ```text
   python integrations/feishu/feishu_client.py login
   ```

   成功后 token 缓存到本目录 `.token-cache.json`；access 到期会用 refresh 自动续，
   refresh 也失效（约 365 天未再授权）时重新 login 即可。

3. 应用身份自检：

   ```text
   python integrations/feishu/feishu_client.py check
   ```

## 六、使用连接器

```text
# 云文档导出（用户身份）：支持 docx/sheet/base/wiki 的 URL 或 token
python integrations/feishu/sources/doc_export.py "https://xxx.feishu.cn/docx/FrNY..." -o ./materials
#   可选 --ext pdf|xlsx|csv|zip 、--type docx|sheet|bitable 、--name 文件名

# 审批拉取（应用身份）：需要审批定义 code
python integrations/feishu/sources/approval.py <approval_code> -o ./materials
#   可选 --status APPROVED 、--no-detail

# 产物发布 A：云盘 + 群消息（png 发图片，其余发文件）
python integrations/feishu/publishers/feishu_push.py out\*-flow.html \
    --chat-id <chat_id>
#   不传 --chat-id 则只传云盘；--folder 指定云盘文件夹（空=根目录）；--no-drive 跳过云盘

# 产物发布 B：云文档（docx + 可在线协同编辑画板），群里只收链接
python integrations/feishu/publishers/feishu_doc.py out\<名>-flow.yaml \
    --chat-id <chat_id> --note "流程图已生成"
#   几何/配色取自 DSL，自动授权该群可编辑；--no-push 只建不发；--no-share 不授权

# 门面 finish（默认首选）：build → HTML 传云盘 → 群里收 /file/ 链接 + “需要可编辑画板吗？”
python integrations/feishu/orchestrate.py finish out\<名>\flowtable.md --chat-id <chat_id>
#   --primary doc 直接发云文档画板；--no-offer-board 不追问；--no-drive 改发 IM 文件

# 门面 board（用户追问“要画板”后）：建 docx + 画板，发 /docx/ 链接
python integrations/feishu/orchestrate.py board out\<名>\flowtable.md --chat-id <chat_id>

# 门面 bitable（需 config 里 delivery.enable_bitable=true）：独立多维表格，发 /base/ 链接
python integrations/feishu/orchestrate.py bitable out\<名>\flowtable.md --chat-id <chat_id>
```

### 交付偏好（config.yaml 的 `delivery` 段，全局记忆、由使用者自行编辑）

```yaml
delivery:
  primary: html          # html=HTML 云盘链接（默认）；doc=直接发云文档画板
  html_to_drive: true    # HTML 走云盘在线渲染；false 改发 IM 文件
  offer_board: true      # 发 HTML 后追问“需要我提供可编辑的画板吗？”
  board_on_request: true # 画板仅在用户明确要求时才给（默认不主动给）
  enable_bitable: false  # 多维表格开关，默认关闭
```

CLI 参数（如 `--primary doc`、`--no-offer-board`、`--no-drive`）可临时覆盖；多维表格里
每个节点一行（12 列），改完可反向喂回重新生成（见下）。

这些连接器同时注册到插件扩展点（`sources/feishu_doc_export`、`sources/feishu_approval`、
`publishers/feishu`、`publishers/feishu_doc`、`commands/feishu_login`），供核心/编排按名调用。

## 七、已知限制与规避（探针实测）

- **云盘上传不要传 checksum**：`upload_all` 带 md5（hex/base64）均报 code=1062008；本插件已不传。
- **SVG 不能插进文档正文**：正文插图仅 jpg/png/bmp/gif；流程图在飞书的原生落点是**画板**
  （4c 已做：直接 POST 画板节点/连线，可在线协同编辑），不再依赖导入 SVG。
- **PNG 只是自身截图快照**，不是正式交付物、也不 build 后自动出，仅按需用于无法渲染 SVG 的场景。
- **审批没有"列出租户全部审批定义"的接口**：必须先拿到 approval_code。
- **本地单文件 HTML 无公网 URL，不能内嵌进飞书文档正文**（内嵌网页走白名单）；HTML 的飞书落点是
  **上传云盘、发 `/file/<token>` 链接**，点开即在线渲染（执行 JS、完整渲染内联 SVG，已实测；
  若个别环境不渲染，退回下载本地打开）。

## 八、阶段进度

- 阶段 3（已完成）：薄网关 `scripts/serve.py` + 宿主契约 `HOST_CONTRACT.md` + 门面 `orchestrate.py`；
  技能不持长连接，由宿主智能体按需调用。
- 阶段 4c（已完成）：云文档发布器 `publishers/feishu_doc.py`（docx + 可编辑画板，群里发链接）。
- 阶段 4d（已完成）：
  - `sync_bitable.py`：流程表 12 列 ↔ 多维表格双向同步（push/pull 往返逐格零差异、二次 push 幂等）；
  - 交付分层落地：`finish` 默认 HTML 云盘链接 + 画板追问；`board`（docx+画板）、`bitable`（独立多维表格）
    均为按需子命令；多维表格默认关闭（`delivery.enable_bitable`）；
  - 反向闭环：改多维表格 → pull 回流程表 → build 重新生成（已端到端实测）；
  - 闭环默认**重新生成新链接**，不做“同一文档原位更新画板”（画板本就按需、非默认，原位更新收益低）。
