# Security

Do not put credentials, live records, generated reports, browser traces, or student/staff identifiers in public issues.

The bundled fixture and roster are synthetic. Configure live endpoints and staff names only in ignored local configuration. Browser authentication uses a fresh context and captures credentials only for the configured HTTPS endpoint. All live API modes reject redirects and credential echoes. Only configure an endpoint you are authorized to use.

All generated HTML, CSV, Excel, and SQLite files can contain sensitive source data. Keep them private. Protect the selected output directory and retain reports only as long as needed. Do not enable browser/network tracing with live authentication.

The desktop **Send Error Logs** action opens a read-only technical diagnostic
preview. **Copy Logs** copies that exact report for manual sharing; it does not
upload or email anything. Events stay in application memory for the current
session, with at most ten affected attempts and 256 events per attempt. Exported
reports are limited to 64 KiB. Closing the application releases its diagnostics;
text explicitly copied to the clipboard remains under the operating system's
normal clipboard behavior.

Diagnostics accept only a fixed catalog of event codes and validated technical
fields: application/code identity, OS/runtime/browser versions, timestamps,
stage outcomes, approved error categories, fixed browser lifecycle events,
allowlisted closure reasons and sign-in/cleanup phases, and numeric HTTP/system/process error
codes. They exclude credentials, cookies, headers, tenant URLs, workflow/staff
names, records and record counts, user/host names, paths, configuration contents,
environment dumps, screenshots, raw exceptions, and tracebacks. Unknown fields
are rejected rather than scrubbed with secret-pattern matching. Worker events
are independently validated before sending and after receipt. Invalid worker
diagnostic messages abort the worker exchange; only a fixed transport-failure
event is recorded, and the rejected contents never enter a report.

Do not add generic exception logging, request/response dumping, or browser/network
tracing to this support feature. The code fingerprint hashes only an explicit
list of application source files, excluding runtime settings and data. Its small
build manifest is an executable asset, not a runtime log.

Before publishing:

```bash
python tools/check_publication.py --working-tree
python -m pytest -q
git status --short
git diff --cached --stat
```

The local checker supplements, but does not replace, a maintained secret scanner and current dependency advisory checks. Its output never includes matched credential values.
