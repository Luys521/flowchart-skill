# 内部 DSL（<流程名>-flow.yaml）规范

> 本文件在 SKILL 第四段（出图与自检）需要手调几何时读取。`<流程名>-flow.yaml` 由 `table_to_dsl.py` 生成，通常**无需手写**。

## 1. 生成与刷新

```bash
# 从流程表生成（-o 固定为 output/<名称>/<名称>-flow.yaml）
python flowchart-skill/scripts/table_to_dsl.py --write "output/<名称>/flowtable.md" -o "output/<名称>/<名称>-flow.yaml"

# 复用已润色流程图的几何（列/边）作为布局提示
python flowchart-skill/scripts/table_to_dsl.py --write --layout "<已润色>.yaml" "output/<名称>/flowtable.md" -o "output/<名称>/<名称>-flow.yaml"

# 质量门禁：零重叠 / 零穿线（正交交叉允许）/ 标签压线
python flowchart-skill/scripts/validate.py "output/<名称>/<名称>-flow.yaml"
```

## 2. 结构

```yaml
meta:
  title: 图表标题
  layout: flow              # flow（缺省）| swimlane（泳道：row=阶段/槽位、col=执行主体）
                            # 由流程表的「输出布局」元信息决定，不手改；swimlane 下 layout.col_x 无意义
  subjects:                 # 主体配色（覆盖 dictionary.yaml 默认）
    主体A: {fill: "#dae8fc", stroke: "#6c8ebf"}
layout:
  col_x: [400, 860]         # 各列中心 x（必须落在粗格 20 上）；写成 `[]` = 按字典 col_pitch 展开
  origin_x: 0               # 画布左留白：加在每一列上，左侧回路通道的基准也跟着移（派生量，见 D-77）
  width: 680                # 画布宽：由内容算出（下限是标题块宽）。**派生量，可手调**
                            # 布局规则升级后，子表的 `*-flow.yaml` 要删掉重新生成才会跟上（build 会跳过已存在的）
nodes:
  - id: "01"
    name: 约定期前技术服务合作协议
    lines: ["01 约定期前技术服务", "合作协议"]   # 节点内换行显示
    type: start             # start|end|task|decision（四种，见 flowtable-spec §2《类型登记表》）
    subject: 双方
    executor: 双方共责
    input: 申请材料、身份证明      # 被消耗/改变的东西（可省，省了本字段对本表隐性）
    basis: 《受理办法》§3.2        # 不被消耗、只决定能不能做（ICOM 的 Control）
    output: 受理回执               # 交出去的东西
    time: 5个工作日           # 可省
    row: 0                  # 可手调
    col: 0                  # 可手调
    route: 通过→05 ｜ 不通过→回 03 修正
    desc: 完整描述…
edges:
  - {from: "13", to: "14", kind: spine, label: 通过}
  - {from: "13", to: "10", kind: loop, polarity: negative, label: 不通过}
```

## 3. 边字段

| 字段 | 取值 | 说明 |
|---|---|---|
| `kind` | `spine` / `horiz` / `loop` / `jumpR` / `mix` | 行间主干竖连 / 同行横连 / 左侧回路通道 / 右侧长跳 / 混合 |
| `polarity` | `main` / `negative` | 实线 / 虚线；`loop` 自动为 negative |
| `gutter` | 数值 | 左侧通道 x（左族，端口 left→left） |
| `channel` | 数值 | 右侧通道 x（右族，端口 right→right） |
| `gapx` | 数值 | 跨相邻列的列间通道 x（端口按列序取 left/right）；也承载前向对角 L 形的折点 x（D-28，此时端口组合是 right→top 或 bottom→right，以落盘的 `exit`/`entry` 为准） |
| `dye` | 数值 | 目标（entry）侧锚点沿端口边的**切向**错位量（左右边挪 y、上下边挪 x，D-17），用于同目标多回路错开；手填值吸到细格、不被自动错开覆盖 |
| `sdye` | 数值 | 源（exit）侧锚点沿端口边的**切向**错位量（语义同 `dye`）：出边与入边共用同一侧端口时挪开出边、避免掉头折返（D-15）；一去一回的两条反向平行边按**行进方向**分别取正负号，各占走廊一侧（D-34）；手填优先、不被覆盖 |
| `exit` / `entry` | top/bottom/left/right | 覆盖默认端口 |

> `gutter` / `channel` / `gapx` 是**派生量**：不写就由 router 依节点布局与端口现场规划，且**通道族严格分侧**（右族不得越过任何节点右沿，左族不得越过左沿）。手填值不直接生效——router 先按通道族推出端口、再用同一套冲突规则复检，过期几何（折线横穿自身节点、箭头被节点盖住）会被**丢弃重规划**，通过复检的才原样钉住。要复位就删掉这几个字段。

> 所有几何字段必须是**格上值**：`col_x` / `row` 影响节点盒（粗格 20），`dye` / `sdye` / `gapx` / `gutter` / `channel` 影响折点（细格 10）。填了离格值不会报错——会被统一吸附（`col_x` 与形状尺寸的吸附会在门禁输出里提示 `· 网格吸附: …`；折点量是静默吸附），但 yaml 与产物就此不一致，next 次对比就会冒出假 diff。

## 4. 边界

- **允许手调**：`row` / `col` / `col_x` / `dye` / `sdye` / `kind`；`gutter` / `channel` / `gapx` 仅在确实要固定通道时手写
- **新增列要同步补 `layout.col_x`**：节点用了 `col: 1` 而 `col_x` 只有一列，几何算不出来（门禁会报「列号越界」）。
  **新列插哪里**（D-29）：上一列中心 + `layout.col_pitch`（默认 460，即 400 → 860 → 1320…）——
  460 = 节点宽 160 + 列间通道带 300，通道带要容下 `col_gap_step` 的交替展开与右族局部基准；
  间距压到 300 以下会挤爆通道带（门禁报边重叠/通道冲突），没有特殊理由就用默认值
- **`<流程名>-flow.yaml` 不是可持久编辑的文档**：`build.py` / `table_to_dsl --write` 会**整份重写**它——手写的注释、键序、换行符都会按生成器的格式统一（注释请写进流程表）。
  推论：对一份"手工改过格式"的 yaml 执行首次 build，它会变；再 build 就稳定了——**幂等只在规范化之后成立**
- **禁止手调**：节点名称、输入、依据、输出、执行主体、执行者、时间、分支语义——改语义必须回写流程表后重新生成
- **禁止出现**：绝对像素坐标、颜色 hex（配色走 `meta.subjects`）、手动连线路由点
- **网格**：任何新加的几何键都要说明它属于粗格（20）还是细格（10），否则不得合入
