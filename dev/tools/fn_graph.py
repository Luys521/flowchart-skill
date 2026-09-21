# -*- coding: utf-8 -*-
"""fn_graph.py — 对 `scripts/*.py` 做 AST 静态分析，产出**函数级依赖图**及其衍生视图。

本工具是「把整台渲染机的脚本与函数画成（多层）流程图」这一任务的**唯一事实输入**：
靠人读代码猜调用关系必然漏，所以全部结论来自 `ast` 解析，不做猜测；判不出的分别记进
`unresolved`（可能有缺口）与 `ambiguity`（候选明确但运行期才定）两本账。

用法
----
    cd <repo 根>
    python dev/tools/fn_graph.py

产出（全部写在 dev/tools/ 下，只读 scripts/，绝不修改它）
----------------------------------------------------
    dev/tools/fn-graph.json    函数级依赖图（主事实源）
    dev/tools/fn-groups.json   函数分组：同文件调用图的弱连通分量（画流程图的依据）
    dev/tools/fn-deps.json     模块级依赖摘要（画"依赖入口"的依据）
    dev/tools/fn-graph.md      人读报告

## 解析规则（本文件的行为契约）

1. 遍历 `scripts/*.py`；逐个 `ast.parse`。解析失败的文件其错误记入 `stats.parse_errors`
   并继续处理其余文件，**不中断**。
2. 函数清单：`FunctionDef` / `AsyncFunctionDef` 都收。
   - 模块级函数：`kind="function"`，`qualname` = 函数名。
   - 类 `ClassDef`：收为一条 `kind="class"`。
   - 类的方法：`kind="method"`，`qualname` = `类名.方法名`；方法**同时**计入该文件的函数数。
   - 嵌套函数：`kind="function"`，`qualname` = `外层.内层`（逐层点号连接）。
   - 条件分支/异常处理里定义（如 `if TYPE_CHECKING:` 内）的函数同样收录，归其所在作用域。
   - `public` = 名字不以 `_` 开头。
   - `imports_used` = 该函数体里引用到的、来自 import 的**依赖模块名**
     （`from semantics import f` 用了 `f` → `"semantics"`；`import yaml` 用了 `yaml` → `"yaml"`）。
     记模块而不是符号名，因为要回答的是「这个函数依赖谁」。
     嵌套函数体的引用不算进外层函数（它会作为独立条目出现），避免重复计数。
   - 额外体量字段（供 md「函数体量排行」用）：
     * `span` = `endlineno - lineno + 1`（含首尾）。
     * `call_sites` = 该函数体**自己**的调用点总数（含对外部/标准库的调用）。
     * `nested` = 该函数体内是否直接定义了嵌套函数（bool）。
     * `segments` = **顶层顺序段数**，判据见下。
3. import 表（JSON 的 `imports`）：处理 `import X`、`import X as Y`、
   `from X import a, b as c`、`from X import *`、`from . import ...`。
   形态为 `源模块 -> 被导入符号名列表`；整模块导入或星号导入记 `["*"]`。
   **只收 `scripts/` 内的模块**（即 `scripts/*.py` 的文件名主干，含 render_html / render_drawio）。
   标准库与第三方不进 `imports`、不产生调用边，但会出现在 `imports_used`。
   相对导入（`from . import`）本项目是平铺目录用不到，一旦出现记入 `unresolved` 且不参与解析。
4. 调用边：对每个函数体（含模块顶层与类体，见末节）`ast.walk` 找 `Call`：
   - `Name(id)`：
       * id 能解析为本文件定义的函数/类名（含嵌套函数）→ **同文件边**；
       * id 来自 `from X import id` 且 X 是 scripts 模块 → **跨文件边**（`to_file = scripts/<模块>.py`）；
       * id 是所在函数的**形参** → 形参派发，见第 6 条；
       * id 是所在函数里 `for id in <本文件模块级字面量表>` 的循环变量 → 表内每个函数记一条边
         （表是字面量的，每次都会全部调用，所以不是歧义）；
       * id 是局部变量且该变量由 `getattr(...)` 赋值 → 见第 6 条；
       * 其余（builtin、标准库、第三方）→ 外部调用，忽略。
   - `Attribute(value=Name(alias), attr)`：
       * alias 是 `import X` 绑定的**模块**且 X 是 scripts 模块 → 跨文件边（`to_fn = attr`）；
       * alias 是 `self` → 沿**继承链**（含项目内基类）找同名方法：命中且在本文件 → 同文件边，
         命中在别的 scripts 模块 → 跨文件边，都没命中 → `unresolved`（**不猜**）；
       * alias 是普通局部变量/形参 → 默认视为**外部对象的方法调用**（Path / argparse / dict / list …），
         不计边、也不进两本账；只计数到 `stats.external_object_method_calls`。
         例外：若该局部变量/形参的类型已被**静态落地**（见第 6 条），则按该类的成员解析成边。
         （除此之外不做通用类型推断；把判不出类型的都塞进账本会让信噪比崩掉。）
   - 同文件边与跨文件边**都记**；自己调自己（递归）额外加 `"recursive": true`。
5. **实例属性的类解析（`self.<属性>.<方法>()`）**：先求 `self.<属性>` 的**候选项目类**——
   来自该类里 `self.<属性> = <某个项目类>(...)` 的赋值（含 if/else 两个分支各赋一个）。
   然后对每个候选类沿继承链找 `<方法>`：
   - 恰好 1 个目标 → **记边**（确定性补边，例如 `self.grid.anchor()`：`anchor` 只在 `Grid` 上有）；
   - ≥2 个目标 → 记入 **`ambiguity`**（候选明确，但运行期二选一，例如 `self.router.path()`）；
   - 0 个目标 → `unresolved`（候选类里没这个方法，或属性根本不是项目类实例）。
   常见形态：`engine.Engine` 里 `self.grid` 是 `Grid` 或 `SwimGrid`、`self.router` 是
   `Router` 或 `LaneRouter`，按泳道模式二选一 —— 这类正是 `ambiguity` 的典型。
6. **三种"间接调用"的确定性解析**：
   - **形参派发**：函数 F 内调用自己的形参 `p` → 在**全项目**里找 F 的调用点（**含
     `self.f(...)` 这种方法调用点**），取第 `p` 个实参（位置取 `param_pos`，方法**已去掉 self**），
     按实参形态落地：
       * `self.<名字>` → 调用点所在类的该方法（沿继承链）；
       * **裸名字且在本文件定义 → 本文件的函数 / 嵌套函数（闭包）/ 类**；来自
         `from X import f` 的裸名字 → 跨文件函数；
       * **裸名字是调用者自己的形参 → 递归进那个形参**（带 `seen` 防环）。
       其余形态（带点、带调用、表达式）一律**不猜**。候选唯一则记边，多个则入 `ambiguity`，
       判不出则入 `unresolved`。
       实例：① `geometry.stagger_source_anchors(model, grid, ports)` 的 `ports`，实参是
       `self.ports` → 候选 `Router.ports` / `LaneRouter.ports`（二选一 → `ambiguity`）；
       ② `LaneRouter._direct_cands(..., add)` 的 `add`，实参是 `_legs_ok` 里的**嵌套闭包**
       → 唯一目标 `LaneRouter._legs_ok.add`（→ 记边）。
   - **`getattr` 取属性再调用**：`v = getattr(<X>, '名字'[, 默认值])` 后 `v(...)` 或 `v.<方法>(...)`，
     其中 `<X>` 是 `self` 或 `self.<属性>`；按第 5 条解析（属性名是字面量，所以可确定性解析）。
     本项目唯一实例：`engine.Engine.lanes` 的 `fn = getattr(self.grid, 'lanes', None)` → `SwimGrid.lanes`。
     注意：`getattr(...)` **表达式本身**的目标永远是 builtin，必然判不出，那一条**不进缺口账本**，
     只计入 `stats.dynamic_dispatch_calls`（见第 7 条）。
   - **工厂返回类型 + 形参类型传播**（局部变量 `v = <项目函数>(...)`）：**只有**当一个项目函数
     **所有** `return` 都构造同一个项目类时（本项目唯一实例：`engine.load` 体内唯一的
     `return Engine(dsl)`），它的返回值类型才是确定的 → 记 `v` 的类型为该类；再把该类型沿
     **裸名字实参**传播到被调函数的对应形参（多点传播，最多 8 轮定循环）。
     例：`render_html.render` 的 `L = load(...)` → `_view_svg(L, …)` → `svg_node(L, n)` →
     `L.node_lines(nid)` 落成 `render_html.svg_node → engine.Engine.node_lines` 这条跨文件边。
     只认这一种最保守的形态：**不做**通用类型推断，**不认** `v = <某个类>(...)`（那是规则 4
     里"局部变量"口径的范围），判不出类型就仍是外部对象、不进账本。
7. **`unresolved`（覆盖率账本）**只收「看起来像调用、但静态判不出目标」的，**一条都不丢**，每条带
   `category`（稳定类目）与 `reason`（细节）：
   - `self.<方法>()` 在类及其项目内基类里都找不到（多为 dict/list 等外部对象的方法）；
   - `self.<属性>.<方法>()` 的候选类里都没有该方法；
   - 名字既非本文件定义、非 import 绑定、非形参、非已知局部可调用（可调用被存进变量）；
   - `from X import Y` 对象的 `.方法()` 调用（需通用类型推断）；
   - 形参派发的实参形态判不出（既非 `self.<名字>`、也非本文件函数/嵌套函数名、也非另一个形参）；
   - callee 无法静态求值的表达式；相对导入。
   它是判断「有没有项目函数被漏画」的依据，所以宁多勿漏。
   **`getattr` / `setattr` / `eval` / `exec` / `globals` / `locals` / `vars` / `__import__` 不进本账本**：
   这类动态派发的调用**表达式本身**目标必然是 builtin，判不出是机制使然而不是"漏了"，
   记进来只会淹掉真缺口。它们单独计入 `stats.dynamic_dispatch_calls`（只计数、不记边、不记条目）。
8. **`ambiguity`（真歧义账本）**与 `unresolved` 分开记：每条给 `candidates`（候选目标全表，
   形如 `模块.类.方法`）与 `reason`。这里的候选都是**已确认存在的项目函数**，只是运行期二选一，
   所以既不是缺口、也不能瞎挑一个当边。

## 模块顶层调用

`if __name__ == "__main__": main()` 这类入口必须有边，否则流程图会缺入口。
模块顶层（及类体）里的调用记 `from_fn = "<module>"`（类体记其类名）。

## 「顶层顺序段数」（segments）判据

把函数体**一级**语句按顺序扫一遍：`if` / `for` / `while` / `try` / `with` / `match` 这类复合语句
各自**切断**序列；连续的若干条「非复合语句」合并成 **1 段**（docstring 不计）。
`segments` = 这样数出来的段数。`segments >= 3` 时 md 记 `yes`（多个顶层顺序段）。
它只能提示「这段函数体是平铺的多段流水、中间被控制流切了几刀」，**不代表语义上真能拆**；
这是刻意定的可计算判据，判不出（函数体为空）记 `0`。

## dev/tools/fn-groups.json

对每个文件，取**同文件调用图的弱连通分量**（把同文件边无向化后连通即同组）。
- 图的节点 = 该文件的函数与方法（`kind` 为 `function` / `method`），**不含类**；
  指向本文件类的同文件边改指该类 `__init__`（构造即调 `__init__`），类本身不作节点，
  这样"所有函数必须落在某一组里"的分母才干净。
- 组按「成员最小行号」升序编号（`id` 从 1 起）。单成员组也列（可能是孤立工具函数）。
- `entry` = 组内被**组外**（跨文件调用方、或本文件 `<module>` 顶层）调用的成员，即该组入口。
- `called_from_outside` = 那些组外调用方，形如 `"build.py: main"`。

## dev/tools/fn-deps.json

模块级依赖，按**import 关系**汇总（不是调用关系）：
`calls_out` = {被导入文件: [导入的符号名]}，`called_by` = 反向索引。
`"*"` 表示整模块/星号导入。入度为 0 的文件谁都不 import 它（顶层入口候选）；
出度为 0 的文件不从 scripts 里拿任何东西（纯叶子）。

## 计数口径

`calls` 是**调用点**列表（同一对 from/to 可能多次出现，各自带 `lineno`）。
`stats.same_file_edges` / `cross_file_edges` 是**去重后的边数**；
`stats.same_file_calls` / `cross_file_calls` 是调用点数。md 报告里的数都与 `stats` 一致。
`stats.external_object_method_calls`（外部对象的方法调用）与 `stats.dynamic_dispatch_calls`
（`getattr`/`eval` 等动态派发）**只计数**：既不记边、也不进两本账，见规则 4 与规则 7。

## 退出码语义（与 equiv / api_audit / coverage 保持一致：0 / 1 / 2）

| 码 | 含义 | 触发条件 |
| ---: | --- | --- |
| `0` | **分析完成并写出产物** | 跑了且没坏。分析出什么都不影响本码 |
| `1` | **跑完了，但有需要人看的缺口/歧义** | `stats.parse_errors` 非空，**或** `unresolved` 超过 `REVIEW_UNRESOLVED`，**或** `ambiguity` 超过 `REVIEW_AMBIGUITY` |
| `2` | **仪器故障**（不是"图里有问题"） | 输入读不了（`scripts/` 不存在等）、产物写不出去、内部异常被捕获。给一句中文 `✗ …`，**不打 traceback** |

阈值口径：这两个阈值是**最近一次逐条复核归档的基线 + 25% 余量**，向上取整。
**最近一次标定（2026-09-14，第二轮收口：W3/W4/W5 拆分 + 形参派发支持嵌套闭包 +
`getattr` 移出缺口账本；标定时刻函数 477）——这是历史快照，不是当前值：**
**`unresolved` 基线 36、`ambiguity` 基线 16。**
⇒ `REVIEW_UNRESOLVED = 45`（36 × 1.25 = 45，向上取整）、
`REVIEW_AMBIGUITY = 20`（16 × 1.25 = 20，向上取整）。
**账本一旦增长超过余量就退 1**——它意味着出现了没人复核过的新缺口，所以宁可吵一次。
**余量 = 阈值 − 账本当前长度**（当前长度看 `dev/tools/fn-graph.json` 的 `stats`，阈值就是上面的
`REVIEW_UNRESOLVED` / `REVIEW_AMBIGUITY`；**不在这里手抄"还剩几条"**——抄了必然与盘上脱节）。
ambiguity 的余量小：一旦它变成 17 以上（例如又冒出一处 `Grid`/`SwimGrid` 或
`Router`/`LaneRouter` 的运行期二选一），**先人工读 `ambiguity` 清单确认是不是新形态**，
再决定"重新标定基线"还是"补解析规则"——**不许为了让 rc 变 0 而抬高这两个常量**。
重新标定的正确触发点：`scripts/` 又发生结构级改动（拆/并模块、大改调用形态）
**且账本已逐条重新复核归档**之后。
标定历史：44 / 16（拆分前，函数 296）→ 50 / 14（拆分后，函数 477）→ **36 / 16（本轮）**。
"""
import argparse
import ast
import builtins
import json
import sys
from collections import defaultdict
from pathlib import Path

