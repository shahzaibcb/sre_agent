import shlex
import subprocess

from langchain.tools import tool

ALLOWED_VERBS = [
    "get",
    "describe",
    "logs",
    "top",
    "explain",
    "version",
    "cluster-info",
    "api-resources",
]


@tool
def run_kubectl(command: str) -> str:
    """
    Run a read-only kubectl command against the current cluster and return stdout.

    `command` is the part AFTER 'kubectl', e.g.
        "get nodes -o wide"
        "get pods -A --field-selector=status.phase!=Running"
        "top nodes"
        "version -o json"
        "cluster-info"

    Only these verbs are allowed: get, describe, logs, top, explain, version, cluster-info, api-resources.
    Write verbs (create, delete, patch, replace, scale, rollout, exec, apply, edit) are rejected.
    """
    tokens = shlex.split(command)
    if not tokens:
        return "error: empty command"
    verb = tokens[0]
    if verb not in ALLOWED_VERBS:
        return f"error: verb '{verb}' not allowed. Allowed: {sorted(ALLOWED_VERBS)}"
    try:
        result = subprocess.run(
            ["kubectl", *tokens],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return "error: kubectl timed out after 15s"

    if result.returncode != 0:
        return f"error (exit {result.returncode}): {result.stderr.strip()}"
    return result.stdout
