# CLAUDE.md

Project guidance for Claude Code working in this repo.

## Hard rules — customer confidentiality

These are absolute. They apply to **all** committed files: source, comments,
tests, docs, YAML, commit messages, and release notes.

- **Never** write the customer's company name anywhere.
- **Never** write customer personnel names anywhere.
- **Never** write customer cluster names, hostnames, project names, IP
  addresses, or other environment-identifying details anywhere.

When a fact from the customer's environment or a real report is useful (e.g. a
threshold learned from production), state it **generically** — "a production
cluster", "the customer's environment", "a real report" — with the numbers but
none of the identifying labels.

If you need to reference customer specifics while working, keep them in the
session only; do not persist them to tracked files. Local-only files
(`CLAUDE.md`, `om_config.md`, `docs/`, `output/`) are gitignored, but treat the
rules above as applying even there for names — prefer generic phrasing by default.
