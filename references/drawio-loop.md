# drawio 读回与回写闭环（同步闭环）

> SKILL 第五段（回流）：用户在 drawio 改了语义时读取。只动几何的情况**不需要执行本流程**。

## 1. 命令

```bash
# 一键同步（推荐）：读回 → 差异对比 → 回写流程表 → 生成 DSL（保留二维布局）→ 碰撞检测
python flowchart-skill/scripts/sync.py "output/<名称>/<名称>-flow.drawio" "output/<名称>/flowtable.md"

# 只看差异，不回写
python flowchart-skill/scripts/xml_reader.py "output/<名称>/<名称>-flow.drawio" --diff "output/<名称>/flowtable.md"

# 确认差异后：覆盖原表 + 重渲染两份产物
python flowchart-skill/scripts/sync.py "output/<名称>/<名称>-flow.drawio" "output/<名称>/flowtable.md" --apply

# 分支走向与流程表冲突时（--apply 会被拦截）：确认"图是对的"才强行覆盖
python flowchart-skill/scripts/sync.py "output/<名称>/<名称>-flow.drawio" "output/<名称>/flowtable.md" --apply --force

# 读回：拓扑摘要（一行一节点，判断节点缩进列出分支），支持外部 drawio
python flowchart-skill/scripts/xml_reader.py "output/<名称>/<名称>-flow.drawio"

# 只要回写流程表、不生成 DSL（默认输出 flowtable.sync.md），并自动重跑结构校验
python flowchart-skill/scripts/writeback.py "output/<名称>/<名称>-flow.drawio" "output/<名称>/flowtable.md" -o "output/<名称>/flowtable.new.md"
```

## 2. 回写原则

- 以 `.drawio` 当前拓扑为准（含用户在 drawio 增删的节点/边）
- 节点语义：**名称**取框内可见文字（在 drawio 双击改名能被读回）；类型按形状（矩形=任务 / 菱形=判断 / 胶囊=起止）
- **其余语义列（项目运作阶段 / 输入 / 依据 / 输出 / 执行主体 / 执行者 / 行动所需时间 / 节点描述）一律以原《流程表》为准。
  图里根本没有这些字段**——drawio 的对象属性里一个语义列都不写（D-73）：那些属性用户改不动，
  写进图只会变成一块"改了等于没改"的牌子。所以这里没有"兜底"可谈：只有**图里新增的节点**
  （流程表里查无此 id）才会带回一行的空语义，由 H7 报缺、由作者补。
- **「下个节点」列（分支走向）同样受这条底线管辖，但它没法静默兜底**（见 D-45）：
  表里那个值就是图里那条边的目标，重建是必然的。所以它的保护方式是**冲突时报警 + `--apply` 拦截**——
  原表说 A 的某条分支去 B、而图里同一标签的分支去了 C（B≠C）时：
  - `writeback.py` 打印 `⚠ 节点 04 分支「不通过」走向冲突：流程表 → 05 ｜ 图 → 03`
  - `sync.py --apply` **默认拦截并退出码 1**，流程表不动；确认图是对的才加 `--force` 强行覆盖
  纯新增/纯删除的边不算冲突（那是正常的增删节点），只报方向性冲突。
- 原流程表表头**之前**的前言（标题、项目元信息、裁决规则）原样保留
- **最小差异**：`(分支标签 + 目标编号)` 与原文一致的分支**逐字回填原文**——分支顺序、编号后的自由注解、`回` 标记、换行符/BOM 一并保住；只有新增/改动的边才重写。三条规则的来龙去脉见 `import-existing.md` 的「回写的三条保真规则」
- 回写后自动跑结构校验；若破坏了结构（如给结束节点加了出边触发 H5）会如实报错，需修正后再继续

> 三条禁令：别用编号大小推分支顺序、别用编号大小猜「回」、别让 `write_text` 翻译换行符。违反了就会产生伪差异。细则见 `import-existing.md`。

## 3. 以回写结果为准刷新产物

回写表经用户确认后，覆盖原流程表，重跑（`--apply` 已包含此步，手工执行时用）：

```bash
python flowchart-skill/scripts/build.py "output/<名称>/flowtable.md"
```

## 4. 高频微调的迭代节奏

「用户改图 → AI 读回理解 → 更新流程表 → 重新渲染」可反复进行：

1. 用户在 drawio 改（几何、节点名、连线、增删节点均可）
2. AI 跑 `sync.py`，先读「差异」段落，用一句话向用户复述改了什么
3. 差异里有语义缺失（外部图常见）→ 补进流程表；补不出的以 `⚠` 标出（图上虚线，用户看图即见）
4. 质量门禁过 → `sync.py --apply` 覆盖原表并重渲染（或单独 `build.py`）
   - 若打印了 `⚠ …走向冲突`，说明流程表与图的连线不一致：**先判断哪边对**。
     表对 → 重跑 `build.py` 让图跟上；图对 → 加 `--force`。别不看这条就重试。
5. 用户继续改，回到第 1 步

`sync.py` 是幂等的：图没变时再跑一次，回写结果与原文逐字节相同。

> 「与流程表一致，无差异」那句是**集合比较**（`xml_reader` 比节点/边的存在性），只说明拓扑没变，不保证文件一致。
> 所以 `sync.py` 回写后自己会做一次**逐字节复核**：一致就明说「逐字节一致」，不一致就打印行级 diff。
> 看到 diff 里冒出你没动过的行，先当缺陷查，不要 `--apply`。（手工核对等价于
> `diff output/<名称>/flowtable.md output/<名称>/flowtable.sync.md`。）

## 5. 子 SOP 跳转

子 SOP 梳理出来后，在 drawio 中新增页面，给大节点加 `link="data:pageId,…"` 属性即可 Ctrl+点击跳转。子 SOP 的语义同样应先落在流程表中（可用独立流程表文件 + 独立 drawio 页面）。