# dev/ 是本文件的上一级——布局假设只表述一次（见 dev/_paths.py 与 D-66）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _paths import REPO as ROOT, SCRIPTS, TOOLS  # noqa: E402

OUT_JSON = TOOLS / "fn-graph.json"
OUT_GROUPS = TOOLS / "fn-groups.json"
OUT_DEPS = TOOLS / "fn-deps.json"
OUT_MD = TOOLS / "fn-graph.md"

# 退出码 1 的阈值（口径见模块 docstring「退出码语义」）：复核基线 + 25% 余量，向上取整。
# 基线标定于 2026-09-14（第二轮收口：拆分 + 形参派发支持嵌套闭包 + getattr 移出账本）：
# unresolved 36、ambiguity 16。
REVIEW_UNRESOLVED = 45
REVIEW_AMBIGUITY = 20

# 「本项目内的模块」= scripts/*.py 的文件名主干。标准库/第三方一律视作外部。
SCRIPT_MODULES = {p.stem for p in SCRIPTS.glob("*.py")}
MODULE_FN = "<module>"  # 模块顶层调用的伪函数名
DYNAMIC_NAMES = {"getattr", "setattr", "eval", "exec", "globals", "locals",
                 "vars", "__import__", "compile"}
BUILTINS = set(dir(builtins))
DEF_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
COMPOUND = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With,
            ast.AsyncWith, ast.Match)
# 可能承载"函数表"的字面量容器（dict 的元素是键值对，不作函数表）。
TABLE_LITERALS = (ast.Tuple, ast.List, ast.Set)


# ============================================================ 通用 AST 小工具
def child_bodies(st):
    """一条语句的各「子语句块」（不含函数/类定义体，那些是独立作用域）。"""
    out = []
    for field in ("body", "orelse", "finalbody"):
        val = getattr(st, field, None)
        if isinstance(val, list):
            out.append(val)
    for handler in (getattr(st, "handlers", None) or []):
        out.append(handler.body)
    return out


def walk_calls(root):
    """在 stmt 子树里找 Call，**不下钻**嵌套的函数/类定义（它们各自记账）。"""
    stack = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Call):
            yield node
        for child in ast.iter_child_nodes(node):
            if isinstance(child, DEF_NODES + (ast.ClassDef,)):
                continue
            stack.append(child)


def walk_names(root):
    """在 stmt 子树里找所有 Name 引用，同样不下钻嵌套定义。"""
    stack = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Name):
            yield node.id
        for child in ast.iter_child_nodes(node):
            if isinstance(child, DEF_NODES + (ast.ClassDef,)):
                continue
            stack.append(child)


def walk_assigns(root):
    """在 stmt 子树里找赋值语句，不下钻嵌套定义。"""
    stack = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Assign):
            yield node
        for child in ast.iter_child_nodes(node):
            if isinstance(child, DEF_NODES + (ast.ClassDef,)):
                continue
            stack.append(child)


def walk_returns(root):
    """在函数子树里找所有 Return，**不下钻**嵌套的函数/类定义。"""
    stack = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Return):
            yield node
        for child in ast.iter_child_nodes(node):
            if isinstance(child, DEF_NODES + (ast.ClassDef,)):
                continue
            stack.append(child)


def scope_facts(stmts):
    """某作用域直接语句里的 Call 与 Name 引用（跳过嵌套定义）。"""
    calls, names = [], set()
    for st in stmts:
        if isinstance(st, DEF_NODES + (ast.ClassDef,)):
            continue
        calls.extend(walk_calls(st))
        names.update(walk_names(st))
    return calls, names


def count_segments(stmts):
    """顶层顺序段数：连续的非复合语句算 1 段，复合语句各自切断（docstring 不计）。"""
    segs, in_run = 0, False
    for st in stmts:
        if isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant) and isinstance(st.value.value, str):
            continue                                   # docstring 不计
        if isinstance(st, COMPOUND):
            in_run = False
            segs += 1
        elif not in_run:
            in_run = True
            segs += 1
    return segs


def unparse(node):
    try:
        return ast.unparse(node)
    except Exception:
        return "<expr>"


def categorize(reason):
    """把 detail 级 reason 归到稳定的类目，供 JSON 消费与 md 分组。"""
    if reason.startswith("self.") and "候选类里" in reason:
        return "self.<属性>.<方法>()：候选类里没有该方法"
    if reason.startswith("self.") and "不是" in reason and "项目类实例" in reason:
        return "self.<属性>.<方法>()：属性不是项目类实例（dict/list 等，假缺口）"
    if reason.startswith("self."):
        return "self.<方法>() 在类及其项目内基类里找不到（多为 dict/list 等外部对象方法）"
    if reason.startswith("形参派发"):
        return "形参派发：实参形态判不出"
    if "来自 from " in reason:
        return "from X import Y 的对象方法调用（需类型推断）"
    if reason.startswith("名字 `"):
        return "可调用被存进变量后再调用"
    if reason.startswith("callee 无法静态求值"):
        return "callee 无法静态求值（订阅 / lambda / 调用结果）"
    if reason.startswith("相对导入"):
        return "相对导入"
    return reason


# ================================================================ import 模型
def make_bindings(import_nodes):
    """import 语句 -> {绑定名: {kind, module, symbol, is_script}}。

    kind ∈ module（import X）/ symbol（from X import a）/ star / relative。
    """
    bindings = {}
    for st in import_nodes:
        if isinstance(st, ast.Import):
            for alias in st.names:
                top = alias.name.split(".")[0]
                bindings[alias.asname or top] = {
                    "kind": "module", "module": alias.name, "symbol": None,
                    "is_script": top in SCRIPT_MODULES, "lineno": st.lineno,
                    "display": alias.name,
                }
        elif isinstance(st, ast.ImportFrom):
            module = st.module or ""
            if st.level:  # 相对导入：平铺目录用不到，只记录
                for alias in st.names:
                    bindings[alias.asname or alias.name] = {
                        "kind": "relative", "module": "." * st.level + module,
                        "symbol": alias.name, "is_script": False, "lineno": st.lineno,
                        "display": unparse(st),
                    }
                continue
            for alias in st.names:
                if alias.name == "*":
                    bindings["*"] = {
                        "kind": "star", "module": module, "symbol": "*",
                        "is_script": module in SCRIPT_MODULES, "lineno": st.lineno,
                        "display": f"{module}.*",
                    }
                else:
                    bindings[alias.asname or alias.name] = {
                        "kind": "symbol", "module": module, "symbol": alias.name,
                        "is_script": module in SCRIPT_MODULES, "lineno": st.lineno,
                        "display": f"{module}.{alias.name}",
                    }
    return bindings


