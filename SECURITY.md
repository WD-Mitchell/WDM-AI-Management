# Security Policy

## Supported Versions

Security fixes are applied to the latest released version of WDM AI Management.
Please update before reporting issues that may already be fixed.

## Reporting a Vulnerability

Do not open a public issue for a suspected vulnerability.

Report security issues using GitHub private vulnerability reporting for this
repository. If that is unavailable, contact the maintainers privately and
include:

- Affected version or commit
- Impacted command, workflow, or file path
- Reproduction steps
- Expected impact and any known workaround

We aim to acknowledge reports within 7 days and provide a remediation plan once
the issue is understood.

## Scope

In scope:

- Local file writes performed by `wdm-ai`
- Sync, bootstrap, pull, import, and backup/restore behavior
- GitHub Actions publishing and release automation
- Source-of-truth content handling under `~/.wdm`

Out of scope:

- Vulnerabilities in third-party harnesses
- User-authored agents, skills, MCP configs, hooks, or workflows
- Social engineering, spam, or denial-of-service reports without a concrete
  product security impact
