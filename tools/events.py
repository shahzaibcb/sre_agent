import subprocess

from langchain.tools import tool


@tool
def get_kubernetes_events(namespace: str = "") -> str:
    """
    Get recent Kubernetes events.

    If namespace is provided, return events from that namespace.
    Otherwise, return events from all namespaces.
    """

    if namespace:
        command = [
            "kubectl",
            "get",
            "events",
            "-n",
            namespace,
            "--sort-by=.lastTimestamp",
        ]
    else:
        command = [
            "kubectl",
            "get",
            "events",
            "-A",
            "--sort-by=.lastTimestamp",
        ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return "error: kubectl events timed out after 15s"

    if result.returncode != 0:
        return f"error (exit {result.returncode}): {result.stderr.strip()}"

    return result.stdout