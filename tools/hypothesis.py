from langchain.tools import tool, ToolRuntime
from langchain_core.messages import ToolMessage
from langgraph.types import Command


@tool 
def record_hypothesis(hypothesis: str, runtime: ToolRuntime) -> Command:
    """
    Record a possible root cause discovered during Kubernetes investigation.
    """

    return Command(
        update={
            "hypotheses": [hypothesis],
            "messages": [ToolMessage(content=f"Hypothesis recorded: {hypothesis}", tool_call_id=runtime.tool_call_id)],
        }
    )