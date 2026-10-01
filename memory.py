"""
Step 1 only: connect to Postgres and create the memory table.

We do not save or search yet. That comes in later steps.

End goal (later):
  next time a Deployment is unhealthy, look up this table for
  the same cluster + same Deployment + same kind of problem,
  and reuse the action that fixed it.
"""

import os
import subprocess

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv()

def get_db_url():
    return os.getenv("SRE_MEMORY_DB_URI")


def get_cluster_name():
    """Ask kubectl which cluster this run is talking to."""
    result = subprocess.run(
        ["kubectl", "config", "current-context"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    name = result.stdout.strip()
    if result.returncode != 0 or name == "":
        raise RuntimeError("Could not read kubectl current-context")
    return name


def create_table():
    """
    Open Postgres and create `incidents` if it does not exist.

    Each later row will be one fix we learned:
      - cluster        -> which kube context (prod vs staging)
      - namespace      -> e.g. default
      - resource_name  -> e.g. nginx-deployment
      - observations   -> what was wrong
      - action_taken   -> what we did
      - status         -> fixed or broken
    """
    sql = """
    CREATE TABLE IF NOT EXISTS incidents (
        id BIGSERIAL PRIMARY KEY,
        cluster TEXT NOT NULL,
        namespace TEXT NOT NULL,
        resource_name TEXT NOT NULL,
        observations TEXT,
        action_taken TEXT,
        status TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """
    db_url = get_db_url()
    with psycopg.connect(db_url) as conn:
        conn.execute(sql)
        conn.commit()
    print("Step 1 done: connected to Postgres and table `incidents` is ready.")


def save_incident_report(report):
    """
    Only Write one finished report into the incidents table if the issue and fix was new.
    Do not bloat database table with unnecessary new additions
    Call this after we stamp cluster_name from kubectl.
    Lists (observations, actions_taken) are stored as plain text.
    """
    if report is None:
        return

    observations = report.observations
    if isinstance(observations, list):
        observations = "\n".join(observations)

    actions = report.actions_taken
    if isinstance(actions, list):
        actions = "\n".join(actions)

    sql = """
    INSERT INTO incidents (
        cluster, namespace, resource_name, observations, action_taken, status
    ) VALUES (%s, %s, %s, %s, %s, %s)
    """
    with psycopg.connect(get_db_url()) as conn:
        conn.execute(
            sql,
            (
                report.cluster_name,
                report.namespace,
                report.resource_name,
                observations,
                actions,
                report.status,
            ),
        )
        conn.commit()
    print("Saved incident to Postgres.")



