# Security

Context Gardener processes tool responses that may contain sensitive data. It applies best-effort redaction before writing compressed artifacts, but it is not a secret manager or a complete data-loss-prevention system.

Report vulnerabilities privately through GitHub Security Advisories for this repository. Do not include live credentials, private transcripts, or confidential tool outputs in an issue.

Runtime artifacts live in Codex's plugin data directory. Users control that directory and can remove it to delete stored observations.
