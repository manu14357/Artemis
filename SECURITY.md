# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| `main` branch | ✅ |
| Tagged releases | ✅ |
| Older commits | ❌ |

## Reporting a vulnerability

**Do NOT open a public GitHub issue for security vulnerabilities.**

Email: **security@artemis-project.dev** (monitored by maintainers)

Include in your report:
- Description of the vulnerability
- Steps to reproduce
- Impact assessment (CIA triad)
- Suggested fix if available

You will receive an acknowledgement within **72 hours** and a severity assessment
within **7 days**.

## Disclosure timeline

| Day | Milestone |
|---|---|
| 0 | Report received, acknowledged |
| 7 | Severity confirmed, fix scope agreed |
| 30 | Fix developed and internally validated |
| 45 | Fix released in a tagged version |
| 60 | Public disclosure (CVE assigned if applicable) |

Coordinated disclosure may be extended to 90 days for complex supply-chain issues.

## Scope

In scope:
- Authentication bypass in the REST API or WebSocket
- MQTT broker access control issues
- Remote code execution via crafted MQTT payloads
- Secrets exposed in config files or Docker images
- Dependency vulnerabilities with a working exploit

Out of scope:
- Physical hardware security of deployed nodes
- Issues in third-party tools (Mosquitto, Acconeer SDK) — report upstream
- Denial-of-service via resource exhaustion without evidence of remote triggering

## Security hall of fame

Responsible disclosures will be credited here (with reporter's permission).

---

*This policy follows the [GitHub Coordinated Disclosure framework](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/about-coordinated-disclosure-of-security-vulnerabilities).*
