"""Command line interface for agent-run-diff-lab."""

import argparse
import sys
from pathlib import Path
from typing import Iterable, Optional

from .config import apply_list_overrides, load_config
from .diff import compare_runs
from .errors import AgentRunDiffError
from .parser import parse_run_file
from .reporters import render_junit, render_json, render_markdown, render_pr_comment, render_sarif

EXIT_PASS = 0
EXIT_GATE_FAILED = 1
EXIT_USAGE_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-run-diff-lab",
        description="Offline diff and CI gate for AI agent run transcripts.",
    )
    parser.add_argument("baseline", help="Baseline transcript path (.json or .jsonl)")
    parser.add_argument("candidate", help="Candidate transcript path (.json or .jsonl)")
    parser.add_argument("--config", help="JSON config path")
    parser.add_argument("--format", choices=["markdown", "json", "junit", "sarif", "pr-comment"], default="markdown")
    parser.add_argument("--output", "-o", help="Write report to path instead of stdout")
    parser.add_argument("--max-duration-delta-pct", type=float)
    parser.add_argument("--max-cost-delta-pct", type=float)
    parser.add_argument("--max-failures-delta", type=int)
    parser.add_argument("--max-retries-delta", type=int)
    parser.add_argument("--max-risk-score", type=int)
    parser.add_argument("--max-file-changes-delta", type=int)
    parser.add_argument("--allow-new-failed-tools", action="store_true")
    parser.add_argument("--allow-tool-reorder", action="store_true")
    parser.add_argument("--no-compare-outputs", action="store_true")
    parser.add_argument("--no-compare-inputs", action="store_true")
    parser.add_argument("--ignore-tool", action="append", default=[])
    parser.add_argument("--ignore-path", action="append", default=[])
    parser.add_argument("--quiet", action="store_true", help="Only print report path or errors")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        config = _config_from_args(args)
        baseline = parse_run_file(args.baseline)
        candidate = parse_run_file(args.candidate)
        result = compare_runs(baseline, candidate, config)
        report = _render(result, args.format)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(report, encoding="utf-8")
            if not args.quiet:
                print(str(output))
        else:
            print(report, end="")
        return EXIT_PASS if result.passed else EXIT_GATE_FAILED
    except AgentRunDiffError as exc:
        print(f"agent-run-diff-lab: {exc}", file=sys.stderr)
        return EXIT_USAGE_ERROR
    except OSError as exc:
        print(f"agent-run-diff-lab: {exc}", file=sys.stderr)
        return EXIT_USAGE_ERROR


def _config_from_args(args):
    overrides = {
        "max_duration_delta_pct": args.max_duration_delta_pct,
        "max_cost_delta_pct": args.max_cost_delta_pct,
        "max_failures_delta": args.max_failures_delta,
        "max_retries_delta": args.max_retries_delta,
        "max_risk_score": args.max_risk_score,
        "max_file_changes_delta": args.max_file_changes_delta,
        "allow_new_failed_tools": True if args.allow_new_failed_tools else None,
        "allow_tool_reorder": True if args.allow_tool_reorder else None,
        "compare_outputs": False if args.no_compare_outputs else None,
        "compare_inputs": False if args.no_compare_inputs else None,
    }
    config = load_config(args.config, overrides=overrides)
    return apply_list_overrides(config, args.ignore_tool, args.ignore_path)


def _render(result, fmt: str) -> str:
    if fmt == "json":
        return render_json(result)
    if fmt == "junit":
        return render_junit(result)
    if fmt == "sarif":
        return render_sarif(result)
    if fmt == "pr-comment":
        return render_pr_comment(result)
    return render_markdown(result)


if __name__ == "__main__":
    raise SystemExit(main())
