"""M5.T5: README config snippets are valid and their arguments start a working server."""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

import pytest

from simplymz_mcp.core.envelope import is_valid_envelope
from tests.conftest import REPO
from tests.helpers import RawStdioSession

pytestmark = pytest.mark.e2e
README = (REPO / "README.md").read_text()


def test_desktop_and_code_snippets_agree_and_run(tmp_path: Path) -> None:
    block = re.search(r"```json\n(.*?)```", README, re.S)
    assert block
    entry = json.loads(block.group(1))["mcpServers"]["simplymz-mcp"]
    assert entry["command"] == "uvx"
    # Installed from GitHub until the PyPI release: --from git+<repo> simplymz-mcp ...
    assert entry["args"][:2] == [
        "--from",
        "git+https://github.com/yhde-oliveira-falcao/simplymz-mcp",
    ]
    cmd = entry["args"].index("simplymz-mcp")
    code = re.search(r"```bash\n(claude mcp add .*?)\n```", README, re.S)
    assert code
    parts = shlex.split(code.group(1))
    assert parts[:5] == ["claude", "mcp", "add", "--transport", "stdio"]
    assert parts[parts.index("--") + 1 :] == ["uvx", *entry["args"]]
    # Launch the server with exactly the README's arguments (root swapped for a temp dir).
    args = [a if not a.startswith("/path/") else str(tmp_path) for a in entry["args"][cmd + 1 :]]
    s = RawStdioSession(tmp_path, [a for a in args if a not in ("--root", str(tmp_path))])
    try:
        s.initialize()
        res = s.request("tools/call", {"name": "server_info", "arguments": {}})
    finally:
        s.close()
    env = res["result"]["structuredContent"]
    assert is_valid_envelope(env) and env["data"]["root"] == str(tmp_path.resolve())
    assert str(len(env["data"]["tools"])) + " tools" in README
