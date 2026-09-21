# Site_Reliability_Engineer

An autonomous Kubernetes SRE agent that triages cluster incidents, investigates
to root cause, and remediates inside policy guardrails — built on LangChain and
LangGraph.

The design premise: **an agent allowed to change production must be harder to
convince than one that only reads it.** Most of the engineering here is spent on
the parts that stop the agent from acting, not the parts that let it.

## What it does

On each run the agent:

1. Runs a deterministic health check — nodes `Ready`, pods `Running`/`Succeeded`,
   deployments at full replica count.
2. **Short-circuits to a verdict if the cluster is healthy — without calling the
   model at all.** The common case costs zero tokens.
3. If unhealthy, investigates with read-only `kubectl` and cluster events,
   recording observations and hypotheses into typed state as it goes.
4. Remediates — rollout restart or image correction — only when the
   investigation justifies it, and only within a hard attempt cap.
5. Re-checks the cluster and records whether the fix actually worked.
6. Emits exactly one verdict: `Status: Healthy` or `Status: Unhealthy`.

## Design decisions

### The cheap path avoids the model entirely

`quick_health_check()` is plain `kubectl` and string parsing — no LLM. It runs in
`@before_agent` middleware, and on a healthy cluster returns `jump_to: "end"`.

A healthy cluster is the overwhelmingly common case. Paying an LLM to confirm it
is the single easiest way to make an ops agent too expensive to run on a short
interval. When the cluster *is* broken, the same evidence is handed to the model
in its opening message, so it never spends a tool call rediscovering what the
health check already knows.

### Investigation state is structured, not conversational

The agent's findings do not live in chat scrollback. `KubernetesAgentState`
carries `observations`, `hypotheses`, `actions_taken`, and `verification_results`
as reducer-backed lists, written by tools that return LangGraph `Command`
objects.

This makes the reasoning trail queryable rather than something you reconstruct by
reading a transcript — which is what makes the next feature (below) possible.

### Remediation is capped in two independent places

Any agent that can restart a Deployment can restart it in a loop. The cap is
enforced twice, deliberately:

- **In the tools.** Both mutating tools check `attempt_count` and refuse before
  reaching `subprocess.run`. The guard sits at the point of the side effect, so
  no amount of model creativity gets past it.
- **In middleware.** `stop_after_max_attempts` ends the run once the state is
  `escalation_required`, so the agent doesn't burn tokens retrying into a refusal.

The tool guard is the safety property; the middleware is the cost property.
Neither alone is sufficient, which is why both are there.

### Reads and writes are separated at the tool boundary

`run_kubectl` accepts an allowlist of verbs — `get`, `describe`, `logs`, `top`,
`explain`, `version`, `cluster-info`, `api-resources`. Every write verb is
rejected. Mutating the cluster requires a purpose-built tool with its own
signature and its own guard, so there is no path from "the model wrote a clever
string" to an arbitrary cluster change.

### A restart that succeeds is not a problem that is fixed

`kubectl rollout restart` exiting `0` means the command was accepted, not that
the outage ended. The agent is required to re-check the affected resources and
record the result before claiming resolution.

## Architecture

```
┌─ before_agent ──────────────────────────────────────────┐
│ quick_health_check()   deterministic, no model          │
│   healthy   → emit verdict, jump_to end   (0 tokens)    │
│   unhealthy → seed state + evidence, continue           │
└────────────────────────┬────────────────────────────────┘
                         ▼
┌─ before_model ──────────────────────────────────────────┐
│ stop_after_max_attempts  → end if escalation_required   │
└────────────────────────┬────────────────────────────────┘
                         ▼
        ┌────────── model ⇄ tools loop ──────────┐
        │  read      run_kubectl                 │
        │            get_kubernetes_events       │
        │  record    record_observation          │
        │            record_hypothesis           │
        │            record_action               │
        │            record_verifications        │
        │  mutate    rollout_restart_deployment  │ ← attempt-capped
        │            rollout_edit_deployment     │ ← attempt-capped
        └────────────────────────────────────────┘
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env        # add your DEEPSEEK_API_KEY
kubectl config current-context   # confirm you are pointed at the right cluster
python k8s_agent.py
```

The agent uses whatever cluster your current `kubectl` context points at, and it
can write to it. Point it at a test cluster first.

### Try it

Break a deployment and watch it recover:

```bash
kubectl create deployment nginx --image=nginx:latest 
kubectl set image deployment/nginx nginx=nginx:latests   # typo → ImagePullBackOff
python k8s_agent.py
```

## Limitations

Stated plainly, because an ops tool that oversells itself is worse than one that
does less:

- **No memory between runs.** `InMemorySaver` dies with the process, so the agent
  re-investigates an identical failure from scratch every time. This is the next
  thing to build (see below).
- **Verification is coarse.** "Deployment ready, pods Running" does not mean the
  application is serving correctly, and a Deployment scaled to `0/0` currently
  reads as healthy.
- **Attempt cap is per-run**, not per-time-window. Three attempts per invocation;
  nothing limits invocations.
- **Single-cluster, single-threaded.** No multi-cluster routing, no concurrency.

## Roadmap

This release is the boilerplate. The direction from here:

**Root cause analysis reports.** The agent already records observations,
hypotheses, actions and verification results as structured state rather than
chat history. That record is most of an RCA already — the next step is emitting
it as a written report an on-call engineer can hand to a review, instead of
leaving it inside the run.

**Integration with external monitoring and alerting.** Today the agent is
started by hand from the CLI and discovers problems by looking. It should be
triggered by the alert that fired — Prometheus, Grafana, PagerDuty, OpsGenie —
and pull the surrounding signals into its investigation rather than starting
from a bare cluster query.

**An experience brain.** The agent should learn from past incidents instead of
investigating an identical failure from scratch every time. Verified fixes and
failed attempts both get recorded against a failure signature, so a repeat
incident is recognised before the model is called, and the agent gets more
intelligent about a specific environment the longer it runs there.

One constraint on that last item, because it decides whether the feature helps
or hurts: retrieved history should **reorder the investigation, not replace
it**. `ImagePullBackOff` is a typo'd image tag, but it is also a deleted
upstream image, an expired pull secret, or a rate-limited registry. An agent
that pattern-matches straight from symptom to stored fix makes confident wrong
writes to production. Experience should tell the agent what to check first,
never what to do without checking.

## Project layout

```
health.py                       deterministic health check (no LLM)
k8s_agent.py                    state schema, middleware, agent wiring, prompt
tools/
  kubectl.py                    read-only kubectl, verb allowlist
  events.py                     cluster events
  observations.py               ─┐
  hypothesis.py                  │ structured investigation record
  actions.py                     │ (LangGraph Command state writers)
  verification.py               ─┘
  restart_deployment.py         mutating, attempt-capped
  edit_deployment.py            mutating, attempt-capped
```
