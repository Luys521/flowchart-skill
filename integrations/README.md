# integrations/ — 插件目录（可插拔集成）

本目录存放**平台/外部系统专属**的可选集成。核心（`scripts/`）不 import 这里的任何代码；
运行时由通用插件框架（`scripts/plugin.py` 的 `discover()`）按清单**动态加载**。

- 插件**出厂默认关闭**：未配置 `enabled: true`（或等价环境变量）时，核心完全感知不到它，零凭证也能跑。
- 缺依赖、缺凭证、入口异常都会被**单个隔离并给出人话**，不拖垮核心、不影响其它插件。
- 判断一段逻辑该不该放这里：**只对某个外部平台有意义、且核心不依赖它** → 放插件；本地和平台都要受益的通用能力 → 进 `scripts/` 核心。

## 目录结构

```text
integrations/
  README.md                 # 本指南
  <plugin-name>/
    plugin.yaml             # 插件清单（必需）：entry / requirements / provides
    config.yaml             # 插件私有配置（可选；建议只放非敏感项，密钥走环境变量）
    config.example.yaml     # 配置模板，供复制成 config.yaml
    <entry>.py              # 入口，定义 register(registry, config, ctx)
    README.md               # 该插件的配置、权限、用法说明
    ...                     # 插件自带的子模块/子包
```

## plugin.yaml 清单字段

```yaml
# 入口模块文件名（缺省 = plugin，即加载 <entry>.py）
entry: plugin

# 依赖自检：discover() 加载前逐项 find_spec，缺失则跳过并提示 pip 安装。
# 每项可写 {import: 导入名, pip: 包名}；导入名与包名相同时可直接写字符串。
requirements:
  - {import: yaml, pip: pyyaml}

# 自述：该插件提供哪些扩展点实现（仅文档/自检用途，不参与加载逻辑）。
provides:
  sources: [example_source]
  publishers: [example_publisher]
```

## 入口契约

入口模块必须定义：

```python
def register(registry, config, ctx):
    """registry: scripts.plugin.Registry；config: 该插件合并后的配置 dict；ctx: 可选运行上下文。"""
    registry.register('sources', 'example_source', fetch, desc='示例材料来源')
    registry.register('publishers', 'example_publisher', publish, desc='示例发布')
```

`registry.register(point, name, fn, **meta)`：
- `point` 可取标准扩展点 `sources` / `renderers` / `publishers` / `sync` / `commands` / `serve_routes`，也可自定义新点；
- `fn` 为 callable，或延迟引用字符串 `"module:attr"`（get 时现解析，便于测试替换）；
- 重复注册以最后一次为准（允许覆盖同名扩展）。

插件目录在加载时会被加入 `sys.path`，因此入口内部可直接 `from <同目录模块> import ...`。

## 扩展点职责

| point | 职责 | 典型返回 |
|---|---|---|
| `sources` | 把外部数据拉成本地材料/流程表 | 本地文件路径或结构化材料 dict |
| `renderers` | 插件侧渲染器（build 自带 html/drawio/svg 注册表独立、不受影响） | 产物路径 |
| `publishers` | 把产物送到外部平台 | 回执 dict（平台侧 ID / 链接） |
| `sync` | 流程表 ↔ 外部结构化载体的双向同步 | 同步报告 |
| `commands` | 插件提供的 CLI 子命令（如登录授权） | 命令处理函数 |
| `serve_routes` | HTTP / 事件回调路由（服务化场景） | 路由处理函数 |

## 配置与凭证

- 配置读取优先级：CLI → 环境变量 → 技能根 `config.yaml` → 插件 `config.yaml` → 默认（见 `scripts/config.py`）。
- **敏感值（app_secret、token 等）只经环境变量注入**，不要写进 `config.yaml` 或提交到仓库。
  插件内用 `env_or_config(name, env_keys, default)` 取值。
- 插件启用开关（任一为真即启用，显式关闭优先）：
  - 配置 `enabled: true`；
  - 环境变量 `FLOWCHART_PLUGIN_<NAME>=1`；
  - CLI 显式传入。

## 新建一个插件（最小步骤）

1. 复制一个现有插件目录（如 `feishu/`）改名，或新建 `integrations/<name>/`。
2. 写 `plugin.yaml`（至少声明依赖）与入口 `register()`。
3. 需要配置就提供 `config.example.yaml`，并在插件 `README.md` 写清权限与环境变量。
4. 用 `FLOWCHART_PLUGIN_<NAME>=1` 启用，确认 `discover()` 报告里出现在 `loaded`；
   故意缺一个依赖，确认它进入 `missing_deps` 且核心仍正常。
5. 插件产物（token 缓存、临时文件）加入 `.gitignore`，不要提交。