def collect_scope_imports(stmts, scope_key, out):
    """收集某作用域里直接出现的 import（下钻 if/try/with 等复合语句，不进嵌套定义）。"""
    bucket = out.setdefault(scope_key, {})
    plain = []
    for st in stmts:
        if isinstance(st, DEF_NODES + (ast.ClassDef,)):
            continue
        if isinstance(st, (ast.Import, ast.ImportFrom)):
            plain.append(st)
        else:
            for body in child_bodies(st):
                collect_scope_imports(body, scope_key, out)
    if plain:
        bucket.update(make_bindings(plain))
    return out


# ================================================================== 定义清单
def walk_scope(stmts, prefix, scope_key, parent_key, in_class_body, cls_qual,
               entries, scope_defs, scope_parent):
    """递归登记所有作用域里的函数/类定义；`scope_defs` 供名字解析用。"""
    local = scope_defs.get(scope_key)
    if local is None:
        local = scope_defs[scope_key] = {}
        scope_parent[scope_key] = parent_key
    for st in stmts:
        if isinstance(st, DEF_NODES):
            qualname = prefix + st.name
            local[st.name] = qualname
            entries.append({
                "name": st.name, "qualname": qualname,
                "kind": "method" if in_class_body else "function",
                "node": st, "lineno": st.lineno,
                "endlineno": getattr(st, "end_lineno", st.lineno),
                "public": not st.name.startswith("_"),
                "scope_key": qualname, "parent_key": scope_key,
                "parent_cls": cls_qual,
            })
            # 函数体是独立作用域；类上下文向下传，让嵌套闭包里的 self.x() 仍能解析。
            walk_scope(st.body, qualname + ".", qualname, scope_key, False, cls_qual,
                       entries, scope_defs, scope_parent)
        elif isinstance(st, ast.ClassDef):
            qualname = prefix + st.name
            local[st.name] = qualname
            entries.append({
                "name": st.name, "qualname": qualname, "kind": "class",
                "node": st, "lineno": st.lineno,
                "endlineno": getattr(st, "end_lineno", st.lineno),
                "public": not st.name.startswith("_"),
                "scope_key": qualname, "parent_key": scope_key,
                "parent_cls": cls_qual,
            })
            walk_scope(st.body, qualname + ".", qualname, scope_key, True, qualname,
                       entries, scope_defs, scope_parent)
        else:
            for body in child_bodies(st):
                walk_scope(body, prefix, scope_key, parent_key, in_class_body, cls_qual,
                           entries, scope_defs, scope_parent)
    return local


def scope_chain(scope_key, scope_parent):
    """由内向外的作用域链，末位是模块作用域 ""。"""
    chain, seen = [], set()
    key = scope_key
    while key is not None and key not in seen:
        chain.append(key)
        seen.add(key)
        key = scope_parent.get(key)
    return chain


# =============================================================== 全项目类索引
def _key(module, qualname):
    return f"{module}.{qualname}"


def _base_key(module, base, module_imports, class_keys):
    """把基类表达式解析成项目内类键 `模块.类`；外部基类（如 str）返回 None。"""
    if isinstance(base, ast.Name):
        if _key(module, base.id) in class_keys:
            return _key(module, base.id)
        binding = module_imports.get(base.id)
        if binding and binding["kind"] == "symbol" and binding["is_script"]:
            candidate = _key(binding["module"], binding["symbol"])
            if candidate in class_keys:
                return candidate
    elif isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name):
        binding = module_imports.get(base.value.id)
        if binding and binding["kind"] == "module" and binding["is_script"]:
            candidate = _key(binding["module"], base.attr)
            if candidate in class_keys:
                return candidate
    return None


def _factory_key(module, call, module_imports, scope_defs):
    """`v = <call>(...)` 的右值若调用一个**项目函数**，返回该函数的键 `模块.函数`；否则 None。

    这里只做「名字 → 函数键」这一步，函数是否真有确定的返回类型交给 `func_returns` 判定。
    """
    func = call.func
    if isinstance(func, ast.Name):
        kind, payload, _ = resolve_name(func.id, [""], scope_defs, {"": module_imports})
        if kind == "same":
            return _key(module, payload)
        if kind == "cross":
            return _key(payload[0], payload[1])
        return None
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        binding = module_imports.get(func.value.id)
        if binding and binding["kind"] == "module" and binding["is_script"]:
            return _key(binding["module"], func.attr)
    return None


def _class_of_call(module, value, module_imports, class_keys):
    """`self.<attr> = <RHS>` 里 RHS 是否构造了某个项目类；是则返回类键。"""
    if isinstance(value, ast.IfExp):
        return _class_of_call(module, value.body, module_imports, class_keys) or \
               _class_of_call(module, value.orelse, module_imports, class_keys)
    if isinstance(value, ast.Call):
        func = value.func
        if isinstance(func, ast.Name):
            if _key(module, func.id) in class_keys:
                return _key(module, func.id)
            binding = module_imports.get(func.id)
            if binding and binding["kind"] == "symbol" and binding["is_script"]:
                candidate = _key(binding["module"], binding["symbol"])
                if candidate in class_keys:
                    return candidate
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            binding = module_imports.get(func.value.id)
            if binding and binding["kind"] == "module" and binding["is_script"]:
                candidate = _key(binding["module"], func.attr)
                if candidate in class_keys:
                    return candidate
    return None


def build_project_index():
    """一遍解析全部文件，建跨文件解析所需的索引。

    含：类->{方法, 已解析的基类} / 类->{self.属性 -> 候选项目类} /
    标识符->调用点（形参派发要用） / 模块->字面量函数表（表派发要用）。
    基类与 `self.属性` 的候选都在这里解析成 `模块.类` 键，后续解析不再需要 import 表。
    """
    parsed = []
    for path in sorted(SCRIPTS.glob("*.py")):
        module, rel = path.stem, f"scripts/{path.name}"
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
        except Exception:
            continue
        module_imports = collect_scope_imports(tree.body, "", {}).get("", {})
        entries, scope_defs, scope_parent = [], {}, {}
        walk_scope(tree.body, "", "", None, False, None, entries, scope_defs, scope_parent)
        parsed.append({"module": module, "tree": tree, "imports": module_imports,
                       "defs": scope_defs, "entries": entries})

    index = {"classes": {}, "attr_cand": defaultdict(dict), "callee_sites": defaultdict(list),
             "tables": defaultdict(dict), "param_pos": {}, "attr_from_param": defaultdict(dict),
             "sites_by_target": defaultdict(list), "subclasses": {}, "func_returns": {},
             "factory_vars": {}, "param_classes": defaultdict(dict), "site_args": [],
             "sites_by_target_fn": defaultdict(list), "scope_defs": {}, "module_imports": {}}

    # ① 先集齐所有类键（基类解析要能查全项目）
    class_keys = {_key(p["module"], e["qualname"])
                  for p in parsed for e in p["entries"] if e["kind"] == "class"}

    # ② 类 -> 方法 + 已解析基类
    for p in parsed:
        for e in p["entries"]:
            if e["kind"] != "class":
                continue
            info = {"methods": {m.name for m in e["node"].body if isinstance(m, DEF_NODES)},
                    "bases": [], "file": f"scripts/{p['module']}.py"}
            for base in e["node"].bases:
                key = _base_key(p["module"], base, p["imports"], class_keys)
                if key and key not in info["bases"]:
                    info["bases"].append(key)
            index["classes"][_key(p["module"], e["qualname"])] = info

    # ③ 类 -> {self.<属性>: 候选项目类集合}；self.<属性> = <构造形参> 也登记下来
    for p in parsed:
        for e in p["entries"]:
            if e["kind"] != "class":
                continue
            bucket = index["attr_cand"][_key(p["module"], e["qualname"])]
            from_param = index["attr_from_param"][_key(p["module"], e["qualname"])]
            for assign in (n for n in ast.walk(e["node"]) if isinstance(n, ast.Assign)):
                target = _class_of_call(p["module"], assign.value, p["imports"], class_keys)
                if target:
                    for tg in assign.targets:
                        if (isinstance(tg, ast.Attribute) and isinstance(tg.value, ast.Name)
                                and tg.value.id == "self"):
                            bucket.setdefault(tg.attr, set()).add(target)
                elif (isinstance(assign.value, ast.Name)
                      and not any(isinstance(n2, ast.Call) for n2 in ast.walk(assign.value))):
                    # self.<属性> = <裸形参名>：候选由调用点实参决定（如 Router(self, model, grid)）
                    for tg in assign.targets:
                        if (isinstance(tg, ast.Attribute) and isinstance(tg.value, ast.Name)
                                and tg.value.id == "self"):
                            owner = _key(p["module"], e["qualname"])
                            pair = (owner, assign.value.id)
                            if pair not in from_param.setdefault(tg.attr, []):
                                from_param[tg.attr].append(pair)

    # ④ 形参位置表（函数用自身签名；方法去掉 self/首参；类用 __init__ 的签名，
    #    对应 `类名(...)` 的实参下标）
    for p in parsed:
        for e in p["entries"]:
            if e["kind"] == "class":
                continue
            args = list(e["node"].args.posonlyargs) + list(e["node"].args.args)
            if e["kind"] == "method" and args:
                args = args[1:]                       # 去掉 self
            index["param_pos"][_key(p["module"], e["qualname"])] = {
                a.arg: i for i, a in enumerate(args)}
        for e in p["entries"]:
            if e["kind"] != "class":
                continue
            path = index["param_pos"].get(_key(p["module"], e["qualname"] + ".__init__"))
            if path is not None:
                index["param_pos"][_key(p["module"], e["qualname"])] = path

    # ⑤ 子类索引：基类方法里的 self.<属性> 要按**实际子类**求候选（如 RectCache 的混入）
    for key, info in index["classes"].items():
        for base in info["bases"]:
            index["subclasses"].setdefault(base, set()).add(key)
    for key in index["classes"]:
        seen, stack, subs = {key}, list(index["subclasses"].get(key, ())), set()
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            subs.add(cur)
            stack.extend(index["subclasses"].get(cur, ()))
        index["subclasses"][key] = subs

    # ⑤b 工厂函数返回类型：**所有** return 都是同一个项目类的构造 → 该函数返回该类。
    #     只认这种最保守的形态（如 `engine.load` 里唯一的 `return Engine(dsl)`），
    #     用于把 `L = load(...)` 之后的 `L.<方法>()` 落到真实类上。
    index["func_returns"] = {}
    for p in parsed:
        for e in p["entries"]:
            if e["kind"] == "class":
                continue
            returns = [n.value for n in walk_returns(e["node"]) if n.value is not None]
            if not returns:
                continue
            found = set()
            for rv in returns:
                cls = _class_of_call(p["module"], rv, p["imports"], class_keys)
                if not cls:
                    found = set()
                    break
                found.add(cls)
            if len(found) == 1:
                index["func_returns"][_key(p["module"], e["qualname"])] = next(iter(found))

    # ⑤c 工厂型「局部变量」索引：`v = <返回类型已落地的项目函数>(...)` → {函数键: {变量名: 类键}}
    #     只对右值本身是一次调用的赋值生效；落在具体作用域上（同名的形参另行判定）。
    index["factory_vars"] = {}
    for p in parsed:
        module = p["module"]
        scopes = [(e["node"].body, e["qualname"]) for e in p["entries"]
                  if e["kind"] != "class"]
        scopes.append((p["tree"].body, MODULE_FN))
        for stmts, qualname in scopes:
            for var, call in collect_local_calls(stmts).items():
                key = _factory_key(module, call, p["imports"], p["defs"])
                if not key:
                    continue
                ret = index["func_returns"].get(key)
                if ret:
                    index["factory_vars"].setdefault(_key(module, qualname), {})[var] = ret

    # ⑥ 调用点（形参派发要用）：按标识符与按解析出的目标各存一份；
    #    顺带收集「调用方作用域 → 被调函数 → 实参表」，供 ⑦ 形参类型传播。
    #    `sites_by_target_fn` 是**形参派发专用**的更全版本：除了 `f(...)`，还收
    #    `self.f(...)`（方法调用），因为「实参是本文件嵌套闭包」的实例正是它。
    for p in parsed:
        index["scope_defs"][p["module"]] = p["defs"]
        index["module_imports"][p["module"]] = p["imports"]
    for p in parsed:
        module = p["module"]
        scopes = [(e["node"].body, e["qualname"], e["parent_cls"]) for e in p["entries"]
                  if e["kind"] != "class"]
        scopes.append((p["tree"].body, MODULE_FN, None))
        for stmts, qualname, cls in scopes:
            for call in scope_facts(stmts)[0]:
                args = [unparse(a) for a in call.args]
                target_key = None
                if isinstance(call.func, ast.Name):
                    index["callee_sites"][call.func.id].append((module, qualname, cls, args))
                    kind, payload, _ = resolve_name(call.func.id, [""], p["defs"],
                                                    {"": p["imports"]})
                    if kind == "same":
                        target_key = _key(module, payload)
                    elif kind == "cross":
                        target_key = _key(payload[0], payload[1])
                    if target_key:
                        index["sites_by_target"][target_key].append((module, cls, args))
                        index["site_args"].append((_key(module, qualname), target_key, args))
                elif (isinstance(call.func, ast.Attribute) and cls
                      and isinstance(call.func.value, ast.Name)
                      and call.func.value.id == "self"):
                    found = resolve_self_method(module, cls, call.func.attr, index)
                    if found:
                        mod, rest = split_target(found + "." + call.func.attr)
                        target_key = _key(mod, rest)
                if target_key:
                    index["sites_by_target_fn"][target_key].append(
                        (module, qualname, cls, args))
        for st in p["tree"].body:
            if isinstance(st, ast.Assign) and isinstance(st.value, TABLE_LITERALS):
                elts = list(st.value.elts)
                names = [x.id for x in elts if isinstance(x, ast.Name)]
                if names and len(names) == len(elts):
                    for tg in st.targets:
                        if isinstance(tg, ast.Name):
                            index["tables"][module][tg.id] = names

    # ⑦ 形参类型传播（有界定点）：实参是「类型已落地」的裸名字（工厂型局部变量，
    #    或已被传播出类型的形参）时，把类型落到被调函数的对应形参上。
    #    只认裸名字实参；循环最多 8 轮，集合不再增长即停。
    for _round in range(8):
        changed = False
        for caller_key, target_key, args in index["site_args"]:
            typed = {}
            for name, cls_key in index["factory_vars"].get(caller_key, {}).items():
                typed.setdefault(name, set()).add(cls_key)
            for name, clss in index["param_classes"].get(caller_key, {}).items():
                typed.setdefault(name, set()).update(clss)
            pos2name = {v: k for k, v in index["param_pos"].get(target_key, {}).items()}
            for i, arg in enumerate(args):
                if "." in arg or "(" in arg:
                    continue
                clss = typed.get(arg)
                name = pos2name.get(i)
                if not clss or not name:
                    continue
                slot = index["param_classes"].setdefault(target_key, {}).setdefault(name, set())
                add = set(clss) - slot
                if add:
                    slot |= add
                    changed = True
        if not changed:
            break
    return index


