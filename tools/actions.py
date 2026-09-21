from langchain.tools import tool, ToolRuntime
from langchain_core.messages import ToolMessage
from langgraph.types import Command

@tool 
def record_action(actions: str, runtime: ToolRuntime) -> Command:
    """
    Record an action performed by agent during kubernetes troubleshooting.
    """

    return Command(
        update={
            "actions_taken": [actions],
            "messages": [
                ToolMessage(content=f"Actions recorded: {actions}", tool_call_id=runtime.tool_call_id)
            ]
        }
    )

@tool
def get_actions(runtime: ToolRuntime) -> Command:
    """
    Get the actions recorded by the agent from the state.
    """
    return runtime.state["actions_taken"]