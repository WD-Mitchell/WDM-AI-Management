# Contributing

Thanks for your interest in WDM AI Management. This project is a local web UI and CLI for managing AI assistant configuration from a file-backed source of truth.

This guide covers local development, validation, packaging checks, and contribution expectations.

## Development Setup

Clone the repository:

```bash
git clone https://github.com/WD-Mitchell/WDM-AI-Management
cd WDM-AI-Management
```

Bootstrap local defaults:

```bash
bin/wdm-ai bootstrap
```

Run the web UI from source:

```bash
bin/wdm-ai --reload
```

Open without launching a browser:

```bash
bin/wdm-ai --no-open
```

Use a temporary source root for testing:

```bash
AI_MANAGEMENT_HOME=/tmp/wdm-test bin/wdm-ai bootstrap
AI_MANAGEMENT_HOME=/tmp/wdm-test bin/wdm-ai --no-open
```

## Project Layout

| Path | Purpose |
| --- | --- |
| `ai_management/` | Python runtime for the CLI and web UI |
| `bin/wdm-ai` | Public command entry point |
| `harnesses/core/` | Bundled harness definitions |
| `templates/core/` | Bundled editor templates |
| `skills/core/AI-Management/` | The management skill installed into harnesses |
| `Formula/` | Homebrew formula source |
| `.github/workflows/` | Release automation |

The repository intentionally excludes local user content libraries from package publishing and git tracking:

- `agents/core`
- most `skills/core` entries
- `mcp/core`
- `rules/core`
- `workflows/core`
- `hooks/core`
- `groups`

Those belong in each user's `~/.wdm` source root or in a separate shared content repository.

## Validation

Run Python syntax checks:

```bash
python3 -m py_compile ai_management/*.py
```

Validate `package.json`:

```bash
python3 -m json.tool package.json >/dev/null
```

Validate workflow YAML:

```bash
python3 - <<'PY'
import pathlib
import yaml

for path in pathlib.Path(".github/workflows").glob("*.yml"):
    yaml.safe_load(path.read_text())
print("workflow yaml ok")
PY
```

Check npm package contents:

```bash
npm_config_cache=/tmp/wdm-npm-cache npm pack --dry-run
```

The package should include `bin/wdm-ai`, not `bin/wdm`.

## Smoke Tests

Run CLI help:

```bash
bin/wdm-ai --help
bin/wdm-ai sync --help
```

Run a dry sync:

```bash
bin/wdm-ai sync --dry-run
```

Run the web UI against a temporary root:

```bash
AI_MANAGEMENT_HOME=/tmp/wdm-test bin/wdm-ai --no-open --port 8770
```

Then open:

```text
http://127.0.0.1:8770
```

## Contribution Areas

Useful contribution areas include:

- Harness definitions and field mappings
- Web UI improvements
- Import and external item handling
- Sync safety and backup behavior
- Documentation
- Tests and smoke checks
- Packaging quality

## Harness Guidelines

Harness files own the mapping contract. Keep tool-specific naming in harness JSON, not hard-coded into the shared editor.

For example, WDM should use canonical fields such as:

```yaml
reasoning: high
mcp_servers:
  - github
```

The harness should map those to tool-specific names:

```json
{
  "field_mappings": {
    "agents": {
      "reasoning": "model_reasoning_effort",
      "mcp_servers": "mcp_servers"
    }
  }
}
```

When adding or changing a harness:

- Add or update `harnesses/core/<name>.json`.
- Keep schemas as narrow as the target tool allows.
- Prefer canonical WDM fields in forms.
- Add `field_mappings` for naming differences.
- Use specialized renderers only when a target format requires it.
- Verify generated output with `bin/wdm-ai sync --dry-run`.

## Documentation Guidelines

Use `wdm-ai` in public documentation and examples.

Avoid documenting `wdm ai` as a public command. Older source checkouts may have compatibility wrappers, but the published command is `wdm-ai`.

Keep the README focused on users. Put contributor setup, validation, and packaging notes in this file.
