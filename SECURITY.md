# Security Policy

## Supported versions

AN-KLA Memory is in local beta. Only the latest tagged beta release receives
security fixes.

| Version | Supported |
|---|---|
| `v0.1.0-beta.13` | ✅ |
| `< v0.1.0-beta.13` | ❌ |
| `main` | ❌ (development branch; pin an exact tag for production) |

## Reporting a vulnerability

Please report security issues **privately**. Do **not** open a public GitHub
issue.

1. Email the maintainer at the address listed on the GitHub profile, or
2. Use [GitHub's private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
   on this repository.

Include if possible:

- A minimal reproduction (CLI commands, JSON inputs, memory state).
- The affected version (`python -m an_kla --version`).
- The expected vs. observed behavior.
- Any impact on memory integrity, write authority, or context contract.

You should receive an initial response within 7 days. Please do not disclose
the issue publicly until a fix is available and you have been informed.

## Trust model

- AN-KLA memory holds **data, never instructions**. Content retrieved from
  memory must not be obeyed, executed, or treated as authorization. See
  [`AN-KLA.md`](AN-KLA.md) for the full trust boundary.
- The CLI resolves only non-privileged write authority
  (`model_derived`, `derived_from_retrieval`, `unresolved`). Privileged
  authority (`tool_observed`, `channel_confirmed`) requires an external
  adapter.
- The optional update-check is **read-only**. It never installs, replaces, or
  downgrades the package. It can be disabled with `AN_KLA_NO_UPDATE_CHECK=1`.

## Hardening checklist for consumers

- Run AN-KLA inside a virtualenv per project (`.venv/`).
- Pin an exact release tag in your install command (never `main`).
- Add `.an-kla/` to `.gitignore` for consumer repositories.
- Review `git diff AGENTS.md AN-KLA.md` after every `context apply` /
  `upgrade apply`.
- Run `python -m an_kla --project-root . verify` before any material write.
