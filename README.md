# mcp-remote-py

Minimal **MCP STDIO ↔ Remote SSE** proxy in Python.

This project is a deliberately small reimplementation of the core idea from `mcp-remote`:

- Local side: MCP over **STDIO** (newline-delimited JSON / JSONL)
- Remote side: MCP over **SSE** (receives JSON-RPC via SSE `message` events)
- Send path: remote provides an `endpoint` SSE event; subsequent client→server messages are sent via **HTTP POST** to that endpoint.

## What this is / isn’t

**Included**
- Bidirectional proxying of MCP JSON-RPC messages
- No stdout contamination (logs go to stderr)
- Optional custom headers (`--header 'Name: value'`)

**Intentionally excluded** (keep it simple)
- OAuth / authorization flows
- Token storage / refresh
- Multi-instance coordination / lockfiles
- HTTP↔SSE fallback strategies

## Install

### Option A — “Global” install with `uv` (recommended)

Installs a user-scoped executable into `~/.local/bin` (macOS/Linux) or `%USERPROFILE%\.local\bin` (Windows).

```bash
chmod +x ./*.sh
./install-global-uv.sh
```

Windows (CMD):

```bat
install-global-uv.cmd
```

Uninstall:

```bash
./uninstall-global-uv.sh
```

Windows (CMD):

```bat
uninstall-global-uv.cmd
```

If your shell can’t find the command, ensure `~/.local/bin` is on your `PATH`.

### Option B — Dev install (editable)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

## Run

```bash
mcp-remote-py http://127.0.0.1:8080/mcp/sse
```

Custom headers:

```bash
mcp-remote-py http://127.0.0.1:8080/mcp/sse \
	--header 'Authorization: Bearer TOKEN'
```

## MCP client configs (copy/paste)

### Codex (`~/.codex/config.toml`)

Codex expects TOML like this:

```toml
[mcp_servers.ida-remote]
command = "/Users/<you>/.local/bin/mcp-remote-py"
args = ["http://127.0.0.1:8080/mcp/sse"]
```

If you installed via `uv` into `~/.local/bin`, `command` is typically:

```toml
command = "/Users/<you>/.local/bin/mcp-remote-py"
```

### Claude Desktop (`claude_desktop_config.json`)

```json
{
	"mcpServers": {
		"ida-remote": {
			"command": "mcp-remote-py",
			"args": ["http://127.0.0.1:8080/mcp/sse"]
		}
	}
}
```

### Cursor (`~/.cursor/mcp.json`)

```json
{
	"mcpServers": {
		"ida-remote": {
			"command": "mcp-remote-py",
			"args": ["http://127.0.0.1:8080/mcp/sse"]
		}
	}
}
```

### Windsurf (`~/.codeium/windsurf/mcp_config.json`)

```json
{
	"mcpServers": {
		"ida-remote": {
			"command": "mcp-remote-py",
			"args": ["http://127.0.0.1:8080/mcp/sse"]
		}
	}
}
```

## Troubleshooting

- **Nothing works / random parse errors:** ensure the remote SSE server emits JSON-RPC only on the default `message` event. Non-protocol events are ignored.
- **Don’t see the command:** add `~/.local/bin` to `PATH` (macOS zsh: `~/.zprofile` is a good default).
- **Logs:** all logs go to stderr by design; stdout is reserved for MCP protocol.
