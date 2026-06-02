# Hermes Fleet Baseline Templates

This directory contains repo-safe templates for deploying a reliable Hermes fleet operating baseline.

These files are **templates and documentation**, not live host identity files. Runtime truth stays in each Hermes home/profile:

```text
~/.hermes/SOUL.md
~/.hermes/YOU.md
~/.hermes/VERIFY.md
~/.hermes/ROUTING.md
~/.hermes/IDENTITY.md
```

## Recommended use

1. Copy the templates to the target Hermes home or profile home.
2. Fill in `IDENTITY.md` with only stable host/profile facts.
3. Do not include secrets, tokens, private keys, one-time credentials, or volatile incident state.
4. Verify each deployed file with existence, byte count, checksum, first heading, and host/profile overlay readback.
5. For risky fleet changes, roll out canary-first: Hermes01 → Hermes02 → Hermes00.

## File roles

| File | Purpose |
| --- | --- |
| `SOUL.md.template` | Fleet-wide operating posture, reliability rules, verification discipline, and communication style. |
| `YOU.md.template` | User-facing operating preferences and response contract. |
| `VERIFY.md.template` | Evidence hierarchy, truth labels, and completion gates. |
| `ROUTING.md.template` | Fleet task routing, mechanism selection, and rollout policy. |
| `IDENTITY.md.template` | Per-host/profile overlay; fill locally and do not commit live host-specific copies. |

## Git policy

Commit templates and generic docs only. Avoid committing live `IDENTITY.md` files or host-specific overlays into shared branches.

If a checkout also keeps local reference copies at the repo root, keep them untracked or ignored locally; they are operational artifacts, not source code.
