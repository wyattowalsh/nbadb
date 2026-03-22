# Security Policy

## Scope

nbadb is an open-data ETL pipeline that processes publicly available NBA statistics. It does not handle user authentication, store personally identifiable information, or expose network-facing services.

The agent query path includes a `ReadOnlyGuard` (SQL comment stripping, Unicode NFKC normalization, keyword blocking, automatic LIMIT wrapping) and runs with `enable_external_access = false`.

## Supported Versions

Only the latest release on the `main` branch is supported. Security patches will not be backported to older tags.

| Version | Supported |
| ------- | --------- |
| latest  | Yes       |
| < latest | No       |

## Reporting a Vulnerability

If you discover a security issue, please report it responsibly:

**Email:** wyattowalsh@gmail.com

**What to include:**
- Description of the vulnerability
- Steps to reproduce
- Potential impact assessment

**What qualifies:**
- SQL injection in the agent query path (bypassing `ReadOnlyGuard`)
- Dependency vulnerabilities affecting nbadb
- Secrets or credentials accidentally committed
- Issues in proxy credential handling (proxywhirl configuration)

**What is out of scope:**
- Vulnerabilities in [nba_api](https://github.com/swar/nba_api) itself (report upstream)
- NBA.com rate limiting or terms of service concerns
- Data accuracy of NBA statistics
- Denial of service against the local pipeline

## Response Timeline

- **Acknowledgment:** Within 72 hours
- **Resolution target:** Within 30 days

## Disclosure Policy

We follow coordinated disclosure. Please do not publish details until a fix is released or 90 days have passed from the initial report, whichever comes first.
