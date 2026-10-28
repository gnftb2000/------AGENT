import asyncio

from pydantic_ai import Agent
from pydantic_graph import End

import session
from agent import agent, MODEL_NAME, api_call_log
from ui.commands import (
    COMMANDS,
    SessionState,
    console,
    print_part,
    print_welcome_banner,
)
from ui.input_ui import Repl


async def handle_command(user_input, state):
    """
    处理以 / 开头的命令。
    返回 'pass'：不是命令，交给 Agent；
    返回 'continue'：命令已处理，进入下一轮；
    返回 'break'：命令要求退出程序。
    """
    if not user_input.startswith("/"):
        return "pass"
    cmd_name = user_input[1:].split()[0]
    command = COMMANDS.get(cmd_name)
    if command is None:
        console.print(f"未知命令：/{cmd_name}，输入 /help 查看可用命令\n")
        return "continue"
    result = command.handler(state)
    # 个别命令（如 /resume）要弹交互式列表，是异步的，需要 await
    if asyncio.iscoroutine(result):
        result = await result
    return "continue" if result else "break"


def apply_result(state, result):
    """
    跑完一轮 Agent 后，把结果同步到 SessionState。
    """
    state.history = result.all_messages()
    usage = result.usage
    state.input_tokens += usage.input_tokens
    state.output_tokens += usage.output_tokens
    state.last_api_calls = list(api_call_log)
    # 把本轮新增的消息追加到会话文件
    session.append_messages(state.session_id, result.new_messages())


async def run_agent_loop(user_input, state):
    """
    展开 agent.run_sync()，逐节点驱动 Agent 循环，每步实时打印。
    """
    api_call_log.clear()

    async with agent.iter(user_input, message_history=state.history) as run:
        node = run.next_node

        while not isinstance(node, End):
            node = await run.next(node)

            if Agent.is_call_tools_node(node):
                for part in node.model_response.parts:
                    print_part(part)

            elif Agent.is_model_request_node(node):
                for part in node.request.parts:
                    if part.part_kind in ("tool-return", "retry-prompt"):
                        print_part(part)

    apply_result(state, run.result)


async def main():
    state = SessionState(
        model_name=MODEL_NAME,
        session_id=session.new_session_id(),
    )
    print_welcome_banner("my-claude-code")

    # 常驻输入区：输入框整个会话期间不消失
    repl = Repl(state)

    async def on_submit(user_input):
        # 每次回车提交一行输入，都走这里
        # 先处理 / 开头的命令
        action = await handle_command(user_input, state)
        if action == "break":
            # 命令要求退出，结束常驻输入区
            repl.exit()
            return
        if action == "continue":
            return

        # 核心 Agent 循环：开请求时显示 working...，结束 / 被打断后由 Repl 统一隐藏；中途按 ESC / Ctrl+C 会打断
        repl.start_working()
        await run_agent_loop(user_input, state)

    await repl.run(on_submit)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, EOFError):
        pass
