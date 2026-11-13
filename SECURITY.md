# Security

Keep credentials, live records, reports, browser traces, and student/staff
identifiers out of public issues and releases. Configure authorized HTTPS
endpoints and staff names only in ignored local settings; bundled examples must
stay synthetic.

Browser authentication uses a fresh context and captures credentials only for
the configured endpoint. Live API modes reject redirects and credential echoes.
Do not enable browser/network tracing with live authentication.

HTML, CSV, Excel, and SQLite exports can contain sensitive source data, including
student names and institutions. Protect output folders and retain reports only
as long as needed.

HTML reports use a Content Security Policy with hashed embedded scripts and
blocked network connections, external scripts, objects, base URL changes, and
form submissions. Inline styles and data/blob images support charts and printing.
Regenerate older reports to apply policy changes.

## Diagnostics

**Send Error Logs** opens a read-only preview; **Copy Logs** copies it for manual
sharing. It does not upload or email anything. Diagnostics stay in session memory,
limited to ten affected attempts, 256 events per attempt, and 64 KiB per report.
Copied text remains in the operating system clipboard after the app closes.

Accept only catalogued events and validated technical fields: application/code
identity, runtime/browser versions, timestamps, stage outcomes, approved error
categories, lifecycle events, and numeric HTTP/system/process codes. Exclude
credentials, cookies, headers, tenant URLs, workflow/staff names, records and
counts, user/host names, paths, settings, environment dumps, screenshots, raw
exceptions, and tracebacks. Reject unknown fields and validate worker diagnostics
at both ends; invalid messages abort the exchange without retaining their content.

Do not add generic exception logging, request/response dumps, or tracing.
Limit code fingerprints to application source, excluding settings and data.

## Before publishing

Review the staged diff and run:

```bash
python tools/check_publication.py --working-tree
python -m pytest -q
git status --short
git diff --cached --stat
```

The checker scans staged, tracked, eligible untracked files, and reachable Git
history, including commit messages and annotated tags. Use `--all-objects` to
include unreachable objects. Matched credential values are never printed.
The checker supplements a maintained secret scanner and current dependency
advisory checks.
