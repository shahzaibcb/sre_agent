from langchain.tools import tool, ToolRuntime
from langchain_core.messages import ToolMessage
from langgraph.types import Command
import subprocess

MAX_REMEDIATION_ATTEMPTS = 3

@tool
def rollout_edit_deployment(
    namespace: str,
    deployment: str,
    image: str,
    container: str,
    version: str,
    runtime: ToolRuntime,
) -> Command:
    """
    Edit a Kubernetes Deployment.

    This is a remediation action. Only use it when investigation
    provides a reasonable reason to edit and restart the deployment.
    """
    attempts = runtime.state.get("attempt_count", 0)
    if attempts >= MAX_REMEDIATION_ATTEMPTS:
        return Command(
            update={
                "resolution_status": "escalation_required",
                "messages": [
                    ToolMessage(
                        content=(
                            f"Refused: {attempts}/{MAX_REMEDIATION_ATTEMPTS} "
                            "remediation attempts already used. Stop remediating "
                            "and report 'Status: Unhealthy - escalation required'."
                        ),
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    try:
        result = subprocess.run(
            [
                "kubectl",
                "set",
                "image",
                f"deployment/{deployment}",
                f"{container}={image}:{version}",
                "-n",
                namespace,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return Command(
            update={
                "resolution_status": "unhealthy",
                "messages": [
                    ToolMessage(
                        content="Edit deployment timed out",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )
    if result.returncode != 0:
        return Command(
            update={
                "actions_taken": [
                    f"Edit deployment failed for "
                    f"{namespace}/{deployment}"
                ],
                "messages": [
                    ToolMessage(
                        content=(
                            f"Edit deployment failed: "
                            f"{result.stderr.strip()}"
                        ),
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    deployment = (
        f"Deployment {namespace}/{deployment} edited"
    )

    return Command(
        update={
            "actions_taken": [deployment],
            "attempt_count": attempts + 1,
            "resolution_status": "verifying",
            "messages": [
                ToolMessage(
                    content=result.stdout.strip() or deployment,
                    tool_call_id=runtime.tool_call_id,
                )
            ],
        }
    )