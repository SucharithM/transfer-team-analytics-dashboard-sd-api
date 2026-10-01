# Security

Do not put credentials, live records, generated reports, browser traces, or student/staff identifiers in public issues.

The bundled fixture and roster are synthetic. Configure live endpoints and staff names only in ignored local configuration. Browser authentication uses a fresh context and captures credentials only for the configured HTTPS endpoint. All live API modes reject redirects and credential echoes. Only configure an endpoint you are authorized to use.

All generated HTML, CSV, Excel, and SQLite files can contain sensitive source data. Keep them private. Protect the selected output directory and retain reports only as long as needed. Do not enable browser/network tracing with live authentication.

Before publishing:

```bash
python tools/check_publication.py --working-tree
python -m pytest -q
git status --short
git diff --cached --stat
```

The local checker supplements, but does not replace, a maintained secret scanner and current dependency advisory checks. Its output never includes matched credential values.
