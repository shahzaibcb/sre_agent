from langchain.tools import tool, ToolRuntime
from langchain_core.messages import ToolMessage
from langgraph.types import Command


@tool
def record_verifications(result: str, runtime: ToolRuntime) -> Command:
    """
    Record the result of varifying an action or checking
    whether the kubernetes issue has been resolved.
    """
    return Command(
        update={
            "verification_results": [result],
            "messages": [
                ToolMessage(content=f"Verification result recorded: {result}", tool_call_id=runtime.tool_call_id)
            ]
        }
    )