from langchain.tools import tool, ToolRuntime
from langchain_core.messages import ToolMessage
from langgraph.types import Command


@tool
def record_observation(
    observations: str,
    runtime: ToolRuntime,
) -> Command:
    """
    Record an important finding discovered during Kubernetes investigation.
    """

    return Command(
        update={
            "observations": [observations],
            "messages": [
                ToolMessage(
                    content=f"Observations recorded: {observations}",
                    tool_call_id=runtime.tool_call_id,
                )
            ],
        }
    )
