import subprocess


def quick_health_check() -> tuple[bool, str]:
    """
    Deterministic Kubernetes health check.

    Returns:
        (healthy, evidence)
    """

    checks = []

    # ---------------------------------------------------------
    # 1. Check Kubernetes nodes
    # ---------------------------------------------------------
    try:
        result = subprocess.run(
            ["kubectl", "get", "nodes", "--no-headers"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            return False, f"Node check failed: {result.stderr.strip()}"

        unhealthy_nodes = []

        for line in result.stdout.strip().splitlines():
            if not line.strip():
                continue

            columns = line.split()

            # kubectl get nodes output:
            # NAME STATUS ROLES AGE VERSION
            if len(columns) >= 2:
                node_name = columns[0]
                status = columns[1]

                if status != "Ready":
                    unhealthy_nodes.append(
                        f"{node_name}: {status}"
                    )

        if unhealthy_nodes:
            checks.append(
                "Unhealthy nodes: " + ", ".join(unhealthy_nodes)
            )
        else:
            checks.append("All nodes are Ready")

    except subprocess.TimeoutExpired:
        return False, "Node check timed out"

    # ---------------------------------------------------------
    # 2. Check pod phases
    # ---------------------------------------------------------
    try:
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "pods",
                "-A",
                "--no-headers",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            return False, f"Pod check failed: {result.stderr.strip()}"

        unhealthy_pods = []

        for line in result.stdout.strip().splitlines():
            if not line.strip():
                continue

            columns = line.split()

            # kubectl get pods -A output:
            #
            # NAMESPACE NAME READY STATUS RESTARTS AGE
            #
            if len(columns) >= 4:
                namespace = columns[0]
                pod_name = columns[1]
                status = columns[3]

                if status not in ("Running", "Succeeded"):
                    unhealthy_pods.append(
                        f"{namespace}/{pod_name}: {status}"
                    )

        if unhealthy_pods:
            checks.append(
                "Unhealthy pods: " + ", ".join(unhealthy_pods)
            )
        else:
            checks.append("All pods are Running/Succeeded")

    except subprocess.TimeoutExpired:
        return False, "Pod check timed out"

    # ---------------------------------------------------------
    # 3. Check deployments
    # ---------------------------------------------------------
    try:
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "deployments",
                "-A",
                "--no-headers",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            return False, (
                f"Deployment check failed: "
                f"{result.stderr.strip()}"
            )

        unhealthy_deployments = []

        for line in result.stdout.strip().splitlines():
            if not line.strip():
                continue

            columns = line.split()

            # kubectl get deployments -A:
            #
            # NAMESPACE NAME READY UP-TO-DATE AVAILABLE AGE
            #
            if len(columns) >= 4:
                namespace = columns[0]
                deployment = columns[1]
                ready = columns[2]

                # READY looks like "3/3", "2/3", etc.
                if "/" in ready:
                    desired, available = ready.split("/", 1)

                    if desired != available:
                        unhealthy_deployments.append(
                            f"{namespace}/{deployment}: "
                            f"{ready} ready"
                        )

        if unhealthy_deployments:
            checks.append(
                "Unhealthy deployments: "
                + ", ".join(unhealthy_deployments)
            )
        else:
            checks.append("All deployments are ready")

    except subprocess.TimeoutExpired:
        return False, "Deployment check timed out"

    # ---------------------------------------------------------
    # Final result
    # ---------------------------------------------------------

    healthy = not any(
        message.startswith("Unhealthy")
        for message in checks
    )

    evidence = "\n".join(
        f"- {message}"
        for message in checks
    )

    return healthy, evidence
