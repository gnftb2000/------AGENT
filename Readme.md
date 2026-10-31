# 工业级 AGENT

一个跑在终端里的编程助手（coding agent）：你用自然语言描述任务，它读写文件、执行命令、运行验证，遇到报错自己修，直到任务完成。

底层基于 [pydantic-ai](https://ai.pydantic.dev/) v2 + DeepSeek。除了「能干活」，它还补齐了工业级 CLI 该有的工程能力：细粒度权限审批、auto 模式 LLM 安全审查、读后写保护、外部改动提醒、会话持久化与恢复、API 自动重试。

> 程序内部代号 `my-coding-agent`：启动横幅显示这个名字，会话数据也存在 `~/.my-coding-agent/` 下。

## 目录

- [功能特性](#功能特性)
- [环境要求](#环境要求)
- [安装](#安装)
- [快速开始](#快速开始)
- [使用方式](#使用方式)
  - [输入区与快捷键](#输入区与快捷键)
  - [权限模式](#权限模式)
  - [斜杠命令](#斜杠命令)
  - [项目指令 AGENTS.md](#项目指令-agentsmd)
- [内置工具](#内置工具)
- [安全机制](#安全机制)
- [上下文与会话](#上下文与会话)
- [稳定性设计](#稳定性设计)
- [终端界面](#终端界面)
- [项目结构](#项目结构)
- [扩展开发](#扩展开发)
- [常见问题](#常见问题)
- [已知限制](#已知限制)

## 功能特性

| 能力 | 说明 |
| --- | --- |
| 自然语言编程 | 理解需求 → 读写文件 → 执行命令验证 → 出错自动修复，循环到任务完成 |
| 4 个内置工具 | `read_file` / `edit_file` / `write_file` / `run_command` |
| 4 档权限模式 | `default` / `acceptEdits` / `auto` / `bypass`，`Shift+Tab` 随时切换 |
| 细粒度审批 | 每次高风险操作弹窗：允许 / 本会话不再询问 / 拒绝，拒绝理由会回填给模型 |
| auto 智能审批 | 本该弹窗的调用交给旁路 LLM 审查：安全就放行、危险就拦截（出错一律按拦截处理） |
| 读后写保护 | 没读过的文件不许改；读完之后被外部改过也不许改，防止覆盖别人的改动 |
| 外部改动提醒 | 读过的文件被外部修改时，自动注入 `<system-reminder>` 提醒模型重读 |
| 会话持久化 | 每轮对话追加写入 jsonl，`/resume` 可恢复历史会话与 token 统计 |
| 自动重试 | HTTP 5xx / 网络故障时指数退避重试 3 次，不打断你的任务 |
| 过程可观测 | thinking、工具调用、工具返回、红绿 diff 实时打印；`/api-detail` 查看每次请求的明细 |
| 常驻输入区 | 输出滚动时输入框固定在底部；请求进行中随时 `Esc` 打断 |
| 动态上下文 | 每轮自动注入工作目录、操作系统、日期，以及项目级 `AGENTS.md` |

## 环境要求

- **Python ≥ 3.11**（代码用到 `X | Y` 类型语法；`pydantic-ai` 新版也要求 3.11+）
- **DeepSeek API Key**：在 <https://platform.deepseek.com/> 申请
- 终端需支持 ANSI 颜色（macOS Terminal / iTerm2 / Windows Terminal / VS Code 终端均可）

## 安装

```bash
# 1. 进入项目目录
cd 工业级AGENT

# 2. 创建并激活虚拟环境
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. 安装依赖
pip install "pydantic-ai>=2.0" openai prompt-toolkit rich questionary
```

> `pydantic-ai` 必须是 **v2 及以上**：本项目用到了 v2 才有的 `pydantic_ai.capabilities.Hooks`。

## 快速开始

```bash
export API_KEY="sk-你的deepseek-api-key"
python main.py
```

Windows PowerShell：

```powershell
$env:API_KEY="sk-你的deepseek-api-key"
python main.py
```

> 请在**项目根目录**下运行 `main.py`：程序使用相对导入，且会话按启动时的工作目录分目录存储。

看到启动横幅后，直接在 `❯` 输入框里描述任务即可：

```
╭──────────────────────────────────────────────╮
│ ✻ 欢迎使用 my-coding-agent                     │
│                                              │
│   /help 查看可用命令                          │
╰──────────────────────────────────────────────╯

❯ 看一下 main.py 是干什么的，然后给 agent/tools.py 加个新工具
```

## 使用方式

### 输入区与快捷键

主界面是常驻输入区：上方是滚动输出区，下方固定为输入框和权限模式提示行。提交后这一行会被回显到滚动区，输入框不会消失。

| 按键 | 空闲时 | 请求进行中 |
| --- | --- | --- |
| `Enter` | 提交输入 | 忽略（不触发新一轮） |
| `Esc` | 清空当前输入行 | **打断**当前这一轮 |
| `Ctrl+C` | 退出程序 | **打断**当前这一轮 |
| `Ctrl+D` | 输入为空时退出程序 | — |
| `Shift+Tab` | 循环切换权限模式 | 同左 |
| `↑` / `↓` | 翻阅历史输入（仅本次运行内） | — |

请求进行中，输入框上方会显示 `⠼ Working…（已耗时 3s · 按 esc 打断）`，可以随时 `Esc` 中止本轮。

### 权限模式

底部提示行 `▶▶ default（Shift+Tab 切换）` 显示当前模式。**权限模式是进程级的**：`/new`、`/resume` 不会改变它，重启程序才回到 `default`。

| 模式 | 读文件 | 写 / 改文件 | 执行命令 | 适用场景 |
| --- | --- | --- | --- | --- |
| `default` | ✅ 自动放行 | 🔐 弹窗审批 | 🔐 弹窗审批 | 默认，最保守 |
| `acceptEdits` | ✅ 自动放行 | ✅ 自动放行 | 🔐 弹窗审批 | 信任文件编辑，命令仍要把关 |
| `auto` | ✅ 自动放行 | ✅ 自动放行 | 🤖 LLM 安全审查 | 放手让它干活，危险命令才拦 |
| `bypass` | ✅ 自动放行 | ✅ 自动放行 | ✅ 自动放行 | ⚠️ 全部放行、不再询问，后果自负 |

需要审批时弹出选择器（`↑↓` 选择、`Enter` 确认、`Esc` 取消）：

```
是否允许执行 run_command(command=pytest -q)？
 ❯  1. 允许
    2. 允许，且本会话不再询问 run_command
    3. 拒绝
```

- **允许**：只执行这一次
- **允许，且本会话不再询问**：本会话后续同工具直接放行（`/new`、`/resume` 会清空这份白名单）
- **拒绝**：工具不执行，拒绝原因作为工具结果回填给模型，并要求它停下来等你指示，而不是自己绕过去

### 斜杠命令

输入以 `/` 开头的命令处理控制逻辑，不会发给模型：

| 命令 | 作用 |
| --- | --- |
| `/help` | 列出所有可用命令 |
| `/new` | 开启新会话：清空历史、token 计数、API 记录，换新会话 ID，同时清空权限白名单和文件读取状态 |
| `/resume` | 列出当前项目的历史会话（按修改时间倒序，首条输入作为摘要），选中后恢复历史、token 统计，并把对话回放到屏幕 |
| `/status` | 显示模型名、当前权限模式、历史消息条数、累计输入 / 输出 tokens |
| `/api-detail` | 显示最近一轮输入触发的每次 model API 调用：模型、消息条数、最后一条消息、工具清单、finish_reason、返回 parts、token usage |
| `/exit` | 退出程序 |

### 项目指令 AGENTS.md

在启动目录放一个 `AGENTS.md`，其中的约定会在**每一轮请求**里自动附加给模型（作为 instructions，每轮都带上，但不写入对话历史）。适合写项目规范：

```markdown
# AGENTS.md

- 这是 Python 3.11 项目，用 pytest 跑测试
- 改代码前先读文件；不要引入新的第三方依赖
- 提交信息用中文
```

### 一次典型会话

```
❯ 帮我把 ui/input_ui.py 里的 Hardcoded 颜色改成可配置

✻ thinking
  （模型思考过程）

⏺ tool_call
  read_file(path=/Users/.../ui/input_ui.py)

✔ tool_return
  read_file -> 1  import asyncio
                2  import time
                ...

⏺ tool_call
  edit_file(path=/Users/.../ui/input_ui.py)
    -  return HTML("<ansicyan>❯ </ansicyan>")
    +  return HTML(f"<ansicyan>{self.prompt}</ansicyan>")

✔ tool_return
  edit_file -> 已编辑 /Users/.../ui/input_ui.py（替换 1 处）

● assistant
  已把提示符颜色抽成 `self.prompt` 属性，默认值不变。
```

## 内置工具

模型只能通过下面 4 个工具接触你的系统，全部在 `agent/tools.py` 里实现。

### `read_file(path, offset=1, limit=None)`

读取文本文件，输出带行号（`cat -n` 风格），方便模型精确定位和编辑。

- 大文件用 `offset`（从 1 开始）和 `limit` 分段读取；不传 `limit` 时最多返回 2000 行，截断时会提示用 `offset` 续读
- **去重**：同一文件、同 `offset`/`limit`、且读取后文件 mtime 没变化时，直接返回「文件内容没有变化，请参考上次读取结果」，不再重复塞进上下文（省 token）
- 文件不存在 / 无权限 / 是目录 → 错误回填给模型让它自己纠正；非 UTF-8 文本 → 直接返回「不是文本文件」

### `edit_file(path, old_string, new_string, replace_all=False)`

精确字符串替换，只传改动的片段，最省 token，**修改已有文件首选**。

- 必须先 `read_file`，否则打回
- 读取之后文件又被外部改动过 → 打回要求重读，避免基于旧内容覆盖别人的改动
- `old_string` 必须逐字符一致（不含行号前缀），且默认要求**唯一匹配**；出现多次时补上下文让它唯一，或传 `replace_all=true`
- 空操作（`old_string == new_string`）会被直接打回
- 同一轮里的多个 `edit_file` / `write_file` **串行执行**，避免并发写盘互相覆盖

### `write_file(path, content)`

整体写入文件，用于**新建文件或整体重写**。

- 覆盖已存在的文件前必须先 `read_file`，且 mtime 校验同样生效
- 写入后自动登记到会话读取状态，后续要改无需重读

### `run_command(command)`

执行一条 shell 命令并返回输出。

- `shell=True`，捕获 stdout / stderr；非 0 退出码会把 stderr 附在输出后
- **超时 10 秒**，超时返回错误（长时间任务请拆小或自己另外跑）
- 执行前会过一道权限判定：高危命令要审批，确认只读的命令自动放行，其余默认要审批

## 安全机制

### 权限判定顺序

每次工具调用前按下面的顺序判定（`permissions.compute_decision`）：

1. `bypass` 模式 → 全部放行，连工具自检都不再过问
2. **工具自检**：工具自己根据参数判断（目前只有 `run_command` 挂了自检）
3. **会话白名单**：本会话点过「不再询问」的工具 → 放行
4. **只读工具**（`read_file`）→ 任何模式都放行
5. `acceptEdits` / `auto` 模式下的**编辑工具**（`edit_file`、`write_file`）→ 放行
6. 其余 → **询问**（`auto` 模式下改由 LLM 审查）

### `run_command` 自检

| 判断 | 结果 |
| --- | --- |
| 命中高危特征 `rm` / `sudo` / `dd` / `mkfs*` | 要求审批 |
| 只读白名单 `ls cat head tail grep wc pwd`，且**不含任何 shell 元字符** | 直接放行 |
| 其他（含管道、重定向、命令替换、串联等） | 交回通用规则 → 默认审批 |

白名单判断非常保守：只要命令里出现分号、`&`、管道、重定向、反引号、`$` 或换行，就视为「无法确认只读」，宁可多问一次。

### `auto` 模式：LLM 安全审查

`auto` 模式下，本该弹窗的调用会先交给一个**独立的旁路 LLM 请求**（`classifier.py`，默认同款 `deepseek-flash`）裁决：

- 转写里**只保留用户原话和工具调用**，丢弃模型自己写的文本与所有工具输出 —— 防止文件内容 / 命令输出里的提示词注入去游说审查员
- 每行用 JSON 序列化，恶意内容伪造不出 `{"user": ...}` 这样的授权行
- `temperature=0` + 强制 JSON 输出，保证判定稳定
- 拿不准就拦截（错误的拦截只是多确认一次，错误的放行可能无法挽回）
- **fail-closed**：审查请求本身出错（网络、超时、解析失败）时一律按拦截处理，并自动回退到人工审批弹窗，绝不因为「判不了」就放行
- 审查过程会在界面上以 `◆ auto_check` / `✔ 放行` / `✘ 拦截` 打印理由，随时可以审计

### 其他兜底

- 模型拒绝执行 / 被拦截后，会把理由作为工具结果回填，并要求模型停下来向你说明，**不许尝试绕过**
- 工具函数抛出的未捕获异常不会让进程崩溃，而是转成 tool result 交给模型自行纠正
- `ModelRetry` 机制：读文件失败、编辑前没读、`old_string` 不唯一等，都会把明确原因回填给模型重新决策

## 上下文与会话

### 读后写保护（`readFileState`）

每个会话持有一个 `ReadFileState`，按绝对路径记录每个文件「读到的内容、读取那一刻的 mtime、读取范围」。`edit_file` / `write_file` 修改前都查它：

- 没读过 → 打回，要求先读
- 读完之后文件被本进程之外的东西改过 → 打回，要求重读

模型自己的编辑会刷新登记时间，所以它自己的改动不会被误判为「外部修改」。`/new`、`/resume` 会换上一个全新的实例。

### 外部改动提醒

每次请求模型前，如果 `readFileState` 里有文件已被外部修改，会自动追加一条 `<system-reminder>`：

```
<system-reminder>
以下文件在你读取之后被外部修改过，你 context 里的内容可能已过时，编辑前请重新用 read_file 读取：
- /path/to/file.py
</system-reminder>
```

模型重读后登记时间刷新，下次就不会再提醒。

### 会话持久化

- 存储位置：`~/.my-coding-agent/projects/<工作目录转义>/<会话ID>.jsonl`
  - 目录名由启动时的工作目录生成，非字母数字字符替换成 `-`
  - 一行一条消息，每轮结束后追加
- `/resume` 会扫描当前项目的所有会话文件，按修改时间倒序列出（首条用户输入作摘要），选中后恢复完整历史，并从 jsonl 里的 usage 累加回 token 统计
- token 统计、模型名等运行状态见 `/status`

## 稳定性设计

| 场景 | 行为 |
| --- | --- |
| HTTP 5xx | 指数退避重试，最多 3 次（等待 1s → 2s → 4s），界面提示 `⟳` |
| HTTP 4xx | 不重试，直接抛出（多为鉴权 / 参数问题，重试无意义） |
| 网络连接失败 | 同样退避重试 3 次 |
| 工具抛异常 | 捕获后作为工具结果回填，模型自行纠正 |
| 用户 `Esc` / `Ctrl+C` 打断 | 取消当前轮，打印「已中断」；**被打断的这一轮不会写入会话历史** |
| `classifier` 自身失败 | 按拦截处理，回退人工审批 |

## 终端界面

| 标签 | 含义 |
| --- | --- |
| `❯ user` | 用户输入（回显） |
| `✻ thinking` | 模型的思考过程（完整显示，弱化样式） |
| `● assistant` | 模型最终回答（Markdown 渲染、标题左对齐） |
| `⏺ tool_call` | 工具调用及其参数 |
| `✔ tool_return` | 工具成功返回 |
| `✘ tool_retry` | 工具报错 / 被 SDK 打回重试（`ModelRetry`） |
| `◇ system` | 系统注入的提醒（如文件过期） |
| `◆ / ✔ / ✘ auto_check` | auto 模式审查中 / 放行 / 拦截 |
| `⠼ Working…` | 正在请求模型，附已耗时与打断提示 |
| `▶▶ <mode>` | 当前权限模式 |

文件操作有专门的富展示：

- `edit_file`：红绿 diff（`-` 删除行、`+` 新增行）
- `write_file`：带行号的写入内容预览（最多 8 行，超出折叠）
- `read_file`：带行号的读取结果预览（最多 8 行）

## 项目结构

```
工业级AGENT/
├── main.py               # 入口：启动 REPL、逐节点驱动 Agent 循环、分发斜杠命令
├── session.py            # 会话持久化：jsonl 追加、扫描、按 ID 恢复
├── permissions.py        # 权限模式、规则判定、审批选择器
├── classifier.py         # auto 模式的 LLM 安全审查（独立旁路请求）
├── Readme.md
├── agent/                # Agent 核心
│   ├── __init__.py       # 对外导出 agent / MODEL_NAME / api_call_log
│   ├── core.py           # Agent 组装：模型、静态 instructions、动态环境上下文
│   ├── tools.py          # 4 个工具 + run_command 权限自检 + 串行执行标记
│   ├── file_state.py     # readFileState：读后写保护、外部改动检测
│   ├── reminders.py      # 文件过期 system-reminder 正文
│   └── hooks.py          # hooks：API 记录、注入提醒、自动重试、权限关卡、异常兜底
└── ui/                   # 终端界面
    ├── __init__.py
    ├── render.py         # 共享 Console、print_step、欢迎横幅
    ├── input_ui.py       # 常驻输入区 Repl、按键绑定、Working 转圈指示器
    └── commands.py       # 斜杠命令、会话状态、消息 part 渲染
```

## 扩展开发

### 加一个工具

1. 在 `agent/tools.py` 里写一个普通函数，**类型注解 + 中文 docstring**（pydantic-ai 会自动生成 JSON Schema 给模型）：

   ```python
   def list_dir(ctx: RunContext[ReadFileState], path: str) -> str:
       """
       列出目录内容。

       Args:
           path: 目录的绝对路径
       """
       ...
   ```

2. 加进文件末尾的 `TOOLS` 列表；需要串行执行（如写文件）用 `Tool(fn, sequential=True)`。
3. 需要参与权限管控：
   - 只读工具 → 加进 `permissions.READONLY_TOOLS`
   - 编辑类工具 → 加进 `permissions.EDIT_TOOLS`
   - 需要按参数判断 → 写一个 `check(args)` 函数，用 `permissions.register_self_check("工具名", check)` 注册（返回 `"allow"` / `"ask"` / `None`）
4. 想在界面上做富展示 → 在 `ui/commands.py` 的 `_print_file_op` 里按工具名特判。

### 加一个斜杠命令

1. 在 `ui/commands.py` 写处理函数，签名 `(state: SessionState) -> bool`，返回 `False` 表示退出程序（异步也可以，`/resume` 就是异步的）：

   ```python
   def cmd_xxx(state: SessionState) -> bool:
       console.print("...")
       return True
   ```

2. 注册进文件末尾的 `COMMANDS` 字典即可。

### 换模型

- 主模型：`agent/core.py` 里的 `MODEL_NAME` 与 provider
- classifier：`classifier.py` 里的 `CLASSIFIER_MODEL` 与 `base_url`

## 常见问题

**启动报 `RuntimeError: 请先设置环境变量 API_KEY`**
没有设置环境变量。注意 `export` 只在当前终端窗口有效，新窗口要重新设置。

**`ModuleNotFoundError: No module named 'pydantic_ai'`**
依赖没装或虚拟环境没激活；确认 `pip list` 里能看到 `pydantic-ai`，且版本 ≥ 2.0。

**`run_command` 总是超时**
工具内置 10 秒超时，长任务（安装依赖、跑全量测试）请拆成小步骤，或让模型分步执行。

**历史会话找不到了**
会话按「启动时的工作目录」分目录存储。在别的目录启动程序，就看不到原目录的会话；回到原目录再 `/resume` 即可。

**审批弹窗显示错乱**
需要支持 ANSI 颜色的现代终端；过老的 cmd.exe / 颜色被关闭的终端可能显示异常。

## 已知限制

- 模型硬编码为 `deepseek-flash`（主流程与 classifier 各一处），换模型需改代码
- 对话历史**不做自动压缩**，长会话会持续增长并推高 token 消耗；建议用 `/new` 开新会话
- `run_command` 只有 10 秒超时，无法直接跑长任务
- 跨进程没有并发写保护，只靠 mtime 检测「读后被外部改动」
- 只处理 UTF-8 文本文件；二进制文件读取会返回错误
- 被 `Esc` / `Ctrl+C` 打断的那一轮不会写入会话历史，恢复后看不到该轮内容
- 项目暂未提供 `requirements.txt` / `pyproject.toml` 与自动化测试
