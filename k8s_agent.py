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
from memory import create_table, get_cluster_name, save_incident_report
from tools import run_kubectl, get_kubernetes_events, record_observation, record_hypothesis, record_action, record_verifications, rollout_restart_deployment, rollout_edit_deployment

load_dotenv()


class KubernetesAgentState(AgentState):
    health_evidence: NotRequired[str]
    health_status: NotRequired[str]

    observations: NotRequired[Annotated[list[str], add]]
    hypotheses: NotRequired[Annotated[list[str], add]]
    actions_taken: NotRequired[Annotated[list[str], add]]
    verification_results: NotRequired[Annotated[list[str], add]]

    attempt_count: NotRequired[int]
    resolution_status: NotRequired[str]

from pydantic import BaseModel, Field
class output_format(BaseModel):
    observations: list[str] = Field(description="Observations of the problem")
    actions_taken: list[str] = Field(description="Actions taken to fix the problem")
    status: str = Field(description="fixed or broken")
    cluster_name: str = Field(description="Name of the cluster")
    namespace: str = Field(description="Namespace of the problem")
    resource_name: str = Field(description="Kubernetes kind, e.g. Deployment, Pod, etc.")


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
    cluster = get_cluster_name()
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
    middleware=[short_circuit_if_healthy,stop_after_max_attempts],
    state_schema=KubernetesAgentState,
    response_format=output_format,
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

- Use only get_kubernetes_events to investigate the problem.
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
3. Do not assume the problem is fixed just because the restart succeeded. If the problem is still present, continue investigating.

In the end provide exactly one verdict:

Status: Healthy

or

Status: Unhealthy

Also provide the output in structured format so it can be added into the database later.
"""


if len(sys.argv) > 1:
    user_prompt = " ".join(sys.argv[1:])
else:
    user_prompt = prompt

# Step 1: make sure the memory table exists. No save/search yet.
create_table()
# Step 3: real cluster id from kubectl, not from the model.
cluster = get_cluster_name()

result = agent.invoke(
    {
        "messages": [
            HumanMessage(content=user_prompt)
        ]
    }, {"configurable": {"thread_id": "1"}}
)

report = result.get("structured_response")



if report is not None:
    #report.cluster_name = cluster
    save_incident_report(report)
    from pprint import pprint
    pprint(report)
