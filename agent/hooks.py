"""
挂在 Agent 上的 hooks，用来抓每次 model API 调用的元数据。

主循环在每轮 run_sync 之前清空 api_call_log，跑完后快照到 SessionState 里，
/api-detail 命令再把这一轮的所有调用展示给用户。
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import Hooks
from pydantic_ai.exceptions import ModelHTTPError, ModelAPIError

import permissions
from ui.render import console


@dataclass
class ApiCall:
    """
    一次 model API 调用的元数据。before_model_request 创建并填充上半部分，
    after_model_request 填充下半部分。
    """
    # request 侧
    model: str
    messages_count: int
    # 这次发送给模型的 messages 中最后一条消息的最后一个 part
    last_part: Any
    tools: list
    # response 侧（after hook 填充）
    finish_reason: str = ""
    parts_kinds: list = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


# 主循环在每轮 run_sync 之前清空它
api_call_log: list[ApiCall] = []

hooks = Hooks()

# ---------- API 调用记录 ----------

@hooks.on.before_model_request
async def _record_request(ctx, request_context):
    """
    每次发起 model 调用之前，创建一条 ApiCall 记录。
    在每次调模型前记录模型名、这次发了几条消息、带了哪些工具、
    最后一个 part 是什么（也就是输出里 last_message 那行）。
    """
    msgs = list(request_context.messages)
    last_part = msgs[-1].parts[-1] if msgs and msgs[-1].parts else None
    try:
        tool_names = [t.name for t in request_context.model_request_parameters.function_tools]
    except AttributeError:
        tool_names = []
    api_call_log.append(ApiCall(
        model=request_context.model.model_name,
        messages_count=len(msgs),
        last_part=last_part,
        tools=tool_names,
    ))
    return request_context


@hooks.on.after_model_request
async def _record_response(ctx, request_context, response):
    """
    每次 model 调用返回后，填充上面这条 ApiCall 的 response 字段。
    在模型返回后记录结束原因和 token 用量
    """
    if api_call_log:
        call = api_call_log[-1]
        call.finish_reason = str(response.finish_reason) if response.finish_reason else "unknown"
        call.parts_kinds = [p.part_kind for p in response.parts]
        call.input_tokens = response.usage.input_tokens
        call.output_tokens = response.usage.output_tokens
    return response

MAX_RETRIES = 3

@hooks.on.model_request
async def _retry_on_error(ctx, *, request_context, handler):
    for attempt in range(MAX_RETRIES + 1):
        try:
            return await handler(request_context)
        except ModelHTTPError as e:
            # http 错误，根据错误码进行判断

            if e.status_code < 500:
                # 4xx 的错误，不重试直接报错
                raise
            if attempt >= MAX_RETRIES:
                console.print(f"[bold red]✗ HTTP {e.status_code}，重试 {MAX_RETRIES} 次后仍失败[/]")
                raise

            # 指数退避算法
            wait = 2 ** attempt
            console.print(
                f"[bold yellow]⟳ HTTP {e.status_code}，{wait}s 后重试 "
                f"({attempt + 1}/{MAX_RETRIES})...[/]"
            )
            await asyncio.sleep(wait)

        except ModelAPIError:
            # dns 等网络不通的错误，自动重试
            if attempt >= MAX_RETRIES:
                console.print(f"[bold red]✗ 网络连接失败，重试 {MAX_RETRIES} 次后仍无法连接[/]")
                raise

            # 指数退避算法
            wait = 2 ** attempt
            console.print(
                f"[bold yellow]⟳ 网络连接失败，{wait}s 后重试 "
                f"({attempt + 1}/{MAX_RETRIES})...[/]"
            )
            await asyncio.sleep(wait)
# ---------- 工具调用权限检查 ----------

@hooks.on.tool_execute
async def _check_permission(ctx, *, call, tool_def, args, handler):
    """
    工具执行前的权限关卡。allow 就调用 handler 真正执行；
    ask 就弹审批列表；deny 则把拒绝原因当作工具结果回填，让模型自行纠正。
    """
    decision = permissions.compute_decision(call.tool_name, args)
    if decision == "allow":
        # 放行，handler(args) 才是真正执行工具的那一步
        return await handler(args)

    # decision == "ask"，弹审批让用户决定
    choice = await permissions.prompt_approval(call.tool_name, args)
    if choice == "once":
        return await handler(args)
    if choice == "always":
        # 记进会话白名单，本会话内这个工具不再询问
        permissions.state.session_allowed.add(call.tool_name)
        return await handler(args)

    # 拒绝：不执行工具，把拒绝原因回填给模型，让它停下来等用户发话，而不是自作主张绕过去
    return f"用户拒绝了对 {call.tool_name} 的调用，这次调用没有执行。请停下手上的事，等用户告诉你接下来该怎么做。"


# ---------- 工具执行异常兜底 ----------

@hooks.on.tool_execute_error
async def _handle_tool_error(ctx, *, call, tool_def, args, error):
    """
        工具函数抛出未捕获异常时，不让进程崩溃，
        而是把错误信息作为 tool result 返回给模型，让它自行纠正。
        """
    console.print(f"[bold red]✗ 工具 {call.tool_name} 出错：{error}[/]")
    return f"工具执行出错：{type(error).__name__}: {error}"