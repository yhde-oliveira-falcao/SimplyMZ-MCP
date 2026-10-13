"""export_report (plan M5.T1)."""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING, Any, Literal

from simplymz_mcp.core import envelope
from simplymz_mcp.core.errors import ErrorCode, SimplyMZError
from simplymz_mcp.core.registry import Registry, ToolSpec
from simplymz_mcp.report.builder import ReportError, Section, build, to_html

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from simplymz_mcp.server import App

REPORT_DIR = "simplymz_reports"
SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def register(server: MCPServer, registry: Registry, app: App) -> dict[str, Any]:
    def export_report(
        title: str,
        sections: list[dict[str, str]],
        filename: str,
        evidence: list[str] | None = None,
        output_format: Literal["md", "html", "both"] = "both",
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Write a Markdown/HTML report. Put numbers in {ev:<id>:<path>} slots (e.g.
        {ev:01J...:data.metrics.rt_drift_min.value}); any other number in the text must
        appear in a referenced ledger entry or the report is rejected (number guard).
        Limits of every referenced result are carried into the report automatically."""
        if not SLUG.match(filename):
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                "Bad filename.",
                "Use 1-64 letters, digits, '_' or '-' (no extension, no folders).",
            )
        if not sections or any(not {"heading", "body"} <= s.keys() for s in sections):
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                "Each section needs 'heading' and 'body'.",
                'Example: [{"heading": "QC", "body": "..."}]',
            )
        try:
            rep = build(
                title,
                [Section(s["heading"], s["body"]) for s in sections],
                evidence or [],
                app.ledger.get,
            )
        except ReportError as exc:
            raise SimplyMZError(ErrorCode.INVALID_ARGUMENT, exc.message, exc.hint) from exc
        out_dir = app.config.root.resolve() / REPORT_DIR
        out_dir.mkdir(exist_ok=True)
        paths = []
        targets = {"md": [".md"], "html": [".html"], "both": [".md", ".html"]}[output_format]
        for ext in targets:
            p = out_dir / f"{filename}{ext}"
            if p.exists() and not overwrite:
                raise SimplyMZError(
                    ErrorCode.INVALID_ARGUMENT,
                    f"{p.name} already exists.",
                    "Pick another filename or pass overwrite=true.",
                )
        for ext in targets:
            p = out_dir / f"{filename}{ext}"
            p.write_text(
                rep.markdown if ext == ".md" else to_html(rep.markdown, title), encoding="utf-8"
            )
            paths.append(f"{REPORT_DIR}/{p.name}")
        digest = hashlib.sha256(rep.markdown.encode()).hexdigest()
        env = envelope.ok(
            f"Report written to {', '.join(paths)} ({rep.slots_filled} slot(s) filled from "
            f"the ledger, {rep.numbers_checked} narrative number(s) verified).",
            {
                "paths": paths,
                "markdown_sha256": digest,
                "referenced": rep.referenced,
                "slots_filled": rep.slots_filled,
                "numbers_checked": rep.numbers_checked,
                "n_disclosures": len(rep.disclosures),
            },
            limits=[
                "The report proves where each number came from; it does not re-check the "
                "science. Its limits section repeats every referenced result's limits."
            ],
        )
        env["_provenance"] = {"input_hashes": [], "parents": rep.referenced}
        return env

    spec = ToolSpec(
        "export_report",
        export_report.__doc__ or "",
        export_report,
        800,
        {
            "title": "Example",
            "filename": "contract_example",
            "sections": [{"heading": "Server", "body": "Version check."}],
            "evidence": ["<ev>"],
            "overwrite": True,
        },
    )
    guarded = registry.register(spec)
    server.add_tool(guarded, name=spec.name, description=spec.description)
    return {"export_report": guarded}