# ===================================================================== 解析器
def param_type_candidates(owner_key, param, index):
    """形参的候选项目类：来自全项目调用点里「工厂型局部变量」实参（类型已落地）。"""
    return set(index["param_classes"].get(owner_key, {}).get(param, ()))


def param_type_targets(alias, member, frame, index):
    """`<形参>.<成员>()` → 候选目标集合（形参实参是工厂型局部变量时才知道类型）。"""
    targets = set()
    for cls_key in param_type_candidates(frame["owner_key"], alias, index):
        mod, _, cls_name = cls_key.partition(".")
        found = resolve_self_method(mod, cls_name, member, index)
        if found:
            targets.add(f"{found}.{member}")
    return targets


def resolve_self_method(module, cls_qual, member, index):
    """`self.<member>()`：在本类与项目内基类里找同名方法（含继承链）。返回 `模块.类` 或 None。"""
    if not cls_qual:
        return None
    queue, seen = [_key(module, cls_qual)], set()
    while queue:
        key = queue.pop(0)
        if key in seen:
            continue
        seen.add(key)
        info = index["classes"].get(key)
        if not info:
            continue
        if member in info["methods"]:
            return key
        for base in info["bases"]:
            if base not in seen:
                queue.append(base)
    return None


def param_candidate_classes(owner_key, param, index, guard):
    """形参/构造参数的候选项目类：来自全项目里对该函数的调用点实参。

    `owner_key` 既是函数键 `模块.函数`，也是类键 `模块.类`（类用 `__init__` 的形参位置，
    对应 `类名(...)` 的实参）。实参形如 `self.<名字>` 时，用调用方类的属性候选去递归。
    """
    pos = index["param_pos"].get(owner_key, {}).get(param)
    if pos is None:
        return set()
    out = set()
    for site_module, site_cls, args in index["sites_by_target"].get(owner_key, ()):
        if pos >= len(args):
            continue
        arg = args[pos]
        if not arg.startswith("self.") or "." in arg[5:]:
            continue
        out |= attr_candidate_classes(site_module, site_cls, arg[5:], index, guard)
    return out


def attr_candidate_classes(module, cls_qual, attr, index, guard=None):
    """`self.<attr>` 的候选项目类集合。

    三处来源合并：① 本类里 `self.<attr> = <项目类>(...)`；
    ② 本类（或其**子类**，混入情形如 `geometry.RectCache`）里 `self.<attr> = <构造形参>`，
    由调用点实参回溯；③ 子类里的 ①②。带 `guard` 防递归。
    """
    if not cls_qual:
        return set()
    guard = guard or set()
    out = set()
    for key in sorted({_key(module, cls_qual)} | index["subclasses"].get(
            _key(module, cls_qual), set())):
        if key in guard:
            continue
        inner = guard | {key}
        out |= set(index["attr_cand"].get(key, {}).get(attr, ()))
        for owner_key, param in index["attr_from_param"].get(key, {}).get(attr, ()):
            out |= param_candidate_classes(owner_key, param, index, inner)
    return out


def attr_dispatch_targets(module, cls_qual, attr, member, index):
    """解析 `self.<attr>.<member>()` → (去重候选目标集合, self.<attr> 的候选类集合)。

    目标是 `模块.类.成员`；空集表示候选类里都没有这个成员。
    """
    classes = attr_candidate_classes(module, cls_qual, attr, index, set())
    targets = set()
    for cls_key in classes:
        mod, _, cls_name = cls_key.partition(".")
        found = resolve_self_method(mod, cls_name, member, index)
        if found:
            targets.add(f"{found}.{member}")
    return targets, classes


def split_target(target):
    """`模块.类.成员` -> (模块, 类.成员)。"""
    module, _, rest = target.partition(".")
    return module, rest


def resolve_name(name, chain, scope_defs, scope_imports):
    """`name(...)` → 边 / 外部 / unresolved。"""
    for scope in chain:                       # 1) 本文件定义（含嵌套函数）
        target = scope_defs.get(scope, {}).get(name)
        if target:
            return ("same", target, None)
    for scope in chain:                       # 2) import 绑定
        binding = scope_imports.get(scope, {}).get(name)
        if not binding:
            continue
        kind = binding["kind"]
        if kind == "relative":
            return ("unresolved", None, f"相对导入 {binding['display']}，静态判不出目标")
        if kind == "star":
            if binding["is_script"]:          # from X import *：来源模块已知，尽力给跨文件边
                return ("cross", (binding["module"], name), None)
            return ("external", None, None)
        if kind == "module":
            return ("external", None, None)
        if binding["is_script"]:              # from X import f
            return ("cross", (binding["module"], binding["symbol"]), None)
        return ("external", None, None)
    if name in BUILTINS:
        return ("external", None, None)
    return ("unresolved", None, f"名字 `{name}` 既非本文件定义也非 import 绑定（可调用被存进变量？）")


def _edge_or_ambiguity(targets, reason_prefix):
    """把候选目标集合落成 边 / ambiguity / unresolved 三种结果。"""
    if len(targets) == 1:
        module, to_fn = split_target(next(iter(targets)))
        return ("cross", (module, to_fn), None)
    if len(targets) > 1:
        return ("ambiguous", sorted(targets),
                f"{reason_prefix}：候选明确但运行期才定（{len(targets)} 个候选）")
    return None


def resolve_attr(alias, member, frame, scope_defs, scope_imports, index):
    """`alias.member(...)` → 边 / 外部 / unresolved / ambiguity。"""
    # 0) 局部变量由 getattr(self[.attr], '名字') 赋值 → 按属性解析
    #    或由工厂函数赋值（类型已落地）→ 按该类的成员解析
    binding = frame["attr_vars"].get(alias)
    if binding is not None:
        if binding[0] == "factory":
            if member is None:
                return ("external_obj", None, None)   # 实例本身被调用，不追
            module, _, cls_name = binding[1].partition(".")
            found = resolve_self_method(module, cls_name, member, index)
            if not found:
                return ("unresolved", None,
                        f"{alias}.{member}()：{alias} 是工厂返回值（项目类 {binding[1]}），"
                        f"但该类及其项目内基类里没有成员 {member}")
            module, rest = split_target(found + "." + member)
            if module == frame["stem"]:
                return ("same", rest, None)
            return ("cross", (module, rest), None)
        return resolve_attr_var(binding, member, frame, index)
    if alias == "self":
        found = resolve_self_method(frame["stem"], frame["cls_qual"], member, index)
        if found:
            module, rest = split_target(found + "." + member)
            if module == frame["stem"]:
                return ("same", rest, None)
            return ("cross", (module, rest), None)
        return ("unresolved", None,
                f"self.{member}() 在类 {frame['cls_qual'] or '?'} 及其项目内基类里都找不到"
                "（可能是 dict/list 等外部对象的方法，或运行期赋值的属性）")
    if alias in frame["params"]:
        # 形参：若所有可解析的调用点都传「同一类型的工厂型局部变量」，类型就落地了 → 按该类型解析
        result = _edge_or_ambiguity(param_type_targets(alias, member, frame, index),
                                    f"形参 {alias}.{member}()")
        if result:
            return result
        return ("external_obj", None, None)   # 实参类型未知 → 外部对象口径，不进账本
    for scope in frame["chain"]:
        if alias in scope_defs.get(scope, {}):
            return ("external", None, None)   # 对已定义函数取属性再调（罕见），不追
    for scope in frame["chain"]:
        imp = scope_imports.get(scope, {}).get(alias)
        if not imp:
            continue
        if imp["kind"] == "relative":
            return ("unresolved", None, f"相对导入 {imp['display']}，静态判不出目标")
        if imp["kind"] == "module":
            if imp["is_script"]:              # import X → X.f() 跨文件边
                return ("cross", (imp["module"], member), None)
            return ("external", None, None)
        if imp["kind"] in ("symbol", "star"):
            if imp["is_script"]:              # from X import Y → Y.m()，需通用类型推断
                return ("unresolved", None,
                        f"`{alias}` 来自 from {imp['module']} import …，其 .{member}() 需类型推断")
            return ("external", None, None)
    if alias in BUILTINS:
        return ("external", None, None)
    return ("external_obj", None, None)       # 普通局部变量/形参的方法调用：外部对象


