"""MCP server entry point.

stdout is the MCP stdio transport. Nothing in this package may write to stdout:
logging goes to stderr only, and ruff rule T20 bans print().
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import asdict
from typing import Any

from mcp.server.mcpserver import MCPServer

from simplymz_mcp import __version__
from simplymz_mcp.config import Config
from simplymz_mcp.core import envelope
from simplymz_mcp.core.registry import Registry, ToolSpec
from simplymz_mcp.ledger.ledger import Ledger
from simplymz_mcp.state.cache import RunCache
from simplymz_mcp.state.runs import RunRegistry
from simplymz_mcp.state.store import Store

log = logging.getLogger("simplymz_mcp")


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


class App:
    """Everything a tool needs: config, persistent state, ledger, runs."""

    def __init__(self, config: Config) -> None:
        self.config = config
        cache_dir = config.resolved_cache_dir()
        self.store = Store(cache_dir)
        self.store.expire(config.handle_ttl_days)
        self.ledger = Ledger(self.store)
        self.cache = RunCache(cache_dir, config.cache_max_mb)
        self.runs = RunRegistry(config, self.store, self.cache)
        from simplymz_mcp.jobs.executor import Jobs

        self.jobs = Jobs(self.store)


def make_strict(server: MCPServer, name: str) -> None:
    """Reject unknown tool arguments instead of silently dropping them.

    MCP SDK 2.x ignores extra arguments by default, so a caller passing e.g. ``level=1``
    to assign_confidence would believe it had an effect. Uses the SDK's tool manager
    (private API); tests/e2e/test_strict_args.py fails loudly if the SDK changes.
    """
    from pydantic import ConfigDict

    tool = server._tool_manager.get_tool(name)
    if tool is None:  # pragma: no cover
        raise RuntimeError(f"tool {name} not registered")
    base = tool.fn_metadata.arg_model
    strict = type(
        f"{base.__name__}Strict",
        (base,),
        {"model_config": ConfigDict(arbitrary_types_allowed=True, extra="forbid")},
    )
    tool.fn_metadata.arg_model = strict
    tool.parameters = {**tool.parameters, "additionalProperties": False}


def build_server(config: Config) -> tuple[MCPServer, Registry]:
    server: MCPServer = MCPServer(
        name="simplymz-mcp",
        version=__version__,
        instructions=(
            "SimplyMZ analyses LC-MS/GC-MS runs (mzML). Tools compute; you plan and "
            "explain. Cite tool results, respect `limits`, and treat "
            "`insufficient_evidence` as a valid answer."
        ),
        log_level="WARNING",
    )
    app = App(config)
    registry = Registry(ledger=app.ledger)
    server.app = app  # type: ignore[attr-defined]  # exposed for tests

    def server_info() -> dict[str, Any]:
        """Report server version, the allowed data root, safety limits and enabled extras."""
        return envelope.ok(
            f"SimplyMZ {__version__} is running with data root {config.root}.",
            {
                "version": __version__,
                "root": str(config.root),
                "limits": asdict(config.limits),
                "extras": list(config.extras),
                "tools": registry.names(),
            },
            limits=["Only files under the data root can be read."],
            next_steps=["load_run(path='<file under the data root>')"],
        )

    spec = ToolSpec(
        name="server_info",
        description=server_info.__doc__ or "",
        fn=server_info,
        budget_tokens=600,
        example_input={},
    )
    server.add_tool(registry.register(spec), name=spec.name, description=spec.description)

    from simplymz_mcp.tools import (
        annotation,
        batch,
        chromatogram,
        data,
        features,
        jobs,
        report,
        runs,
    )

    runs.register(server, registry, app)
    chromatogram.register(server, registry, app)
    batch.register(server, registry, app)
    annotation.register(server, registry, app)
    annotation.register_formula_and_confidence(server, registry, app)
    report.register(server, registry, app)
    data.register(server, registry, app)
    jobs.register(server, registry, app)
    features.register(server, registry, app)

    from simplymz_mcp import prompts

    prompts.register(server)
    prompts.register_identify(server)
    for name in registry.names():
        make_strict(server, name)
    return server, registry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="simplymz-mcp",
        description="SimplyMZ MCP server (stdio). Point it at a folder of mzML files.",
    )
    parser.add_argument("--root", help="Data folder the server may read (or SIMPLYMZ_ROOT).")
    parser.add_argument("--cache-dir", help="State/cache folder (default <root>/.simplymz).")
    parser.add_argument("--log-level", default="INFO", help="stderr log level (default INFO).")
    parser.add_argument("--version", action="version", version=f"simplymz-mcp {__version__}")
    args = parser.parse_args(argv)

    configure_logging(args.log_level)
    config = Config.from_args(args.root, args.cache_dir)
    if not config.root.is_dir():
        log.error("data root %s is not a directory", config.root)
        return 2
    server, _ = build_server(config)
    log.info("starting simplymz-mcp %s, root=%s", __version__, config.root)
    server.run("stdio")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
