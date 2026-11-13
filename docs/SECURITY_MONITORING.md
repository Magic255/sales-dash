# Security monitoring

SALES DASH runs automated security checks in GitHub Actions:

- `pip-audit` checks the complete Python development dependency set, including transitive packages, on pushes, pull requests, and weekly.
- CodeQL scans the Python backend and JavaScript frontend on pushes, pull requests, and weekly.
- Dependabot checks Python packages and GitHub Actions dependencies weekly and can open update pull requests.

## Repository settings to verify

Workflow files cannot turn on every repository-level security feature. In GitHub, open **Settings → Code security and analysis** and verify that these are enabled where available:

1. Dependabot alerts.
2. Dependabot security updates.
3. Secret scanning and push protection.
4. Code scanning alerts (the CodeQL workflow uploads analysis results).

Do not assume an unavailable alert list means there are no alerts. Review the repository's **Security** tab after the first scheduled CodeQL run.

## Handling findings

- Treat a failing dependency audit as a release blocker until the vulnerable dependency is upgraded or a documented, reviewed exception is approved.
- Review Dependabot pull requests and CI results before merging.
- Review CodeQL findings for exploitability and tenant/authentication impact; do not dismiss alerts solely to make the dashboard green.
- Rotate any credential that may have been committed, even if the file is later removed.
