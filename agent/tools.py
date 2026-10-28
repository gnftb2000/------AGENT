"""
Coding Agent 用到的三个工具：读文件、写文件、跑 shell 命令。
"""
import re
import shlex
import subprocess
from pydantic_ai.exceptions import ModelRetry

import permissions

def read_file(path: str) -> str:
    """
    读取指定文件的内容。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        raise ModelRetry(f"文件 {path} 不存在，请确认路径或换一个文件")
    except PermissionError:
        raise ModelRetry(f"没有权限读取 {path}，请换一个可读的文件")
    except IsADirectoryError:
        raise ModelRetry(f"{path} 是一个目录，请指定目录下的具体文件")
    except UnicodeDecodeError:
        return f"错误：{path} 不是文本文件，无法读取"



def write_file(path: str, content: str) -> str:
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"已写入 {path}"
    except FileNotFoundError:
        # 换个已存在的目录就能成功，交给模型重试
        raise ModelRetry(f"目录不存在，无法写入 {path}，请换一个已存在的目录")
    except PermissionError:
        raise ModelRetry(f"没有权限写入 {path}，请换一个可写的路径")
    except OSError as e:
        # 磁盘已满之类，重试也白搭，直接当结果返回
        return f"错误：写入 {path} 失败 ({e})"


def run_command(command: str) -> str:
    """
    执行一条 shell 命令并返回输出。
    """
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, errors="replace", timeout=10
        )
        output = result.stdout
        if result.returncode != 0:
            output += f"\n[错误] {result.stderr}"
        return output or "(无输出)"
    except subprocess.TimeoutExpired:
        return "[错误] 命令执行超时（10秒）"
    except OSError as e:
        return f"[错误] 无法执行命令 ({e})"

# 高危命令的特征：删除文件、提权、直写磁盘
DANGEROUS_PATTERNS = [
    r"\brm\b",
    r"\bsudo\b",
    r"\bdd\b",
    r"\bmkfs\w*\b",
]


# 只读命令白名单
READONLY_COMMANDS = {"ls", "cat", "head", "tail", "grep", "wc", "pwd"}
# 串联、管道、重定向和命令替换都可能夹带写操作
SHELL_META = re.compile(r"[;&|<>`$\n]")


def is_readonly_command(command: str) -> bool:
    """
    保守地判断命令是否只读：必须是白名单里的单条命令，不带任何 shell 元字符。
    """
    if SHELL_META.search(command):
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    return bool(tokens) and tokens[0] in READONLY_COMMANDS


def run_command_self_check(args: dict):
    """
    run_command 的权限自检：命中高危特征就要求审批，确认只读就直接放行，其余交给通用规则。
    """
    command = args.get("command", "")
    if any(re.search(pattern, command) for pattern in DANGEROUS_PATTERNS):
        return "ask"
    if is_readonly_command(command):
        return "allow"
    # 既不危险也不能确认只读，交给通用规则决定
    return None


# 把自检挂到权限模块的注册表上
permissions.register_self_check("run_command", run_command_self_check)

# Pydantic AI 支持 tools=[plain_function]，从函数签名 + docstring 自动生成 JSON Schema
TOOLS = [read_file, write_file, run_command]

