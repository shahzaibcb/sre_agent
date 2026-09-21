from typing import Any, Annotated
from operator import add
from typing_extensions import NotRequired
from langchain.agents import create_agent, AgentState
from langchain.agents.middleware import before_agent, before_model, hook_config

from langgraph.runtime import Runtime
from langchain_deepseek import ChatDeepSeek
from langchain_core.messages import HumanMessage, AIMessage
from dotenv import load_dotenv
import sys
from langgraph.checkpoint.memory import InMemorySaver

from health import quick_health_check
from tools import run_kubectl, get_kubernetes_events, record_observation, record_hypothesis, record_action, record_verifications, rollout_restart_deployment, rollout_edit_deployment

load_dotenv()  # load the environment variables from the .env file


class KubernetesAgentState(AgentState):
    health_evidence: NotRequired[str]
    health_status: NotRequired[str]

    observations: NotRequired[Annotated[list[str], add]]
    hypotheses: NotRequired[Annotated[list[str], add]]
    actions_taken: NotRequired[Annotated[list[str], add]]
    verification_results: NotRequired[Annotated[list[str], add]]

    attempt_count: NotRequired[int]
    resolution_status: NotRequired[str]


@before_agent
@hook_config(can_jump_to=["end"])
def short_circuit_if_healthy(state: KubernetesAgentState, runtime: Runtime) -> dict[str, Any] | None:
    """If the cluster is healthy, skip the model entirely — 0 tokens spent."""
    healthy, evidence = quick_health_check()
    if healthy:
        return {
            "health_status": "Healthy",
            "health_evidence": evidence,
            
            "messages": [AIMessage(content=f"Status: Healthy\n{evidence}")],
            "jump_to": "end",
        }
    # Unhealthy: let the agent proceed, but hand it the evidence up front
    # so it doesn't waste its first tool call rediscovering the problem.
    return {
        "health_status": "Unhealthy",
        "health_evidence": evidence,
        "observations": [evidence],
        "hypotheses": [],
        "actions_taken": [],
        "verification_results": [],
        "attempt_count": 0,
        "resolution_status": "investigating",

        "messages": [AIMessage(content=(
            f"Status: Unhealthy\n{evidence}\n\n"
            "Investigate the root cause using run_kubectl and get_kubernetes_events, "
            "then give the final verdict."
        ))],
    }


@before_model
@hook_config(can_jump_to=["end"])
def stop_after_max_attempts(state: KubernetesAgentState, runtime: Runtime) -> dict[str, Any] | None:
    """Once remediation attempts are exhausted, end the run instead of looping."""
    if state.get("resolution_status") == "escalation_required":
        attempts = state.get("attempt_count", 0)
        return {
            "messages": [AIMessage(content=(
                "Status: Unhealthy\n"
                f"Escalation required — {attempts} remediation attempts exhausted "
                "without resolving the problem."
            ))],
            "jump_to": "end",
        }
    return None


agent = create_agent(
    tools=[run_kubectl, get_kubernetes_events, record_observation, record_hypothesis, record_action, record_verifications, rollout_restart_deployment, rollout_edit_deployment],
    model=ChatDeepSeek(model="deepseek-chat"),
    middleware=[short_circuit_if_healthy, stop_after_max_attempts],
    state_schema=KubernetesAgentState,
    checkpointer=InMemorySaver(),
)

prompt = """
Assess the health of the Kubernetes cluster.

Check:
1. nodes are Ready
2. kube-system pods are Running
3. no pods cluster-wide are in a non-Running/Succeeded phase
4. deployments are ready

If the cluster is unhealthy:

- Investigate using run_kubectl.
- Use get_kubernetes_events when useful.
- When you discover an important finding, use record_observation.
- Continue investigating until you have a reasonable root-cause hypothesis.
- When you perform an investigation action, use record_action to record what you did.
- After performing an action, verify its result. Use record_verifications to record what happened.
- Do not assume an action fixed the problem without verification.

Provide a brief summary of:
- observations
- likely root cause
- actionable steps to fix it

You are allowed to edit and restart a Kubernetes Deployment when
your investigation provides a reasonable reason to do so.

Before restarting a Deployment:

1. Investigate the problem.
2. Record the relevant observations.
3. Record your hypothesis.
4. Decide whether a rollout restart is an appropriate action.
5. If needed, use rollout_edit_deployment to edit the incorrect Deployment including image version and restart the Deployment.

After any remediation action:

1. Re-check the affected Kubernetes resources.
2. Determine whether the original problem is resolved.
3. Use record_verifications to record the result.
4. If the problem is still present, continue investigating.
5. Do not perform more than 3 remediation attempts.
6. If the problem remains after 3 attempts, set the final status to escalation required.

After restarting:

1. Verify the Deployment and its pods.
2. Record the verification result.
3. Do not assume the problem is fixed just because the restart succeeded.

In the end provide exactly one verdict:

Status: Healthy

or

Status: Unhealthy
"""


if len(sys.argv) > 1:
    user_prompt = " ".join(sys.argv[1:])
else:
    user_prompt = prompt


result = agent.invoke(
    {
        "messages": [
            HumanMessage(content=user_prompt)
        ]
    }, {"configurable": {"thread_id": "1"}}
)

final_output = result["messages"][-1].content
# Provide a clean summary with proper line breaks for readability
def clean_summary(output: str) -> str:
    # Remove excessive line breaks, strip leading/trailing whitespace
    # and replace multiple spaces with a single space if needed.
    lines = output.splitlines()
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped:
            cleaned_lines.append(stripped)
    # Join the cleaned lines into paragraphs.
    return "\n".join(cleaned_lines)

print(clean_summary(final_output))
