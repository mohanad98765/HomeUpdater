# Security Policy — سياسة الأمان

HomeUpdater (محدِّث المنزل) is a security-sensitive tool: it runs with elevated
privileges, is reachable over the local network, and handles device credentials
(SSH / WinRM / Home Assistant) and an Anthropic API key. We take vulnerability
reports seriously.

## Supported Versions — الإصدارات المدعومة

Only the **latest** release receives security fixes. Always run the newest
signed installer from the [Releases page](https://github.com/mohanad98765/HomeUpdater/releases/latest).

| Version | Supported |
|---------|-----------|
| Latest release | ✅ |
| Older releases | ❌ |

## Reporting a Vulnerability — الإبلاغ عن ثغرة

**Please do NOT open a public GitHub issue for a security vulnerability.**
لا تفتح مشكلة عامة للثغرات الأمنية.

Report privately by either:

- **GitHub Security Advisories** — the preferred channel:
  [Report a vulnerability](https://github.com/mohanad98765/HomeUpdater/security/advisories/new)
  (Repository → **Security** → **Advisories** → *Report a vulnerability*).
- **Email:** `mohanad98765` on GitHub / the contact in the repository profile,
  with the subject `SECURITY: HomeUpdater`.

Please include:
- affected version (from Settings → About, or `GET /api/system/version`);
- a clear description and the impact;
- reproduction steps or a proof-of-concept;
- any suggested remediation.

## What to Expect — ما تتوقّعه

- **Acknowledgement:** within **72 hours**.
- **Triage & severity assessment:** within **7 days**.
- **Fix target:** critical issues in a hotfix release as soon as validated;
  others in the next scheduled release.
- **Credit:** with your permission, we will credit you in the release notes.

## Scope — النطاق

In scope: the backend API and its auth/session model, credential storage
(encryption at rest), the local-network exposure surface, the update-execution
paths (winget / WUA / WinRM / SSH / adb), and the installer/signing pipeline.

Out of scope: vulnerabilities in third-party dependencies already tracked
upstream (report those to the upstream project; we consume their fixes via
dependency updates), and issues requiring pre-existing administrative access to
the user's own machine.

## Safe Harbor

Good-faith security research conducted in accordance with this policy — against
your own installation, without harming others' data or availability — will not
be pursued or reported by us.