def resolve_attr_var(binding, member, frame, index):
    """`v = getattr(<X>, '名字')` 之后 `v(...)`（member=None）或 `v.<member>()`。"""
    if binding[0] == "factory":
        return ("external_obj", None, None)   # 工厂返回的实例被直接调用：不追（同局部变量口径）
    if binding[0] == "selfattr":              # v = getattr(self.<attr>, '名字', ...)
        attr, name = binding[1], binding[2]
    else:                                     # v = getattr(self, '<attr>', ...) → v 就是 self.<attr>
        attr, name = binding[1], member
    if binding[0] == "self" and member is None:
        # v 自己就是 self.<attr>：v() 即 self.<attr>()，按方法解析
        found = resolve_self_method(frame["stem"], frame["cls_qual"], attr, index)
        if found:
            module, rest = split_target(found + "." + attr)
            if module == frame["stem"]:
                return ("same", rest, None)
            return ("cross", (module, rest), None)
        return ("unresolved", None, f"getattr(self, '{attr}') 在类里找不到该方法")
    if name is None:
        return ("unresolved", None, "getattr 结果被当作属性链调用，判不出成员名")
    targets, _classes = attr_dispatch_targets(frame["stem"], frame["cls_qual"], attr, name, index)
    result = _edge_or_ambiguity(targets, f"getattr(self.{attr},'{name}')")
    if result:
        return result
    return ("unresolved", None,
            f"getattr(self.{attr},'{name}') 的候选类里都没有 {name}（或 self.{attr} 不是项目类实例）")


def resolve_param_dispatch(param, frame, index):
    """函数内调用自己的形参 → 由全项目调用点的实参推断候选目标。"""
    if param not in frame["params"]:
        return None
    owner_key = frame["owner_key"]
    # 位置必须用 `index["param_pos"]`（**方法已去掉 self**），因为调用点的 `args` 是
    # `call.args`（不含 self）。`frame["params"]` 含 self，对方法会整体差 1 —— 早先
    # 就是用 frame["params"] 取位置，导致 `_direct_cands(..., add)` 这个第 10 个实参
    # 被判成"越界"，`add` 这条真边一直没落上。
    pos = index["param_pos"].get(owner_key, {}).get(param)
    if pos is None:
        return None
    targets = param_call_candidates(owner_key, pos, index, frozenset())
    result = _edge_or_ambiguity(targets, f"形参派发 {param}()")
    if result:
        return result
    if param_type_candidates(owner_key, param, index):
        # 形参类型已落地（实参是工厂型局部变量），但这是对**实例**的调用（不是项目函数），不追
        return ("external_obj", None, None)
    return ("unresolved", None,
            f"形参派发 {param}()：实参形态判不出（{frame['fn_name']} 的调用点里第 {pos} 个实参"
            "既不是 self.<名字>、也不是本文件函数/嵌套函数名、也不是另一个形参）")


def param_call_candidates(owner_key, pos, index, seen):
    """全项目里调用 `owner_key` 时，第 `pos` 个实参可能指向的**项目目标**集合。

    实参形态只有三种能静态落地（其余一律不猜、返回空集）：
      A. `self.<名字>`            → 调用点所在类的该方法（沿继承链）；
      B. 裸名字且在本文件定义      → 本文件的函数 / **嵌套函数（闭包）** / 类；
         裸名字来自 `from X import f` → 跨文件函数。
      C. 裸名字是**调用者自己的形参** → 递归进那个形参（例：`_place_offset(ports)` 的
         `ports` 来自 `stagger_source_anchors` 的 `ports`，而后者在全项目里的实参是
         `self.ports` → 候选 `Router.ports` / `LaneRouter.ports`）。
        递归带 `seen` 防环。
    """
    if owner_key in seen or owner_key is None:
        return set()
    seen = seen | {owner_key}
    out = set()
    for site_module, site_fn, site_cls, args in index["sites_by_target_fn"].get(owner_key, ()):
        if pos >= len(args):
            continue
        arg = args[pos]
        # A) self.<名字>
        if arg.startswith("self.") and "." not in arg[5:] and site_cls:
            found = resolve_self_method(site_module, site_cls, arg[5:], index)
            if found:
                out.add(f"{found}.{arg[5:]}")
            continue
        if not arg.isidentifier():
            continue                        # 表达式/带点/带调用 → 不猜
        # B) 本文件定义（含嵌套闭包）或本文件 import 进来的项目函数
        defs = index["scope_defs"].get(site_module, {})
        imports = {"": index["module_imports"].get(site_module, {})}
        kind, payload, _ = resolve_name(arg, qualname_chain(site_fn), defs, imports)
        if kind == "same":
            out.add(_key(site_module, payload))
            continue
        if kind == "cross":
            out.add(_key(payload[0], payload[1]))
            continue
        # C) 该名字是调用者自己的形参 → 递归
        caller_key = _key(site_module, site_fn)
        caller_pos = index["param_pos"].get(caller_key, {}).get(arg)
        if caller_pos is not None:
            out |= param_call_candidates(caller_key, caller_pos, index, seen)
    return out


def qualname_chain(qualname):
    """由内向外的作用域链（只靠 qualname 的逐层前缀推出来），末位是模块作用域 ""。"""
    parts = qualname.split(".")
    return [".".join(parts[:i + 1]) for i in range(len(parts))][::-1] + [""]


def resolve_dispatch_table(var, frame, scope_defs, scope_imports):
    """`for var in <本文件模块级字面量表>:` 的 var 调用 → 表内每个函数各记一条边。

    表是字面量的，所以表内成员每次都会被调用 —— 每个成员记一条边，不是歧义。
    """
    elements = frame["tables"].get(var)
    if not elements:
        return None
    targets = []
    for name in elements:
        kind, payload, _ = resolve_name(name, [""], scope_defs, scope_imports)
        if kind in ("same", "cross"):
            targets.append((kind, payload))
    if not targets:
        return None
    return ("table", targets, f"函数表派发：表内 {len(targets)} 个函数都会被调用")


def classify(func_node, frame, scope_defs, scope_imports, index):
    if isinstance(func_node, ast.Name):
        name = func_node.id
        if name in DYNAMIC_NAMES and name in BUILTINS:
            return ("dynamic", name, f"动态派发 {name}()")
        if name in frame["attr_vars"] or name in frame["params"]:
            result = (resolve_attr_var(frame["attr_vars"][name], None, frame, index)
                      if name in frame["attr_vars"]
                      else None)
            if result is None:
                result = resolve_param_dispatch(name, frame, index)
            if result:
                return result
        result = resolve_dispatch_table(name, frame, scope_defs, scope_imports)
        if result:
            return result
        return resolve_name(name, frame["chain"], scope_defs, scope_imports)
    if isinstance(func_node, ast.Attribute):
        base = func_node.value
        if isinstance(base, ast.Name):
            return resolve_attr(base.id, func_node.attr, frame, scope_defs, scope_imports, index)
        if isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name):
            if base.value.id == "self":       # self.<属性>.<方法>()
                targets, classes = attr_dispatch_targets(
                    frame["stem"], frame["cls_qual"], base.attr, func_node.attr, index)
                if classes:
                    result = _edge_or_ambiguity(
                        targets, f"self.{base.attr}.{func_node.attr}()")
                    if result:
                        return result
                    return ("unresolved", None,
                            f"self.{base.attr}.{func_node.attr}()：候选类 "
                            f"{sorted(classes)} 里都没有 {func_node.attr}")
                return ("unresolved", None,
                        f"self.{base.attr}.{func_node.attr}()：self.{base.attr} 不是"
                        "在类（或其子类）里赋过值的项目类实例（多为 dict/list 等外部对象）")
            # 局部变量 = getattr(self[.attr], '名字') 之后的 v.<方法>()
            binding = frame["attr_vars"].get(base.value.id)
            if binding is not None:
                return resolve_attr_var(binding, func_node.attr, frame, index)
        return ("external", None, None)       # os.path.join(...) 这类链式，视为外部
    return ("unresolved", None, f"callee 无法静态求值：{unparse(func_node)}")


