"""Smoke-test an installed `simplymz-mcp` over stdio (used by the release workflow).

    python scripts/smoke_installed.py [path/to/simplymz-mcp] [file.mzML]
Exit 0 when initialize and server_info succeed and only JSON-RPC appears on stdout.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile


def main() -> int:
    exe = sys.argv[1] if len(sys.argv) > 1 else shutil.which("simplymz-mcp")
    mzml = sys.argv[2] if len(sys.argv) > 2 else None
    if not exe:
        print("simplymz-mcp executable not found", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as root:
        if mzml:
            shutil.copy(mzml, root)
        p = subprocess.Popen(
            [exe, "--root", root],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        assert p.stdin and p.stdout

        def send(m: dict) -> None:
            p.stdin.write(json.dumps(m) + "\n")
            p.stdin.flush()

        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "smoke", "version": "0"},
                },
            }
        )
        init = json.loads(p.stdout.readline())
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "server_info", "arguments": {}},
            }
        )
        info = json.loads(p.stdout.readline())
        loaded = None
        if mzml:
            from pathlib import Path

            send(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "load_run", "arguments": {"path": Path(mzml).name}},
                }
            )
            loaded = json.loads(p.stdout.readline())["result"]["structuredContent"]
        p.stdin.close()
        p.wait(timeout=20)
    env = info["result"]["structuredContent"]
    ok = init["result"]["serverInfo"]["name"] == "simplymz-mcp" and env["status"] == "ok"
    if loaded is not None:
        ok = ok and loaded["status"] == "ok"
        print(f"load_run: {loaded['verdict']}")
    print(f"{'OK' if ok else 'FAIL'}: {env['verdict']} ({len(env['data']['tools'])} tools)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
