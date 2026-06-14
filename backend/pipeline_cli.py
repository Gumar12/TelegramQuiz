"""CLI for the DOCX-first parser pipeline."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from backend.parsers.docx_reader import read_docx_to_ir
from backend.parsers.docx_strict import parse_prepared_file
from backend.parsers.google_docx_prepare import prepare_google_docx
from backend.pipeline.clean_quiz import build_clean_quiz
from backend.pipeline.encoding import configure_cli_output_utf8, write_json_utf8, write_text_utf8

PREPARE_STRATEGY = "google-docs-docx-prep"
STRICT_STRATEGY = "docx-strict-template"


def prepare_docx(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    media_dir = out_dir / "media"

    ir = read_docx_to_ir(args.file, media_dir=media_dir)
    result = prepare_google_docx(ir)

    prepared_md = out_dir / "prepared.md"
    prepared_json = out_dir / "prepared.json"
    report_json = out_dir / "report.json"
    write_text_utf8(prepared_md, result.prepared_markdown)
    write_json_utf8(prepared_json, result.to_prepared_json())
    write_json_utf8(report_json, result.to_report())

    has_errors = bool(result.broken_questions) or any(
        issue.severity == "error" for issue in result.issues
    )
    print("Подготовка DOCX завершена.")
    print(f"Вопросов найдено: {result.question_count}")
    print(f"Требует проверки: {'да' if result.requires_review else 'нет'}")
    print(f"prepared.md: {prepared_md}")
    print(f"prepared.json: {prepared_json}")
    print(f"report.json: {report_json}")
    if has_errors:
        print("Найдены блокирующие ошибки подготовки DOCX.", file=sys.stderr)
        return 1
    return 0


def parse_prepared(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    strict_result = parse_prepared_file(args.file)
    artifacts = build_clean_quiz(strict_result, title=args.title)

    clean_json = out_dir / "quiz.clean.json"
    audit_json = out_dir / "quiz.audit.json"
    report_json = out_dir / "report.json"
    artifacts.write(clean_json, audit_json)
    write_json_utf8(report_json, _strict_report(artifacts.audit_json))

    requires_review = bool(artifacts.issues)
    print("Строгий парсинг завершен.")
    print(f"Вопросов найдено: {artifacts.audit_json['question_count']}")
    print(f"Требует проверки: {'да' if requires_review else 'нет'}")
    print(f"quiz.clean.json: {clean_json}")
    print(f"quiz.audit.json: {audit_json}")
    print(f"report.json: {report_json}")
    if artifacts.has_errors:
        print("Найдены блокирующие ошибки strict parsing.", file=sys.stderr)
        return 1
    return 0


def _strict_report(audit_json: dict[str, Any]) -> dict[str, Any]:
    parse_report = audit_json.get("parse_report", {})
    return {
        "source_id": audit_json.get("source_id", ""),
        "parser_strategy": audit_json.get("parser_strategy", STRICT_STRATEGY),
        "question_count": audit_json.get("question_count", 0),
        "requires_review": bool(parse_report.get("error_count") or parse_report.get("warning_count")),
        "error_count": parse_report.get("error_count", 0),
        "warning_count": parse_report.get("warning_count", 0),
        "issues": parse_report.get("issues", []),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DOCX-first Quizbot parser pipeline.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser(
        "prepare-docx",
        help="Prepare Google Docs-exported DOCX into strict prepared artifacts.",
    )
    prepare.add_argument("--file", required=True, help="Source DOCX file")
    prepare.add_argument("--strategy", choices=[PREPARE_STRATEGY], default=PREPARE_STRATEGY)
    prepare.add_argument("--out", required=True, help="Output directory")
    prepare.set_defaults(func=prepare_docx)

    parse = subparsers.add_parser(
        "parse-prepared",
        help="Parse strict prepared.md into clean JSON and audit JSON.",
    )
    parse.add_argument("--file", required=True, help="Prepared markdown file")
    parse.add_argument("--strategy", choices=[STRICT_STRATEGY], default=STRICT_STRATEGY)
    parse.add_argument("--out", required=True, help="Output directory")
    parse.add_argument("--title", default=None, help="Clean quiz title")
    parse.set_defaults(func=parse_prepared)

    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    configure_cli_output_utf8()
    args = parse_args(argv)
    try:
        return int(args.func(args))
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()