# ================================================================== 单文件分析
def analyze_file(path, rel, index):
    # `unparsed` 让消费方能区分"这个文件真没有函数"与"这个文件没读动"（后者会被 coverage
    # 当成"分母里没有它"，覆盖率因此虚高——见 coverage.py 的 parse_errors 处理）。
    record = {"lines": 0, "doc": "", "functions": [], "unparsed": False}
    stem = path.stem
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:                  # 读不了也按解析失败记，不中断
        record["unparsed"] = True
        return record, None, {"file": rel, "error": f"{type(exc).__name__}: {exc}"}
    record["lines"] = len(text.splitlines())
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        record["unparsed"] = True
        return record, None, {"file": rel, "error": f"SyntaxError: {exc}"}
    except Exception as exc:
        record["unparsed"] = True
        return record, None, {"file": rel, "error": f"{type(exc).__name__}: {exc}"}

    doc = ast.get_docstring(tree) or ""
    record["doc"] = doc.splitlines()[0].strip() if doc else ""

    entries, scope_defs, scope_parent = [], {}, {}
    walk_scope(tree.body, "", "", None, False, None, entries, scope_defs, scope_parent)

    scope_imports = {}
    collect_scope_imports(tree.body, "", scope_imports)
    for entry in entries:
        collect_scope_imports(entry["node"].body, entry["scope_key"], scope_imports)

    # `imports` 表：全文件（各作用域合并）里来自 scripts 的 import
    aggregated = defaultdict(set)
    for st in ast.walk(tree):
        if isinstance(st, (ast.Import, ast.ImportFrom)):
            for _name, binding in make_bindings([st]).items():
                if binding["is_script"]:
                    aggregated[binding["module"]].add(binding["symbol"] or "*")
    imports_table = {mod: sorted(syms, key=lambda s: (s != "*", s))
                     for mod, syms in sorted(aggregated.items())}

    calls, unresolved, ambiguity = [], [], []
    external_obj = [0]
    dynamic = [0]

    def make_frame(from_fn, chain, cls_qual, node_body, fn_name, params):
        attr_vars = collect_attr_vars(node_body)
        # 工厂返回类型：`v = <项目函数>(...)`，若该函数**所有** return 都是同一个项目类
        # 的构造，则 v 的类型确定 → 记 `("factory", "模块.类")`，供 v.<方法>() 落边。
        # 这是全图里唯一对「局部变量」做类型落地的地方，且只认这一种最保守的形态。
        for var, call in collect_local_calls(node_body).items():
            if var in attr_vars:
                continue
            fn = call.func
            key = None
            if isinstance(fn, ast.Name):
                kind, payload, _ = resolve_name(fn.id, chain, scope_defs, scope_imports)
                if kind == "same":
                    key = _key(stem, payload)
                elif kind == "cross":
                    key = _key(payload[0], payload[1])
            else:                                   # 模块别名.函数(...)
                for scope in chain:
                    imp = scope_imports.get(scope, {}).get(fn.value.id)
                    if not imp:
                        continue
                    if imp["kind"] == "module" and imp["is_script"]:
                        key = _key(imp["module"], fn.attr)
                    break
            if key:
                ret = index["func_returns"].get(key)
                if ret:
                    attr_vars[var] = ("factory", ret)
        return {"stem": stem, "cls_qual": cls_qual, "chain": chain, "fn_name": fn_name,
                "owner_key": _key(stem, fn_name) if fn_name and fn_name != MODULE_FN else None,
                "params": params, "attr_vars": attr_vars,
                "tables": collect_dispatch_tables(node_body, index["tables"].get(stem, {}))}

    def emit_call(call_node, from_fn, frame):
        kind, payload, reason = classify(call_node.func, frame, scope_defs, scope_imports, index)
        if kind == "same":
            targets = [(rel, payload)]
        elif kind == "cross":
            targets = [(f"scripts/{payload[0]}.py", payload[1])]
        elif kind == "table":
            targets = [(rel, v) if k == "same" else (f"scripts/{v[0]}.py", v[1])
                       for k, v in payload]
        else:
            targets = None
        if targets is not None:
            for to_file, to_fn in targets:
                edge = {"from_file": rel, "from_fn": from_fn, "to_file": to_file,
                        "to_fn": to_fn, "lineno": call_node.lineno}
                if from_fn == to_fn and to_file == rel:
                    edge["recursive"] = True
                calls.append(edge)
            return
        if kind == "ambiguous":
            ambiguity.append({"from_file": rel, "from_fn": from_fn,
                              "expr": unparse(call_node.func), "lineno": call_node.lineno,
                              "candidates": payload, "reason": reason})
        elif kind == "unresolved":
            unresolved.append({"from_file": rel, "from_fn": from_fn,
                               "expr": unparse(call_node.func),
                               "lineno": call_node.lineno,
                               "category": categorize(reason), "reason": reason})
        elif kind == "external_obj":
            external_obj[0] += 1        # 只计数，不记边、不进两本账
        elif kind == "dynamic":
            # `getattr(...)` / `eval(...)` 这类调用**表达式本身**的目标永远是 builtin，
            # 静态判不出是必然的（不是"漏了"），所以单列计数、不进缺口账本，避免污染信噪比。
            # 其中 getattr 取到的成员若名字是字面量，其**后续重派发**（`v(...)`）仍会照常落边。
            dynamic[0] += 1
        # external（标准库/第三方/builtin）不记

    # 函数与方法：自己的体
    for entry in entries:
        if entry["kind"] == "class":
            continue
        chain = scope_chain(entry["scope_key"], scope_parent)
        fn_calls, fn_names = scope_facts(entry["node"].body)
        params = {}
        for pos, arg in enumerate(list(entry["node"].args.posonlyargs)
                                  + list(entry["node"].args.args)):
            params.setdefault(arg.arg, pos)
        frame = make_frame(entry["qualname"], chain, entry["parent_cls"],
                           entry["node"].body, entry["qualname"], params)
        used = set()
        for scope in chain:
            for name, binding in scope_imports.get(scope, {}).items():
                if name != "*" and name in fn_names:
                    used.add(binding["module"])
        entry["imports_used"] = sorted(used)
        entry["call_sites"] = len(fn_calls)
        entry["segments"] = count_segments(entry["node"].body)
        for call_node in fn_calls:
            emit_call(call_node, entry["qualname"], frame)

    # 模块顶层与类体：伪函数 <module> / 类名
    pseudo = [(tree.body, MODULE_FN, [""], None, None)]
    for entry in entries:
        if entry["kind"] == "class":
            pseudo.append((entry["node"].body, entry["qualname"],
                           scope_chain(entry["scope_key"], scope_parent), entry["qualname"], None))
    for stmts, from_fn, chain, cls_qual, _x in pseudo:
        frame = make_frame(from_fn, chain, cls_qual, stmts, from_fn, {})
        for call_node in scope_facts(stmts)[0]:
            emit_call(call_node, from_fn, frame)

    # 嵌套标记 + 相对导入单独记账
    for entry in entries:
        entry["nested"] = any(other["parent_key"] == entry["scope_key"]
                              and other["kind"] != "class" for other in entries)
    for scope in scope_imports.values():
        for binding in scope.values():
            if binding["kind"] == "relative":
                unresolved.append({"from_file": rel, "from_fn": MODULE_FN,
                                   "expr": binding["display"], "lineno": binding["lineno"],
                                   "category": categorize("相对导入"),
                                   "reason": "相对导入：平铺目录不适用，未参与解析"})

    for entry in entries:
        record["functions"].append({
            "name": entry["name"], "qualname": entry["qualname"], "kind": entry["kind"],
            "lineno": entry["lineno"], "endlineno": entry["endlineno"],
            "span": entry["endlineno"] - entry["lineno"] + 1,
            "public": entry["public"], "imports_used": entry.get("imports_used", []),
            "call_sites": entry.get("call_sites", 0),
            "nested": entry.get("nested", False),
            "segments": entry.get("segments", 0),
        })

    return record, {"imports": imports_table, "calls": calls, "unresolved": unresolved,
                    "ambiguity": ambiguity, "external_obj": external_obj[0],
                    "dynamic": dynamic[0]}, None


def collect_dispatch_tables(stmts, module_tables):
    """`for v in <本文件模块级字面量表>:` → {循环变量名: 表内元素名列表}。"""
    out = {}
    for st in stmts:
        if isinstance(st, DEF_NODES + (ast.ClassDef,)):
            continue
        if (isinstance(st, (ast.For, ast.AsyncFor)) and isinstance(st.target, ast.Name)
                and isinstance(st.iter, ast.Name)):
            elements = module_tables.get(st.iter.id)
            if elements:
                out[st.target.id] = elements
        for body in child_bodies(st):
            out.update(collect_dispatch_tables(body, module_tables))
    return out


def collect_attr_vars(stmts):
    """`v = getattr(<X>, '名字'[, 默认值])` 的局部绑定，供间接调用解析。

    返回 {v: ("self", 属性名)}（X 是 self）或 {v: ("selfattr", 属性名, 成员名)}（X 是 self.<属性>）。
    只认属性名是字面量字符串的情形；其余一律不记（不猜）。
    """
    out = {}
    for assign in walk_assigns_from(stmts):
        call = assign.value
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                and call.func.id == "getattr" and len(call.args) >= 2):
            continue
        literal = call.args[1]
        if not (isinstance(literal, ast.Constant) and isinstance(literal.value, str)):
            continue
        obj = call.args[0]
        for tg in assign.targets:
            if not isinstance(tg, ast.Name):
                continue
            if isinstance(obj, ast.Name) and obj.id == "self":
                out[tg.id] = ("self", literal.value)
            elif (isinstance(obj, ast.Attribute) and isinstance(obj.value, ast.Name)
                    and obj.value.id == "self"):
                out[tg.id] = ("selfattr", obj.attr, literal.value)
    return out


def collect_local_calls(stmts):
    """`v = <名字>(...)` / `v = <模块别名>.<名字>(...)` 的局部绑定（供工厂返回类型解析）。

    只收「右值是一次简单调用」这一种形态；更复杂的右值一律不记（不猜）。
    """
    out = {}
    for assign in walk_assigns_from(stmts):
        call = assign.value
        if not isinstance(call, ast.Call):
            continue
        fn = call.func
        simple = isinstance(fn, ast.Name) or (
            isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name))
        if not simple:
            continue
        for tg in assign.targets:
            if isinstance(tg, ast.Name):
                out.setdefault(tg.id, call)
    return out


def walk_assigns_from(stmts):
    for st in stmts:
        if isinstance(st, DEF_NODES + (ast.ClassDef,)):
            continue
        yield from walk_assigns(st)


# =================================================== 衍生视图①：函数分组
def build_groups(graph):
    """同文件调用图的弱连通分量。节点=该文件的函数与方法；指向本文件类的边改指其 __init__。"""
    files = {}
    for rel, rec in sorted(graph["files"].items()):
        lineno = {f["qualname"]: f["lineno"] for f in rec["functions"]}
        members = [f["qualname"] for f in rec["functions"] if f["kind"] in ("function", "method")]
        member_set = set(members)
        classes = {f["qualname"] for f in rec["functions"] if f["kind"] == "class"}

        def node_of(target):
            """目标若指向本文件的类，落到该类的 __init__（构造即调 __init__）。"""
            if target in classes:
                init = f"{target}.__init__"
                return init if init in member_set else None
            return target if target in member_set else None

        adj = {m: set() for m in members}
        incoming = defaultdict(list)          # 成员 -> [(调用方文件, 调用方函数)]
        for call in graph["calls"]:
            if call["to_file"] == rel:
                incoming[node_of(call["to_fn"]) or call["to_fn"]].append(
                    (call["from_file"], call["from_fn"]))
            if call["from_file"] != rel:
                continue
            src, dst = call["from_fn"], node_of(call["to_fn"])
            if src in member_set and dst in member_set:
                adj[src].add(dst)
                adj[dst].add(src)

        seen, comps = set(), []
        for m in sorted(members, key=lambda q: lineno.get(q, 0)):
            if m in seen:
                continue
            stack, comp = [m], []
            seen.add(m)
            while stack:
                cur = stack.pop()
                comp.append(cur)
                for nxt in adj[cur]:
                    if nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
            comps.append(comp)
        comps.sort(key=lambda c: min(lineno.get(q, 0) for q in c))

        groups = []
        for i, comp in enumerate(comps, 1):
            comp_set = set(comp)
            entry, outside = [], set()
            for m in sorted(comp, key=lambda q: lineno.get(q, 0)):
                outs = [c for c in incoming.get(m, ())
                        if c[0] != rel or c[1] == MODULE_FN or c[1] not in comp_set]
                if outs:
                    entry.append(m)
                    for f, fn in outs:
                        outside.add(f"{Path(f).name}: {fn}")
            groups.append({"id": i, "size": len(comp),
                           "members": sorted(comp, key=lambda q: lineno.get(q, 0)),
                           "entry": entry, "called_from_outside": sorted(outside)})
        files[rel] = {"file": rel, "functions": len(members), "groups": groups}
    return {"files": files,
            "stats": {"files": len(files),
                      "functions": sum(v["functions"] for v in files.values()),
                      "groups": sum(len(v["groups"]) for v in files.values()),
                      "singleton_groups": sum(1 for v in files.values()
                                              for g in v["groups"] if g["size"] == 1)}}


