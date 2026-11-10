# 08　Edax：请一位职业棋手当外援

> 把局面写成纸条递出去，读回它建议的第一步；逐行读 `ai/othello_ext/`

**编号 08　|　难度：深入　|　建议阅读：26 分钟　|　前置：第 00 篇（统一接口与工厂）、第 03 篇（合法步）**

[← 返回文档导航](README.md)　|　上一篇：[07 ABC 人工蜂群](07_ABC_人工蜂群.md)　|　下一篇：[09 规则层与位板加速](09_规则层与位板加速架构.md)

> **30 秒速览：** Edax 不是本项目写的算法，而是**外部黑白棋专用强引擎**。Python 侧只做协议适配：每步把棋盘写成 OBF 临时文件、启动一次子进程、从输出里解析主变例（PV）首着。这一篇把 `ai/othello_ext/` 四个小文件逐段读完，包括可用性检测、环境变量、OBF 换算、子进程调用、输出解析、失败降级，以及为什么它对其它棋种「零影响」。

> **源码快照说明：** 代码片段基于 **2026-11-10** 源码，均为**节选**；行号仅供对照，**函数名才是稳定定位**。

## 这一篇的目录

1. [1. 这一篇讲什么](#1-这一篇讲什么)
2. [2. 先用直觉理解](#2-先用直觉理解)
3. [3. 跟着代码走一遍](#3-跟着代码走一遍)
4. [4. 名词速查](#4-名词速查)
5. [5. 源码逐段精读](#5-源码逐段精读)
6. [6. 代码模块地图](#6-代码模块地图)
7. [7. 动手试一试](#7-动手试一试)
8. [8. 常见疑问与已知限制](#8-常见疑问与已知限制)

---

## 1. 这一篇讲什么

一句话：Edax 是「外援」——Python 侧只负责把局面翻译给它、把答案翻译回来。

读完你应该能回答：

- 为什么不把引擎改造成一个 Python 类，而要用子进程？
- OBF 是什么格式，PV 又是什么，怎么换算成 `(row, col)`？
- 引擎缺失 / 超时 / 输出异常时，代码怎么保证对局不中断？
- 为什么它对其它棋种和其它算法「零影响」？

**这一篇会带你读的文件：** `ai/othello_ext/__init__.py`（配置与可用性）、`obf.py`（局面与坐标换算）、`protocol.py`（子进程与输出解析）、`edax_ai.py`（AI 适配与降级）、`ai/factory.py`（延迟导入）、`vendor/edax/`（外部二进制与权重）。

## 2. 先用直觉理解

想象你正在下棋，身边坐着一位只懂黑白棋的特级大师。你不会请他重写你的整个比赛流程，只会每次把当前棋局抄在一张纸条上递过去，等他写回一句「我建议下 D3」，再把 D3 翻译成棋盘坐标。

这里「纸条」就是 OBF 文件，「特级大师」是 `wEdax-x86-64.exe`，「递纸条」是 `subprocess.run()` 启动一次进程，「D3」是引擎输出里 PV（主要变例）的第一个着法。

> **初学者提示：** 这种「无状态、每步一次调用」的方式，比让引擎长驻并用 NBoard / GTP 协议通信简单得多：没有进程内状态、没有死锁，超时直接结束进程即可。

## 3. 跟着代码走一遍

> **这一节是整篇最关键的部分。** 假设黑白棋轮到 AI，引擎文件齐备、搜索深度 18、超时 8 秒。下面按真实执行顺序走 8 步。

### 先收好这张「函数名对照表」

| 函数名（英文） | 中文作用（它到底干了什么） | 输入 → 输出 |
| --- | --- | --- |
| `EdaxAI.select_move()` | 适配器入口：确认棋种 → 调引擎 → 降级 → 返回坐标 | 棋盘 + 回调 → `(row, col)` |
| `is_available()` | 只检查 exe 与 `eval.dat` 两个文件是否存在 | 无 → `True/False` |
| `engine_dir()` / `exe_path()` / `eval_path()` | 拼出引擎目录、可执行文件路径、权重文件路径 | 环境变量 → `Path` 对象 |
| `level()` / `time_limit()` | 读搜索深度与硬超时（带范围钳制与异常兜底） | 环境变量 → 整数 / 浮点数 |
| `board_to_obf()` | 把二维棋盘写成 64 字符 OBF 文本 + 轮次标记 | 棋盘 → 字符串 |
| `notation_to_rc()` | 把 `D3` 这类代数坐标换成项目用的 `(row, col)` | 字符串 → 二元组 |
| `solve()` | 写临时 OBF、拼命令、跑子进程、解析结果、清理文件 | 棋盘 + 深度 + 超时 → `((row,col), score)` 或 `None` |
| `parse_solve_output()` | 从引擎输出表格里找 PV 首着与评估分 | 标准输出文本 → `(坐标, 分数)` 或 `None` |
| `subprocess.run()` | 启动外部进程并等待结果（带 `timeout`） | 命令列表 → 输出对象 |
| `sort_moves_by_heuristic()` | 降级时按棋理分挑一个最好的合法步 | 棋盘 + 合法步 → 排序后的列表 |
| `create_ai()`（factory） | 按 `"edax"` 延迟导入适配器 | 算法名 → `EdaxAI` 实例 |

### 第 1 步：入口先确认「是不是黑白棋」

**在干什么：** 保证外部引擎永远不会在别的棋种里被调用。

**函数具体做什么：** `EdaxAI.select_move()` 第一句 `if type(board).__name__ != "OthelloBoard":` 就从 `ai.alpha_beta` **延迟导入** `AlphaBetaAI`，用同样的 `self.player` / `self.config` 造一个实例并把这次选步**整个委托**给它（`return AlphaBetaAI(...).select_move(board, on_progress)`）。

**输入 → 输出：** 五子棋 / 围棋 / 象棋棋盘 → 由 Alpha-Beta 算出的坐标。

**为什么：** Edax 只认 8×8 黑白棋局面，传别的一定出错；委托现有算法比报错更稳妥。

### 第 2 步：重置思考状态，取合法步

**在干什么：** 准备界面播报，并处理「无合法步」。

**函数具体做什么：** `self._begin_think()` 重置 `ThinkState`；`legal = board.get_legal_moves()`；为空就写 `think.note = "无合法步，停一手"`、`finish()`、`_emit()` 后返回 `None`（与其它 AI 完全一致的边界约定）。

**输入 → 输出：** 棋盘 → `legal = [(2,3), (2,4), ...]`，或 `None`。

**为什么：** 黑白棋中盘常出现某方无合法步，对局层会自动跳回合。

### 第 3 步：只做「文件存在性」检查

**在干什么：** 判断引擎到底装没装。

**函数具体做什么：** `available = is_available()`，它在 `__init__.py` 第 38 行，实现只有一句 `return exe_path().is_file() and eval_path().is_file()`，外加 `try/except OSError` 返回 False。模块 docstring 特意强调「不装包、不启动进程、不读权重内容」。`exe_path()` 拼的是 `engine_dir() / name`，`eval_path()` 拼的是 `engine_dir() / "data" / "eval.dat"`；默认目录 `_DEFAULT_DIR = <项目根>/vendor/edax`，默认文件名 `_DEFAULT_EXE = "wEdax-x86-64.exe"`。

**输入 → 输出：** 文件系统 → `True/False`。

**为什么：** 没装引擎时该功能应当**完全隐身**（菜单里不出现、其它算法不受影响），而不是启动时报错。

### 第 4 步：把二维棋盘翻译成 OBF 文本

**在干什么：** 把项目内部的棋盘数据结构写成引擎能读的字符串。

**函数具体做什么：** `board_to_obf()` 双重循环遍历 `board.board`，黑子（`BLACK`）写 `X`、白子（`WHITE`）写 `O`、空格写 `-`，得到 64 个字符（行优先）；轮次标记是 `" X;"`（黑先）或 `" O;"`（白先），用空格拼接后返回。

**输入 → 输出：** 8×8 棋盘 → 例如 `"---------------------------OX------XO--------------------------- X;"`（初始局面附近）。

**为什么：** 这是两套系统之间唯一的「共同语言」；转换函数集中放在 `obf.py`，避免各处重复拼字符串。

### 第 5 步：写临时文件，拼命令，启动一次子进程

**在干什么：** 真正把「纸条」递给大师。

**函数具体做什么：** `solve()` 里 `tempfile.mkstemp(prefix="acbp_", suffix=".obf", dir=str(directory))` 在引擎目录下建临时文件，写入 `board_to_obf(board) + "\n"`。然后拼命令：

```
[exe, "-solve", path, "-l", str(depth), "-eval-file", str(eval_path()), "-book-usage", "off"]
```

`subprocess.run(cmd, cwd=directory, stdin=DEVNULL, stdout=PIPE, stderr=PIPE, timeout=timeout, check=False)` 等待结果。`-l` 是搜索深度（来自 `level()`，默认 18），`-book-usage off` 关掉开局库保证每次独立求解。

**输入 → 输出：** 棋盘 + 深度 18 + 超时 8.0 秒 → 引擎的标准输出文本。

**为什么：** 无状态的一次性调用，没有长驻进程、没有协议握手、没有死锁；超时由 `subprocess` 强制终止。

### 第 6 步：从输出里解析 PV 首着

**在干什么：** 把引擎那堆表格文字翻译成项目能用的坐标。

**函数具体做什么：** `parse_solve_output()` 逐行扫描：跳过没有 `|` 的行和以 `#` 开头的注释；取 `|` 右边的部分 `rhs`；用 `MOVE_RE = re.compile(r"\b([A-Ha-h])([1-8])\b")` 找第一个形如 `D3` 的着法；再用 `_SCORE_RE = re.compile(r"[+-]\d+")` 取评估分。最后 `notation_to_rc(m.group(0))` 换算：`int(行号) - 1` 得 row，`ord(大写列字母) - ord("A")` 得 col，所以 `D3 → (2, 3)`。

**输入 → 输出：** 一行 `1|18@73%  +01  ...  D3 f5 F4 ...` → `((2,3), 1)`。

**为什么：** 引擎输出是人类看的表格，不是结构化 API；正则解析是协议适配层最核心也最脆弱的一块，所以解析失败一律返回 `None` 交给上层降级。

### 第 7 步：无论成败都删掉临时文件

**在干什么：** 清理现场，不留垃圾。

**函数具体做什么：** `solve()` 用 `try/except/finally` 包住整个流程：`except (subprocess.TimeoutExpired, OSError, ValueError): return None`（超时、文件错误、解析出的分数不是整数都安全返回 `None`）；`finally:` 里 `os.remove(path)`，并用 `try/except OSError: pass` 兜住「文件已经不在」的情况。

**输入 → 输出：** 临时 `.obf` 文件 → 被删除。

**为什么：** 每步都建一个文件，若不清理，`vendor/edax/` 下会堆满 `acbp_*.obf`。

### 第 8 步：结果合法就用，否则降级，并写回思考状态

**在干什么：** 把最终决定交给对局层。

**函数具体做什么：** `edax_ai.py` 里 `if result is not None and result[0] in legal:` 才采用引擎结果（`move, score = result[0], float(result[1])`、`note = "Edax 求解完成"`）；否则 `move = sort_moves_by_heuristic(board, legal, self.player)[0]`，并按 `available` 决定 `note` 是 `"Edax 未安装"` 还是 `"Edax 超时 / 无解，已降级"`。随后写 `think.phase = "Edax 引擎求解"`、`done = total = 1`、`best_move / best_value / top_moves / elapsed`，`finish()` + `_emit()` + `return move`。

**输入 → 输出：** 引擎结果或降级结果 → 一个合法坐标。

**为什么：** 「外部引擎不可用也不能让对局中断」是这一层最重要的设计约束；降级用的是项目自带的启发式排序，不依赖任何外部文件。

> **一句话记住整条链：** 确认棋种 → `is_available()` → `board_to_obf()` → `subprocess.run(-solve)` → `parse_solve_output()` → `finally` 删文件 → 合法则用、否则降级 → 返回坐标。
>
> 上面每一步的**真实源码片段与逐行解释**在第 5 节；图 1 就是这条链。

## 4. 名词速查

| 名词 | 大白话 | 在项目里的取值 / 位置 |
| --- | --- | --- |
| Edax 4.6 | 开源黑白棋强引擎（外部程序） | `vendor/edax/` |
| OBF | 描述局面的纯文本：64 字符 + 轮次标记 | `obf.py · board_to_obf()` |
| PV | 引擎认为双方最优的一条主线，首着即建议 | `protocol.py · parse_solve_output()` |
| `MOVE_RE` | 匹配 `D3` / `f5` 这类代数坐标的正则 | `obf.py` 第 9 行 |
| `-l 18` | 传给引擎的搜索深度 | `level()`，默认 18 |
| `eval.dat` | 引擎的模式评估权重文件 | `eval_path()` |
| 无状态调用 | 每步启动一次进程，用完即结束 | `protocol.py · solve()` |
| 零影响设计 | 引擎不在时功能自动隐藏 | `is_available()` + 菜单过滤 |
| 降级 | 失败时退回启发式最佳合法步 | `sort_moves_by_heuristic()[0]` |

## 5. 源码逐段精读

> **进阶提醒：** 四个文件加起来不到 200 行，建议按 `__init__.py → obf.py → protocol.py → edax_ai.py` 一次读完。

![图 1　Edax 一步调用链：上排中文动作、下排代码定位](architecture/08_edax_flow.png)

**图 1　代码调用链**（可编辑 Visio 源：[08_edax_flow.vsdx](architecture/08_edax_flow.vsdx)）

![图 2　Edax 集成代码架构：可用性 / 配置 / 协议 / 降级](architecture/08_edax_arch.png)

**图 2　代码模块架构**（可编辑 Visio 源：[08_edax_arch.vsdx](architecture/08_edax_arch.vsdx)）

**怎么读这两张图：** 每个节点**上排是中文动作说明**，**下排才是文件与函数定位**。例如「把二维棋盘写成 OBF 文本」下面写的是 `obf.py · board_to_obf()`。先读上排理解流程，再看下排找源码。PNG 与 VSDX 文字完全一致。

### 5.1 可用性与环境变量

**定位：`ai/othello_ext/__init__.py` 第 19—57 行（节选）**

```python
_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DIR = _ROOT / "vendor" / "edax"
_DEFAULT_EXE = "wEdax-x86-64.exe"

def engine_dir() -> Path:
    raw = os.environ.get("ACBP_EDAX_DIR", "").strip()
    return Path(raw) if raw else _DEFAULT_DIR

def is_available() -> bool:
    """只做文件存在性检查：不装包、不启动进程、不读权重内容。"""
    try:
        return exe_path().is_file() and eval_path().is_file()
    except OSError:
        return False

def level() -> int:
    try:
        return max(1, min(60, int(os.environ.get("ACBP_EDAX_LEVEL", "18"))))
    except ValueError:
        return 18

def time_limit() -> float:
    try:
        return max(0.5, min(60.0, float(os.environ.get("ACBP_EDAX_TIME", "8.0"))))
    except ValueError:
        return 8.0
```

**逐行看懂：** 四个环境变量全部**可选**，`os.environ.get(..., 默认值)` 保证没设也能跑；`level()` 钳制在 1~60、`time_limit()` 钳制在 0.5~60.0，且 `except ValueError` 在环境变量写错时静默回退默认值。`parents[2]` 是从 `ai/othello_ext/__init__.py` 往上两级回到项目根。

### 5.2 局面与坐标换算

**定位：`obf.py` 第 9—32 行（全文）**

```python
MOVE_RE = re.compile(r"\b([A-Ha-h])([1-8])\b")

def board_to_obf(board) -> str:
    cells = []
    for row in board.board:
        for value in row:
            if value == BLACK:
                cells.append("X")
            elif value == WHITE:
                cells.append("O")
            else:
                cells.append("-")
    turn = "X" if board.current_player == BLACK else "O"
    return "".join(cells) + " " + turn + ";"

def notation_to_rc(text):
    m = MOVE_RE.search(text)
    if m is None:
        return None
    return int(m.group(2)) - 1, ord(m.group(1).upper()) - ord("A")
```

**逐行看懂：** `board.board` 是第 09 篇说的**权威二维列表**；`turn` 用 `" X;"` / `" O;"` 标记轮次；`notation_to_rc()` 里 `-1` 是因为项目行号从 0 开始、引擎从 1 开始，列字母减 `ord("A")` 同理。`MOVE_RE` 用 `\b` 单词边界，避免把输出里其它数字误当着法。

### 5.3 子进程调用与输出解析

**定位：`protocol.py` 第 20—62 行（节选）**

```python
_SCORE_RE = re.compile(r"[+-]\d+")

def parse_solve_output(stdout: str):
    for line in stdout.splitlines():
        if "|" not in line or line.lstrip().startswith("#"):
            continue
        rhs = line.split("|", 1)[1]
        m = MOVE_RE.search(rhs)
        if m is None:
            continue
        s = _SCORE_RE.search(rhs)
        return notation_to_rc(m.group(0)), (int(s.group(0)) if s else 0)
    return None

def solve(board, depth, timeout):
    if not is_available():
        return None
    directory = engine_dir()
    fd, path = tempfile.mkstemp(prefix="acbp_", suffix=".obf", dir=str(directory))
    try:
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(board_to_obf(board) + "\n")
        cmd = [str(exe_path()), "-solve", path, "-l", str(depth),
               "-eval-file", str(eval_path()), "-book-usage", "off"]
        proc = subprocess.run(
            cmd, cwd=str(directory), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, check=False)
        return parse_solve_output(proc.stdout.decode("utf-8", "replace"))
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
```

**逐行看懂：**

1. `line.split("|", 1)[1]` 只切第一个竖线，取右边那一段（引擎输出形如 `1|18@73% +01 ... D3 f5 ...`）。
2. `decode("utf-8", "replace")` 对引擎可能输出的非 UTF-8 字节用替换字符兜底，不让解码异常冒泡。
3. `stdin=DEVNULL` 防止引擎等待输入卡住；`check=False` 表示非零退出码不抛异常，交由后续解析返回 `None`。
4. `finally` 必删临时文件；`except OSError: pass` 容忍「文件已被删」。

### 5.4 适配层与降级

**定位：`edax_ai.py` 第 26—60 行（节选）**

```python
def select_move(self, board, on_progress=None):
    if type(board).__name__ != "OthelloBoard":
        from ai.alpha_beta import AlphaBetaAI
        return AlphaBetaAI(self.player, self.config).select_move(board, on_progress)

    self._begin_think()
    legal = board.get_legal_moves()
    if not legal:
        ...
        return None

    available = is_available()
    t0 = time.perf_counter()
    result = solve(board, level(), time_limit()) if available else None
    score = 0.0
    if result is not None and result[0] in legal:
        move, score = result[0], float(result[1])
        note = "Edax 求解完成"
    else:
        move = sort_moves_by_heuristic(board, legal, self.player)[0]
        note = "Edax 未安装" if not available else "Edax 超时 / 无解，已降级"

    self.think.phase = "Edax 引擎求解"
    self.think.done = self.think.total = 1
    self.think.best_move = move
    self.think.best_value = score
    self.think.top_moves = [(move, 1, score)]
    self.think.note = note
    self.think.elapsed = time.perf_counter() - t0
    self.think.finish()
    self._emit(on_progress)
    return move
```

**逐行看懂：** `result[0] in legal` 是第二道防线——即使引擎给了一个坐标，也要确认它在当前合法步里。`done = total = 1` 表示这一步只有「一次求解」，进度条直接走满。`elapsed` 用 `time.perf_counter()` 手动计时（没有用 `MoveTimer`），因为这里只是一次外部调用。

### 5.5 工厂里的延迟导入

**定位：`ai/factory.py` 第 45—48 行（节选）**

```python
if algo_name == "edax":
    # 延迟导入：未选该算法时不加载适配层，也不检查外部引擎文件
    from .othello_ext.edax_ai import EdaxAI
    return EdaxAI(player, config)
```

**逐行看懂：** `edax` **不在** `_REGISTRY` 字典里，而是单独分支 + 函数内 import。这样没选它时，程序连 `ai/othello_ext/` 都不加载，外部引擎缺文件完全不影响其它算法启动——这就是「零影响」在代码里的落点（第 00 篇 5.4 也提到过）。

### 5.6 本节小结：把函数名串起来

```
ai/factory.py · create_ai("edax")        （延迟导入）
  └─ ai/othello_ext/edax_ai.py · EdaxAI.select_move()
     ├─ 非 OthelloBoard → ai/alpha_beta.py · AlphaBetaAI.select_move()
     ├─ __init__.py · is_available() → exe_path() / eval_path()
     ├─ protocol.py · solve(board, level(), time_limit())
     │    ├─ obf.py · board_to_obf() → 临时 .obf
     │    ├─ subprocess.run(-solve -l -eval-file -book-usage off)
     │    ├─ parse_solve_output() → MOVE_RE / _SCORE_RE / notation_to_rc()
     │    └─ finally: os.remove(path)
     ├─ 合法则采用；否则 sort_moves_by_heuristic()[0] 降级
     └─ ThinkState → _emit() → return (row, col)
```

| 变量 / 常量 | 定义处 | 默认值 |
| --- | --- | --- |
| `ACBP_EDAX_DIR` | `__init__.py` | `<项目根>/vendor/edax` |
| `ACBP_EDAX_EXE` | `__init__.py` | `wEdax-x86-64.exe` |
| `ACBP_EDAX_LEVEL` | `level()` | 18（范围 1~60） |
| `ACBP_EDAX_TIME` | `time_limit()` | 8.0 秒（范围 0.5~60） |
| `MOVE_RE` | `obf.py` 第 9 行 | 匹配 `A~H` + `1~8` |

## 6. 代码模块地图

| 文件 | 类 / 函数 | 作用 | 被谁调用 | 建议读码顺序 |
| --- | --- | --- | --- | --- |
| `ai/factory.py` | `create_ai()` 的 `edax` 分支 | 延迟导入适配器 | `build_players()` / `_worker()` | ① |
| `ai/othello_ext/__init__.py` | `is_available()` / `engine_dir()` / `level()` / `time_limit()` | 可用性与环境变量 | `solve()`、`edax_ai.py`、菜单 | ② |
| `ai/othello_ext/edax_ai.py` | `EdaxAI.select_move()` | 入口、棋种隔离、结果校验、降级 | `step_ai()` | ③ |
| `ai/othello_ext/obf.py` | `board_to_obf()` / `notation_to_rc()` | 局面与坐标双向换算 | `solve()` / `parse_solve_output()` | ④ |
| `ai/othello_ext/protocol.py` | `solve()` / `parse_solve_output()` | 子进程调用与 PV 解析 | `select_move()` | ⑤ |
| `ai/candidates.py` | `sort_moves_by_heuristic()` | 降级时挑启发式最佳步 | `select_move()` | ⑥ |
| `ai/alpha_beta.py` | `AlphaBetaAI.select_move()` | 非黑白棋时的委托对象 | `select_move()` | ⑦ |
| `ai/think_state.py` | `ThinkState` | 播报「Edax 求解完成 / 已降级」 | `_emit()` | ⑧ |
| `vendor/edax/` | exe + `data/eval.dat` | 外部引擎与权重 | `subprocess.run()` | ⑨ |

**推荐读码路线：** ③ 入口先看全貌 → ② 看可用性怎么判断 → ④ 看两种格式怎么换算 → ⑤ 看子进程与正则解析（最容易出错的一段）→ ① 看为什么它不影响其它算法。

## 7. 动手试一试

```bash
# 引擎到位后，直接让 Edax 对本项目 Alpha-Beta（黑白棋）
python start.py --game othello --mode ai_vs_ai --p1-ai edax --p2-ai alphabeta --ab-depth 3

# 降低引擎等级，观察棋力与耗时变化（Windows CMD 示例）
set ACBP_EDAX_LEVEL=8
python start.py --game othello --mode ai_vs_ai --p1-ai edax --p2-ai alphabeta --ab-depth 3

# 在五子棋里强选 edax：会自动退回 Alpha-Beta，外部引擎不会被调用
python start.py --game gomoku --mode ai_vs_ai --p1-ai edax --p2-ai random
```

| 环境变量 | 默认值 | 含义 |
| --- | --- | --- |
| `ACBP_EDAX_DIR` | `vendor/edax` | 引擎目录（exe + `data/eval.dat`） |
| `ACBP_EDAX_EXE` | `wEdax-x86-64.exe` | 可执行文件名 |
| `ACBP_EDAX_LEVEL` | 18 | 搜索深度，范围 1~60 |
| `ACBP_EDAX_TIME` | 8.0 | 子进程硬超时秒数，范围 0.5~60 |

- 若菜单里看不到 Edax，先检查 `vendor/edax/` 下是否有 exe 与 `data/eval.dat`。
- 实战记录：Edax 对深度 3 的 Alpha-Beta 各执黑白 10 局，10 胜 0 负、0 非法步。
- 调小 `ACBP_EDAX_LEVEL` 能明显缩短每步等待，适合先跑通流程。

> **初学者提示：** 这些是**环境变量**，不是命令行参数，也不在 `settings.py` 里。Git Bash 里要用 `export ACBP_EDAX_LEVEL=8` 而不是 `set`。

## 8. 常见疑问与已知限制

**问：为什么不用长驻进程通信，每步都启动一次不慢吗？**

答：确实有 50~200 ms 的权重加载开销，但换来「无状态、无死锁、超时直接 kill」的简单模型。对本项目这种一步一调用的使用方式，可靠性更值钱。

**问：其它棋种能用 Edax 吗？**

答：不能。`select_move()` 开头检测 `type(board).__name__ != "OthelloBoard"`，直接委托 Alpha-Beta，保证外部引擎一次都不会被调用。

**问：引擎文件没放会报错吗？**

答：不会。`is_available()` 返回 `False`，菜单里该选项隐藏；即便被命令行强选，`solve()` 也会返回 `None` 并降级到启发式最佳步。

**问：引擎给了一个坐标，代码还会检查吗？**

答：会。`result[0] in legal` 是第二道防线，防止引擎输出与当前局面不一致时走出非法步。

- 已知限制：release 是 Windows 64 位 exe，其它平台需自行编译。
- 已知限制：每步启动外部进程有 50~200 ms 权重加载开销。
- 已知限制：仅支持黑白棋，且依赖外部权重文件 `eval.dat`。
- 已知限制：`parse_solve_output()` 依赖引擎输出格式的正则匹配，引擎版本升级导致输出格式变化时可能需要同步修改。
- 文档定位：代码片段是节选，完整实现以 `ai/othello_ext/` 四个文件为准。

---

*ACBP 棋类综合对战平台 · 算法学习文档 · 第 08 篇 / 共 10 篇 · 代码片段基于 2026-11-10 源码*
