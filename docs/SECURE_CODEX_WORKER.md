# Secure Codex Worker

This note captures the safer production design for the Codex navigability worker.

## Short answer

- Do not rely on prompt text to stop exfiltration.
- Do not rely on rotating Azure OpenAI resource keys per audit run.
- Do route worker egress through a controlled path.
- Do isolate the worker from unrelated secrets.

## Why per-run Azure OpenAI keys are the wrong primitive

Azure AI Services exposes two resource keys (`key1` and `key2`) at the account level and supports listing/regenerating them. That is good for rotation, but not for minting an independent one-time key per job.

Implications:

- Rotating a key for one job can break other concurrent jobs.
- A "create key, hand to worker, destroy key" flow is not natively supported the way a true per-session credential system would be.
- For code we control directly, Microsoft Entra ID / managed identity is the preferred answer.

## What to do instead

There are two practical designs.

### Preferred for code we own directly

Use Microsoft Entra ID / managed identity for Azure OpenAI calls.

This works well for the regular backend LLM client because we control that code path.

Benefits:

- no long-lived API key in the worker environment
- RBAC instead of shared secret distribution
- short-lived bearer tokens instead of static credentials

### Preferred for the Codex CLI worker

Treat the worker as untrusted with respect to secret handling and put an internal gateway in front of Azure OpenAI.

Pattern:

1. Worker authenticates to an internal gateway using a short-lived internal credential.
2. Gateway validates the worker and job scope.
3. Gateway calls Azure OpenAI using managed identity or a tightly scoped upstream secret.
4. Worker never sees the real Azure OpenAI credential.

This does **not** stop prompt injection from abusing model access, but it prevents the worker from directly stealing the upstream Azure OpenAI secret.

## Egress control

Because the product audits arbitrary websites, the worker needs outbound access to:

- the submitted site being audited
- Azure OpenAI

It should not have arbitrary internet egress beyond that.

For Azure Container Apps, the practical pattern is:

1. Run the worker in a workload profiles environment.
2. Attach the environment to a VNet.
3. Use a user-defined route (UDR) to force outbound through Azure Firewall or another egress appliance.
4. Allow only:
   - Azure OpenAI endpoint(s)
   - the internal gateway, if used
   - DNS and required platform dependencies
   - the submitted target host for the active job

## Important design constraint

Static firewall allowlists do not fit a crawler that must visit arbitrary customer-submitted domains.

That means one of these has to own destination policy:

- a programmable egress proxy/gateway that checks the current job's allowed target host
- automation that updates firewall rules per job

The proxy/gateway approach is usually simpler and safer than mutating firewall rules for each run.

## Recommended rollout for OpenIngress

1. Keep the Codex worker on `workspace-write`, never `danger-full-access`.
2. Move the worker into a dedicated Azure Container Apps workload-profile environment.
3. Put all outbound egress behind UDR + Azure Firewall.
4. Add an internal audit gateway for model access.
5. Give the worker no secrets except a short-lived internal credential for the gateway.
6. Remove SMTP, Supabase service-role, Stripe, and other unrelated secrets from the worker environment.
7. Add output filtering so stored audit artifacts cannot contain obvious credential dumps.

## Non-goals

This architecture reduces blast radius. It does not make hostile page instructions safe by themselves.

If the worker can still read sensitive local data or reach arbitrary destinations, prompt injection remains a serious risk.