# ================================================= 衍生视图②：模块级依赖
def build_deps(graph):
    deps = {rel: {"calls_out": {}, "called_by": {}} for rel in graph["files"]}
    for rel, imports in graph["imports"].items():
        for module, symbols in imports.items():
            target = f"scripts/{module}.py"
            if target not in deps:
                continue
            deps[rel]["calls_out"][target] = sorted(symbols)
            deps[target]["called_by"][rel] = sorted(symbols)
    for rel in deps:
        deps[rel]["calls_out"] = dict(sorted(deps[rel]["calls_out"].items()))
        deps[rel]["called_by"] = dict(sorted(deps[rel]["called_by"].items()))
    top = [rel for rel in deps if not deps[rel]["called_by"]]
    leaf = [rel for rel in deps if not deps[rel]["calls_out"]]
    return {"deps": deps,
            "stats": {"files": len(deps),
                      "no_incoming": sorted(top),      # 谁都不 import 它：顶层入口候选
                      "no_outgoing": sorted(leaf)}}    # 不从 scripts 拿任何东西：纯叶子


# ======================================================================== 汇总
def build_graph():
    files = sorted(SCRIPTS.glob("*.py"))
    index = build_project_index()
    graph = {"files": {}, "imports": {}, "calls": [], "unresolved": [], "ambiguity": [],
             "stats": {"files": 0, "functions": 0, "methods": 0, "classes": 0,
                       "same_file_edges": 0, "cross_file_edges": 0,
                       "same_file_calls": 0, "cross_file_calls": 0,
                       "unresolved": 0, "ambiguity": 0,
                       "external_object_method_calls": 0, "dynamic_dispatch_calls": 0,
                       "parse_errors": []}}
    for path in files:
        rel = f"scripts/{path.name}"
        record, payload, error = analyze_file(path, rel, index)
        if error:
            graph["stats"]["parse_errors"].append(error)
        graph["files"][rel] = record
        if payload:
            graph["imports"][rel] = payload["imports"]
            graph["calls"].extend(payload["calls"])
            graph["unresolved"].extend(payload["unresolved"])
            graph["ambiguity"].extend(payload["ambiguity"])
            graph["stats"]["external_object_method_calls"] += payload["external_obj"]
            graph["stats"]["dynamic_dispatch_calls"] += payload["dynamic"]

    stats = graph["stats"]
    stats["files"] = len(graph["files"])
    stats["functions"] = sum(1 for f in graph["files"].values()
                             for fn in f["functions"] if fn["kind"] in ("function", "method"))
    stats["methods"] = sum(1 for f in graph["files"].values()
                           for fn in f["functions"] if fn["kind"] == "method")
    stats["classes"] = sum(1 for f in graph["files"].values()
                           for fn in f["functions"] if fn["kind"] == "class")
    same, cross = set(), set()
    for call in graph["calls"]:
        if call["from_file"] == call["to_file"]:
            same.add((call["from_file"], call["from_fn"], call["to_fn"]))
        else:
            cross.add((call["from_file"], call["from_fn"], call["to_file"], call["to_fn"]))
    stats["same_file_edges"] = len(same)
    stats["cross_file_edges"] = len(cross)
    stats["same_file_calls"] = sum(1 for c in graph["calls"] if c["from_file"] == c["to_file"])
    stats["cross_file_calls"] = sum(1 for c in graph["calls"] if c["from_file"] != c["to_file"])
    stats["unresolved"] = len(graph["unresolved"])
    stats["ambiguity"] = len(graph["ambiguity"])
    return graph


def fan_in_map(calls):
    fan = defaultdict(set)
    for call in calls:
        fan[(call["to_file"], call["to_fn"])].add((call["from_file"], call["from_fn"]))
    return fan


def module_pairs(calls):
    pair = defaultdict(set)
    for call in calls:
        if call["from_file"] != call["to_file"]:
            pair[(call["from_file"], call["to_file"])].add((call["from_fn"], call["to_fn"]))
    return pair


# =================================================================== md 报告
def render_md(graph, groups, deps):
    stats = graph["stats"]
    calls = graph["calls"]
    out = []
    add = out.append

    add("# 函数级依赖图 · 人读报告")
    add("")
    add("> 由 `dev/tools/fn_graph.py` 对 `scripts/*.py` 做 AST 静态分析生成，**未修改 scripts/**。")
    add("> 机器可读版：`dev/tools/fn-graph.json`（主事实源）、`dev/tools/fn-groups.json`（函数分组）、")
    add("> `dev/tools/fn-deps.json`（模块依赖）。字段口径见 `fn_graph.py` 模块 docstring。")
    add("")

    add("## 1. 概览")
    add("")
    add("| 指标 | 值 |")
    add("| --- | ---: |")
    add(f"| 文件数 | {stats['files']} |")
    add(f"| 函数数（含方法与嵌套函数） | {stats['functions']} |")
    add(f"| 　其中方法 | {stats['methods']} |")
    add(f"| 类数 | {stats['classes']} |")
    add(f"| 同文件边（去重） | {stats['same_file_edges']} |")
    add(f"| 跨文件边（去重） | {stats['cross_file_edges']} |")
    add(f"| 　同文件调用点 | {stats['same_file_calls']} |")
    add(f"| 　跨文件调用点 | {stats['cross_file_calls']} |")
    add(f"| unresolved（缺口账本） | {stats['unresolved']} |")
    add(f"| ambiguity（真歧义账本） | {stats['ambiguity']} |")
    add(f"| 外部对象方法调用（不计边，见规则 4） | {stats['external_object_method_calls']} |")
    add(f"| 动态派发调用 getattr/eval 等（不计边、不进账本，见规则 7） "
        f"| {stats['dynamic_dispatch_calls']} |")
    errors = stats["parse_errors"]
    add(f"| 解析失败 | {len(errors)} |")
    add("")
    add("> 规则 4 的例外（**类型落地**）：`L = load(...)` 这类「项目函数的返回值类型可由静态确定」")
    add("> 的局部变量，其 `L.<方法>()` 会按该类记成边，并沿裸名字实参把类型传给被调函数的形参")
    add("> （详见 `fn_graph.py` 规则 6 第三条）。本项目里这条规则把渲染器/校验器接回了 `Engine` 门面，")
    add("> 否则整个门面层在函数级图上都不可达。类型判不出的局部变量仍按外部对象处理、不进两本账。")
    add("")
    if errors:
        add("解析失败明细：")
        for err in errors:
            add(f"- `{err['file']}` — {err['error']}")
        add("")
    add(f"`calls` 里的 `from_fn = {MODULE_FN}` 表示**模块顶层**调用（如 "
        "`if __name__ == \"__main__\": main()`），是流程图的入口。")
    add("")

    # ---- 2. 按文件
    add("## 2. 按文件：函数清单")
    add("")
    by_fn = defaultdict(list)
    for call in calls:
        by_fn[(call["from_file"], call["from_fn"])].append(call)
    for rel, record in sorted(graph["files"].items()):
        fns = record["functions"]
        n_fn = sum(1 for f in fns if f["kind"] in ("function", "method"))
        n_cls = sum(1 for f in fns if f["kind"] == "class")
        add(f"### `{rel}` — {record['lines']} 行 / {n_fn} 个函数 / {n_cls} 个类")
        add("")
        if record["doc"]:
            add(f"*{record['doc']}*")
            add("")
        if not fns:
            add("_无函数/类定义_")
            add("")
            continue
        add("| 行号 | 名字 | 可见性 | 调用了 |")
        add("| --- | --- | --- | --- |")
        rows = [("—", MODULE_FN, "—", by_fn.get((rel, MODULE_FN), []))]
        for fn in fns:
            rows.append((f"{fn['lineno']}–{fn['endlineno']}", fn["qualname"],
                         "公开" if fn["public"] else "私有",
                         by_fn.get((rel, fn["qualname"]), [])))
        for lineno, name, vis, fn_calls in rows:
            seen, parts = set(), []
            for call in sorted(fn_calls, key=lambda c: (c["lineno"], c["to_fn"])):
                key = (call["to_file"], call["to_fn"])
                if key in seen:
                    continue
                seen.add(key)
                if call["to_file"] == rel:
                    parts.append(f"`{call['to_fn']}`")
                else:
                    parts.append(f"`{call['to_fn']}` [{Path(call['to_file']).stem}]")
            label = f"`{name}`" if name != MODULE_FN else MODULE_FN
            add(f"| {lineno} | {label} | {vis} | {', '.join(parts) if parts else '—'} |")
        add("")

    # ---- 3. 反向索引
    fan = fan_in_map(calls)
    ranked = sorted(fan.items(), key=lambda kv: (-len(kv[1]), kv[0][1]))
    hot = [(key, callers) for key, callers in ranked if len(callers) >= 3]

    add("## 3. 反向索引（fan-in：谁在调它）")
    add("")
    add(f"### 3.1 fan-in ≥ 3 —— 共享工具层候选（{len(hot)} 个）")
    add("")
    add("| 函数 | fan-in | 被谁调（文件:函数） |")
    add("| --- | ---: | --- |")
    for (to_file, to_fn), callers in hot:
        who = "、".join(f"`{Path(f).stem}:{fn}`" for f, fn in sorted(callers))
        add(f"| `{Path(to_file).stem}.{to_fn}` | {len(callers)} | {who} |")
    add("")
    add("### 3.2 完整 fan-in 表")
    add("")
    add("| 函数 | fan-in | 被谁调（文件:函数） |")
    add("| --- | ---: | --- |")
    for (to_file, to_fn), callers in ranked:
        who = "、".join(f"`{Path(f).stem}:{fn}`" for f, fn in sorted(callers))
        add(f"| `{Path(to_file).stem}.{to_fn}` | {len(callers)} | {who} |")
    add("")

    # ---- 4. 模块依赖矩阵
    pair = module_pairs(calls)
    srcs = sorted({a for a, _ in pair})
    dsts = sorted({b for _, b in pair})
    add("## 4. 模块依赖矩阵（行=调用方，列=被调方，格=去重边数）")
    add("")
    if not pair:
        add("_无跨文件边_")
        add("")
    else:
        add("| 调用方 \\ 被调方 | " + " | ".join(f"`{Path(d).stem}`" for d in dsts) + " | 合计 |")
        add("| --- | " + " | ".join("---:" for _ in dsts) + " | ---: |")
        for src in srcs:
            cells = [str(len(pair[(src, d)])) if pair.get((src, d)) else "·" for d in dsts]
            total = sum(len(pair[(src, d)]) for d in dsts if pair.get((src, d)))
            add(f"| `{Path(src).stem}` | " + " | ".join(cells) + f" | {total} |")
        add("")
        add("边数最多的 5 个模块对：")
        add("")
        for (s, d), edges in sorted(pair.items(), key=lambda kv: -len(kv[1]))[:5]:
            add(f"- `{Path(s).stem}` → `{Path(d).stem}`：{len(edges)} 条")
        add("")

    # ---- 5. 函数体量排行
    add("## 5. 函数体量排行 top 25（决定哪些函数值得原子化拆开）")
    add("")
    add("`行数` = `endlineno - lineno + 1`；`直接调用数` = 该函数体自己的调用点总数（含对外部/标准库）；")
    add("`多个顶层顺序段` 判据：函数体一级语句里，连续的非复合语句算 1 段，")
    add("`if/for/while/try/with/match` 各自切断序列；段数 ≥3 记 `yes`（见模块 docstring）。")
    add("")
    all_fns = [(rel, f) for rel, rec in graph["files"].items()
               for f in rec["functions"] if f["kind"] in ("function", "method")]
    top = sorted(all_fns, key=lambda rf: (-rf[1]["span"], rf[0], rf[1]["lineno"]))[:25]
    add("| 文件:函数 | 行数 | 直接调用数 | 含嵌套函数 | 多个顶层顺序段 |")
    add("| --- | ---: | ---: | --- | --- |")
    for rel, f in top:
        add(f"| `{Path(rel).stem}:{f['qualname']}` | {f['span']} | {f['call_sites']} "
            f"| {'是' if f['nested'] else '否'} "
            f"| {'yes (%d)' % f['segments'] if f['segments'] >= 3 else 'no (%d)' % f['segments']} |")
    add("")

    # ---- 6. 函数分组
    gstats = groups["stats"]
    add("## 6. 函数分组（同文件调用图的弱连通分量）")
    add("")
    add(f"共 {gstats['groups']} 组（其中单成员组 {gstats['singleton_groups']} 个）；"
        f"所有 {gstats['functions']} 个函数都落在某一组里。")
    add("")
    add("| 文件 | 函数数 | 组数 | 最大组 | 最大组成员 |")
    add("| --- | ---: | ---: | ---: | --- |")
    for rel, info in sorted(groups["files"].items()):
        if not info["groups"]:
            add(f"| `{Path(rel).stem}` | 0 | 0 | · | · |")
            continue
        biggest = max(info["groups"], key=lambda g: g["size"])
        members = "、".join(f"`{m}`" for m in biggest["members"][:8])
        if len(biggest["members"]) > 8:
            members += "…"
        add(f"| `{Path(rel).stem}` | {info['functions']} | {len(info['groups'])} "
            f"| {biggest['size']} | {members} |")
    add("")
    add("### 6.1 函数最多的 5 个文件：分组明细")
    add("")
    for rel, info in sorted(groups["files"].items(), key=lambda kv: -kv[1]["functions"])[:5]:
        add(f"**`{rel}`** — {info['functions']} 个函数，{len(info['groups'])} 组")
        add("")
        add("| 组 | 规模 | 成员 | 入口（被组外调用） | 组外调用方 |")
        add("| ---: | ---: | --- | --- | --- |")
        for g in info["groups"]:
            members = "、".join(f"`{m}`" for m in g["members"])
            entry = "、".join(f"`{m}`" for m in g["entry"]) or "·"
            outside = "、".join(f"`{c}`" for c in g["called_from_outside"]) or "·"
            add(f"| {g['id']} | {g['size']} | {members} | {entry} | {outside} |")
        add("")

    # ---- 7. 模块依赖摘要
    dstats = deps["stats"]
    add("## 7. 模块依赖摘要（import 关系）")
    add("")
    add("**入度为 0**（谁都不 import 它 → 顶层入口候选）：")
    add("")
    add("　" + ("、".join(f"`{Path(r).stem}`" for r in dstats["no_incoming"]) or "·"))
    add("")
    add("**出度为 0**（不从 scripts 里拿任何东西 → 纯叶子）：")
    add("")
    add("　" + ("、".join(f"`{Path(r).stem}`" for r in dstats["no_outgoing"]) or "·"))
    add("")
    add("| 文件 | 它依赖谁（出度） | 谁依赖它（入度） |")
    add("| --- | ---: | ---: |")
    for rel in sorted(deps["deps"]):
        info = deps["deps"][rel]
        add(f"| `{Path(rel).stem}` | {len(info['calls_out'])} | {len(info['called_by'])} |")
    add("")

    # ---- 8. ambiguity
    add(f"## 8. ambiguity —— 真歧义账本（{len(graph['ambiguity'])} 条）")
    add("")
    add("候选目标**都真实存在**，但运行期按模式二选一，所以既不算缺口、也不能瞎挑一个当边。")
    add("")
    if graph["ambiguity"]:
        add("| 位置 | 表达式 | 候选目标 | 说明 |")
        add("| --- | --- | --- | --- |")
        for item in sorted(graph["ambiguity"], key=lambda i: (i["from_file"], i["lineno"])):
            cands = "、".join(f"`{c}`" for c in item["candidates"])
            add(f"| `{Path(item['from_file']).stem}:{item['from_fn']}:{item['lineno']}` "
                f"| `{item['expr']}` | {cands} | {item['reason']} |")
    else:
        add("_无_")
    add("")

    # ---- 9. unresolved
    add(f"## 9. unresolved —— 缺口账本（{len(graph['unresolved'])} 条）")
    add("")
    add("这些是「像调用、但静态判不出目标」的点，**一条都没丢**。它是判断")
    add("「有没有项目函数被漏画」的依据；按类目分组如下。")
    add("")
    add("> `self.<属性>.<方法>()` 这一类里，`self.cfg.get()` / `self.notes.append()` /")
    add("> `self.cells.items()` 是 dict/list 的方法，属**假缺口**（属性候选类为空，故不是项目调用）。")
    add(">")
    add(f"> `getattr(...)` / `eval(...)` 这类动态派发**不在本账本里**（{stats['dynamic_dispatch_calls']} 处）——")
    add("> 它们的调用表达式目标必然是 builtin，判不出是机制使然，不是缺口；见「概览」那一行。")
    add("")
    grouped = defaultdict(list)
    for item in graph["unresolved"]:
        grouped[item["category"]].append(item)
    for category, items in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        add(f"### {category}（{len(items)} 条）")
        add("")
        add("| 位置 | 表达式 | 说明 |")
        add("| --- | --- | --- |")
        for item in sorted(items, key=lambda i: (i["from_file"], i["lineno"])):
            add(f"| `{Path(item['from_file']).stem}:{item['from_fn']}:{item['lineno']}` "
                f"| `{item['expr']}` | {item['reason']} |")
        add("")
    return "\n".join(out) + "\n"


def review_reasons(stats):
    """返回「需要人看」的理由列表；空列表表示可以退 0。口径见模块 docstring。"""
    reasons = []
    if stats["parse_errors"]:
        reasons.append("解析失败 %d 个文件" % len(stats["parse_errors"]))
    if stats["unresolved"] > REVIEW_UNRESOLVED:
        reasons.append("unresolved %d > 阈值 %d（出现未复核的新缺口）"
                       % (stats["unresolved"], REVIEW_UNRESOLVED))
    if stats["ambiguity"] > REVIEW_AMBIGUITY:
        reasons.append("ambiguity %d > 阈值 %d（出现未复核的新歧义）"
                       % (stats["ambiguity"], REVIEW_AMBIGUITY))
    return reasons


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="fn_graph.py",
        description="对 scripts/*.py 做 AST 静态分析，产出函数级依赖图与三份衍生视图"
                    "（只写 dev/tools/，只读 scripts/，不改它）。",
        epilog="退出码：0 = 分析完成并写出产物；1 = 跑完了但有需人工复核的缺口/歧义"
               "（解析失败，或账本超过 fn_graph.py 里 REVIEW_* 阈值）；"
               "2 = 仪器故障（输入读不了/产物写不出去/内部异常，给一句中文 ✗ 不打 traceback）。")
    ap.parse_args(argv)

    # ⓪ 输入先检查：目录不存在 / 里面没有 .py —— 这是"输入读不了"，属仪器故障（2），
    #    不能让它变成"分析完成，0 个文件"，那会把故障伪装成正常结果。
    if not SCRIPTS.is_dir():
        print(f"✗ 输入目录不存在：{SCRIPTS}（仪器故障）", file=sys.stderr)
        return 2
    if not any(SCRIPTS.glob("*.py")):
        print(f"✗ 输入目录里没有 .py 文件：{SCRIPTS}（仪器故障）", file=sys.stderr)
        return 2

    # ① 分析：输入读不了 / 内部异常 → 仪器故障（2），不把 traceback 甩给用户
    try:
        graph = build_graph()
        groups = build_groups(graph)
        deps = build_deps(graph)
    except Exception as exc:
        print(f"✗ 分析失败（仪器故障，非图里有问题）：{type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2

    # ② 写产物：写不出去同样是仪器故障（2）
    # **`newline='\n'` 是必须的**（2026-09-19，D-131）：不传时 Windows 会把 `\n` 翻成 `\r\n`，
    # 于是这三份 JSON 与 `fn-graph.md` 是 CRLF，而它旁边的**一手文件**是 LF——同一棵树两种字节，
    # 面③ 那条"全仓文本文件一个 CR 都没有"当场红。正是 D-116 在产物侧修过的同一个形态
    # （"写的那一侧没人管"），这次轮到生成器自己。
    try:
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        for path, payload in ((OUT_JSON, graph), (OUT_GROUPS, groups), (OUT_DEPS, deps)):
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8", newline="\n")
        OUT_MD.write_text(render_md(graph, groups, deps), encoding="utf-8", newline="\n")
    except OSError as exc:
        print(f"✗ 产物写不出去（仪器故障）：{exc}", file=sys.stderr)
        return 2

    report = {"stats": graph["stats"],
              "groups": groups["stats"],
              "deps": {"no_incoming": deps["stats"]["no_incoming"],
                       "no_outgoing": deps["stats"]["no_outgoing"]}}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    for path in (OUT_JSON, OUT_GROUPS, OUT_DEPS, OUT_MD):
        print(f"wrote {path.relative_to(ROOT)}  ({path.stat().st_size} bytes)")

    # ③ 跑完了但有需要人看的缺口 → 1（这与"仪器故障"是两回事，故分开）
    reasons = review_reasons(graph["stats"])
    if reasons:
        print("⚠ 需人工复核（退出码 1）：" + "；".join(reasons), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
