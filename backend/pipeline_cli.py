"""CLI for the DOCX-first parser pipeline."""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import shlex
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from backend.parsers.docx_reader import read_docx_to_ir
from backend.parsers.docx_strict import parse_prepared_file
from backend.parsers.google_docx_prepare import prepare_google_docx
from backend.pipeline.clean_quiz import build_clean_quiz
from backend.pipeline.encoding import configure_cli_output_utf8, write_json_utf8, write_text_utf8
from backend.pipeline.review import (
    GroupReviewDecision,
    ReviewDecision,
    ReviewDecisionError,
    build_review_artifact,
    expand_group_decision,
    make_review_decision,
    parse_review_artifact,
    resolve_upload_gate,
)
from backend.pipeline.validation import (
    ValidationIssue,
    ValidationReport,
    load_clean_quiz_file,
    validate_clean_quiz_file,
)

PREPARE_STRATEGY = "google-docs-docx-prep"
STRICT_STRATEGY = "docx-strict-template"
DEFAULT_UPLOAD_SPEED = "normal"


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


def validate_quiz(args: argparse.Namespace) -> int:
    quiz_path = Path(args.file)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    report = validate_clean_quiz_file(quiz_path)
    report_path = out_dir / "validation-report.json"
    write_json_utf8(report_path, report.to_dict())

    print("Валидация clean JSON завершена.")
    print(f"Вопросов найдено: {report.question_count}")
    print(f"Блокирующих ошибок: {len(report.hard_errors)}")
    print(f"Предупреждений: {len(report.warnings)}")
    print(f"validation-report.json: {report_path}")

    if args.interactive:
        return _interactive_validate_review(quiz_path, out_dir, report)

    if report.has_hard_errors:
        print("Найдены нерешенные блокирующие ошибки validation.", file=sys.stderr)
        return 1
    if report.warnings:
        print("Есть предупреждения. Для review запусти:")
        print(_validate_command(quiz_path, out_dir, interactive=True))
        return 0
    print("Validation пройден без предупреждений.")
    print("Следующая команда:")
    print(_upload_command(quiz_path, title=_safe_quiz_title(quiz_path)))
    return 0


def upload_quiz(args: argparse.Namespace) -> int:
    quiz_path = Path(args.file)
    service = _make_upload_service()
    store = _store_from_service(service)
    replace_active = _startup_reconcile(store, confirmed=bool(args.yes))
    if replace_active is None:
        return 1

    try:
        run = _run_maybe_async(
            service.start_upload(
                quiz_file=quiz_path,
                quiz_name=args.name,
                speed=args.speed,
                start_from=args.start_from,
                account_profile_id=args.profile,
                replace_active=replace_active,
            )
        )
    except _upload_gate_error_type() as exc:
        print("Upload заблокирован: нет свежих review decisions для текущего JSON.")
        reason = getattr(getattr(exc, "gate", None), "reason", None)
        if reason:
            print(f"Причина: {reason}")
        print("Сначала запусти:")
        print(_validate_command(quiz_path, quiz_path.parent, interactive=True))
        return 1

    _print_run_summary(run, title="Upload завершен или поставлен на паузу.")
    return 0


def probe_speed(args: argparse.Namespace) -> int:
    quiz_path = Path(args.file)
    service = _make_speed_probe_service()
    store = _store_from_service(service)
    replace_active = _startup_reconcile(
        store,
        confirmed=bool(args.yes),
        new_run_label="probe-speed",
    )
    if replace_active is None:
        return 1

    normalized_profile = (args.profile or "").strip() or None
    if normalized_profile is None and not args.confirm_active:
        print(
            "Speed probe заблокирован: без --profile он запустился бы на активном "
            "(боевом) account profile и сжёг бы его лимиты.",
            file=sys.stderr,
        )
        print(
            "Укажи конкретный профиль через --profile <id>, либо явно подтверди "
            "запуск на активном профиле через --confirm-active."
        )
        return 1

    probe_kwargs: dict[str, Any] = {
        "quiz_file": quiz_path,
        "question_count": args.questions,
        "policy": args.policy,
        "account_profile_id": normalized_profile,
        "replace_active": replace_active,
    }
    if normalized_profile is None:
        probe_kwargs["confirm_active"] = True
    run = _run_maybe_async(service.start_probe(**probe_kwargs))

    _print_run_summary(run, title="Speed probe завершен или поставлен на паузу.")
    report_path = service.report_path(run.probe_id)
    print(f"Отчет probe: {report_path}")
    return 0


def status_run(args: argparse.Namespace) -> int:
    store = _make_run_store()
    snapshot = store.safe_status_snapshot(args.run_id)
    _print_run_summary(snapshot, title="Статус запуска.")
    return 0


def resume_run(args: argparse.Namespace) -> int:
    service = _make_upload_service()
    store = _store_from_service(service)
    if _is_speed_probe_run(store, args.run_id):
        probe_service = _make_speed_probe_service()
        run = _run_maybe_async(probe_service.resume_probe_run(args.run_id))
        _print_run_summary(run, title="Speed probe resume завершен или поставлен на паузу.")
        return 0
    run = _run_maybe_async(service.resume_upload_run(args.run_id))
    _print_run_summary(run, title="Resume завершен или поставлен на паузу.")
    return 0


def pause_run(args: argparse.Namespace) -> int:
    store = _make_run_store()
    run_id = store.resolve_run_id(args.run_id)
    run = store.update_status(
        run_id,
        "paused",
        last_error={
            "code": "paused_by_cli",
            "message": "Пользователь поставил запуск на паузу через CLI.",
        },
    )
    _print_run_summary(run, title="Запуск поставлен на паузу.")
    return 0


def rollback_run(args: argparse.Namespace) -> int:
    service = _make_upload_service()
    try:
        run = _run_maybe_async(
            service.rollback_upload_run(
                args.run_id,
                args.to,
                confirm_rollback=bool(args.yes),
            )
        )
    except _upload_confirmation_error_type() as exc:
        _print_confirmation_details(exc)
        if not _confirm_dangerous_action(
            "Подтверди rollback, чтобы отправить /undo и продолжить с выбранного вопроса.",
            yes=bool(args.yes),
        ):
            return 1
        run = _run_maybe_async(
            service.rollback_upload_run(
                args.run_id,
                args.to,
                confirm_rollback=True,
            )
        )

    _print_run_summary(run, title="Rollback выполнен.")
    return 0


def continue_from_run(args: argparse.Namespace) -> int:
    service = _make_upload_service()
    try:
        run = _run_maybe_async(
            service.continue_upload_run_from(
                args.run_id,
                args.question_index,
                confirm_rollback=bool(args.yes),
                confirm_skip_forward=bool(args.yes),
            )
        )
    except _upload_confirmation_error_type() as exc:
        _print_confirmation_details(exc)
        if not _confirm_dangerous_action(
            "Подтверди continue-from, чтобы выполнить rollback или skip-forward.",
            yes=bool(args.yes),
        ):
            return 1
        kwargs = {
            "confirm_rollback": getattr(exc, "action", "") == "rollback",
            "confirm_skip_forward": getattr(exc, "action", "") == "skip_forward",
        }
        run = _run_maybe_async(
            service.continue_upload_run_from(
                args.run_id,
                args.question_index,
                **kwargs,
            )
        )

    _print_run_summary(run, title="Continue-from завершен или поставлен на паузу.")
    return 0


def account_list(args: argparse.Namespace) -> int:
    from backend import accounts

    try:
        profiles = accounts.list_profiles()
    except accounts.AccountProfileError as exc:
        return _print_account_error(exc)

    print("Telegram account profiles:")
    for profile in profiles:
        _print_public_profile(profile)
    return 0


def account_current(args: argparse.Namespace) -> int:
    from backend import accounts

    try:
        profile = accounts.current_profile()
    except accounts.AccountProfileError as exc:
        return _print_account_error(exc)

    print("Текущий Telegram account profile:")
    _print_public_profile(profile)
    return 0


def account_use(args: argparse.Namespace) -> int:
    from backend import accounts

    try:
        if not _account_switch_allowed(args.profile_id):
            return 1
        profile = accounts.use_profile(args.profile_id)
    except accounts.AccountProfileError as exc:
        return _print_account_error(exc)

    print("Активный Telegram account profile изменен:")
    _print_public_profile(profile)
    return 0


def account_enable(args: argparse.Namespace) -> int:
    from backend import accounts

    try:
        profile = accounts.enable_profile(args.profile_id)
    except accounts.AccountProfileError as exc:
        return _print_account_error(exc)

    print("Telegram account profile включен:")
    _print_public_profile(profile)
    return 0


def account_disable(args: argparse.Namespace) -> int:
    from backend import accounts

    try:
        profile = accounts.disable_profile(args.profile_id)
    except accounts.AccountProfileError as exc:
        return _print_account_error(exc)

    print("Telegram account profile выключен:")
    _print_public_profile(profile)
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


def _interactive_validate_review(
    quiz_path: Path,
    out_dir: Path,
    report: ValidationReport,
) -> int:
    review_path = out_dir / "review-decisions.json"
    existing_artifact = _load_existing_review_artifact(review_path)
    if existing_artifact is not None:
        gate = resolve_upload_gate(report, existing_artifact)
        if gate.reason == "review_decisions_stale":
            print("Предыдущие review decisions устарели: hash quiz file изменился.")
        elif gate.allowed:
            print("Review уже пройден для текущего hash.")
            print("Следующая команда:")
            print(_upload_command(quiz_path, title=_safe_quiz_title(quiz_path)))
            return 0

    decisions: list[ReviewDecision] = []
    groups: list[GroupReviewDecision] = []
    question_snapshots = _load_question_snapshots(quiz_path)

    for issue in report.hard_errors:
        decision = _prompt_issue(issue, question_snapshots)
        if decision is None:
            break
        decisions.append(decision)
        if decision.action in {"edit", "abort"}:
            break

    if not any(decision.action in {"edit", "abort"} for decision in decisions):
        warning_groups, individual_warnings = _safe_warning_groups(report.warnings)
        stop_review = False
        for grouped_issues in warning_groups:
            action = _prompt_warning_group(grouped_issues, question_snapshots)
            if action == "review_one_by_one":
                for issue in grouped_issues:
                    decision = _prompt_issue(issue, question_snapshots)
                    if decision is None:
                        break
                    decisions.append(decision)
                    if decision.action in {"edit", "abort"}:
                        break
            elif action is not None:
                group = expand_group_decision(
                    group_id=_group_id(grouped_issues, report.quiz_file_hash),
                    issue_code=grouped_issues[0].code,
                    action=action,
                    affected_question_indexes=[
                        issue.source_question_index
                        for issue in grouped_issues
                        if issue.source_question_index is not None
                    ],
                )
                groups.append(group)
                if action in {"edit", "abort"}:
                    stop_review = True
            if any(decision.action in {"edit", "abort"} for decision in decisions):
                break
            if stop_review:
                break
        if not stop_review and not any(decision.action in {"edit", "abort"} for decision in decisions):
            for issue in individual_warnings:
                decision = _prompt_issue(issue, question_snapshots)
                if decision is None:
                    break
                decisions.append(decision)
                if decision.action in {"edit", "abort"}:
                    break

    artifact = build_review_artifact(
        quiz_file_hash=report.quiz_file_hash,
        decisions=decisions,
        groups=groups,
    )
    write_json_utf8(review_path, artifact.to_dict())
    print(f"review-decisions.json: {review_path}")

    gate = resolve_upload_gate(report, artifact)
    if gate.allowed:
        print("Review пройден. Upload разрешен.")
        print("Следующая команда:")
        print(_upload_command(quiz_path, title=_safe_quiz_title(quiz_path)))
        return 0
    if gate.status == "blocked":
        print("Review не завершен: остались блокирующие ошибки.", file=sys.stderr)
        return 1
    print("Review не завершен: остались предупреждения без решения.", file=sys.stderr)
    return 1


def _load_existing_review_artifact(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return parse_review_artifact(raw)
    except (OSError, json.JSONDecodeError, ReviewDecisionError) as exc:
        print(f"Существующий review-decisions.json не используется: {exc}")
        return None


def _load_question_snapshots(quiz_path: Path) -> dict[int, dict[str, Any]]:
    try:
        clean_json = load_clean_quiz_file(quiz_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    items = clean_json.get("items")
    if not isinstance(items, list):
        return {}

    snapshots: dict[int, dict[str, Any]] = {}
    source_question_index = 0
    for item in items:
        if not isinstance(item, Mapping) or item.get("type") != "question":
            continue
        source_question_index += 1
        options: list[str] = []
        raw_options = item.get("options")
        if isinstance(raw_options, list):
            for option in raw_options:
                if isinstance(option, Mapping) and isinstance(option.get("text"), str):
                    options.append(option["text"])
        question_text = item.get("question") if isinstance(item.get("question"), str) else ""
        snapshots[source_question_index] = {
            "question_text": question_text,
            "options": options,
        }
    return snapshots


def _prompt_issue(
    issue: ValidationIssue,
    question_snapshots: Mapping[int, Mapping[str, Any]],
) -> ReviewDecision | None:
    _print_issue(issue, question_snapshots)
    if issue.source_question_index is None:
        print("Это file-level issue. Исправь JSON и запусти validate заново.")
        return None
    action = _ask_action(issue.actions)
    if action is None:
        return None
    return make_review_decision(
        issue_code=issue.code,
        source_question_index=issue.source_question_index,
        action=action,
        evidence=issue.evidence,
    )


def _print_issue(
    issue: ValidationIssue,
    question_snapshots: Mapping[int, Mapping[str, Any]],
) -> None:
    print("")
    print(f"[{issue.severity.upper()}] {issue.code}")
    if issue.source_question_index is not None:
        print(f"Вопрос #{issue.source_question_index}")
    print(f"Сообщение: {issue.message_ru}")
    print(f"Действие: {issue.action_ru}")

    snapshot = (
        question_snapshots.get(issue.source_question_index, {})
        if issue.source_question_index is not None
        else {}
    )
    question_text = snapshot.get("question_text") or issue.question_text
    if question_text:
        print(f"Текст вопроса: {question_text}")
    options = snapshot.get("options")
    if isinstance(options, list) and options:
        print("Варианты:")
        for index, option_text in enumerate(options, start=1):
            print(f"  {index}. {option_text}")
    if issue.evidence:
        print("Evidence:")
        print(json.dumps(issue.evidence, ensure_ascii=False, indent=2))


def _ask_action(actions: list[str], *, extra_actions: list[str] | None = None) -> str | None:
    available = list(dict.fromkeys([*actions, *(extra_actions or [])]))
    while True:
        value = input(f"Выберите действие [{'/'.join(available)}]: ").strip()
        try:
            if value in available:
                return value
            raise ReviewDecisionError(f"Unknown review action: {value!r}")
        except ReviewDecisionError as exc:
            print(f"Недопустимое действие: {exc}")


def _prompt_warning_group(
    issues: list[ValidationIssue],
    question_snapshots: Mapping[int, Mapping[str, Any]],
) -> str | None:
    first = issues[0]
    question_indexes = [
        issue.source_question_index for issue in issues if issue.source_question_index is not None
    ]
    print("")
    print(f"Группа предупреждений: {first.code}")
    print(f"Количество: {len(issues)}")
    print("Вопросы: " + ", ".join(str(index) for index in question_indexes))
    print(f"Сообщение: {first.message_ru}")
    print(f"Действие: {first.action_ru}")
    print("Примеры:")
    for issue in issues[:5]:
        _print_issue(issue, question_snapshots)

    action = _ask_action(first.actions, extra_actions=["review_one_by_one"])
    if action == "skip_question":
        expected = f"skip {len(question_indexes)}"
        confirmation = input(
            f"Чтобы пропустить {len(question_indexes)} вопросов, введите '{expected}': "
        ).strip()
        if confirmation != expected:
            print("Group skip отменен.")
            return None
    return action


def _safe_warning_groups(
    warnings: list[ValidationIssue],
) -> tuple[list[list[ValidationIssue]], list[ValidationIssue]]:
    buckets: dict[tuple[str, tuple[str, ...]], list[ValidationIssue]] = defaultdict(list)
    individual: list[ValidationIssue] = []
    for issue in warnings:
        if issue.source_question_index is None:
            individual.append(issue)
            continue
        buckets[(issue.code, tuple(issue.actions))].append(issue)

    groups: list[list[ValidationIssue]] = []
    for grouped in buckets.values():
        if len(grouped) > 1:
            groups.append(grouped)
        else:
            individual.extend(grouped)
    return groups, individual


def _group_id(issues: list[ValidationIssue], quiz_file_hash: str) -> str:
    indexes = "-".join(
        str(issue.source_question_index)
        for issue in issues
        if issue.source_question_index is not None
    )
    return f"{issues[0].code}:{quiz_file_hash.removeprefix('sha256:')[:12]}:{indexes}"


def _safe_quiz_title(quiz_path: Path) -> str:
    try:
        clean_json = load_clean_quiz_file(quiz_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return "Новый квиз"
    title = clean_json.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return "Новый квиз"


def _upload_command(quiz_path: Path, *, title: str) -> str:
    return (
        "python -m backend.pipeline_cli upload "
        f"--file {shlex.quote(str(quiz_path))} "
        f"--name {shlex.quote(title)} "
        f"--speed {DEFAULT_UPLOAD_SPEED}"
    )


def _validate_command(quiz_path: Path, out_dir: Path, *, interactive: bool) -> str:
    command = (
        "python -m backend.pipeline_cli validate "
        f"--file {shlex.quote(str(quiz_path))} "
        f"--out {shlex.quote(str(out_dir))}"
    )
    if interactive:
        command += " --interactive"
    return command


def _make_upload_service() -> Any:
    from backend.upload_service import UploadService

    return UploadService()


def _make_speed_probe_service() -> Any:
    from backend.speed_probe import SpeedProbeService

    return SpeedProbeService()


def _make_run_store() -> Any:
    from backend import runs

    return runs.RunStore()


def _store_from_service(service: Any) -> Any:
    return getattr(service, "run_store", None) or _make_run_store()


def _startup_reconcile(
    store: Any,
    *,
    confirmed: bool,
    new_run_label: str = "upload",
) -> bool | None:
    active_run_id = store.get_active_run_id(required=False)
    if not active_run_id:
        return False

    from backend import runs

    active_run = store.load_run(active_run_id)
    if not runs.has_protected_progress(active_run):
        print("Найден активный запуск без защищенного прогресса; он будет заменен.")
        return True

    _print_run_summary(
        active_run,
        title="Найден активный запуск с защищенным прогрессом.",
    )
    if _confirm_dangerous_action(
        f"Новый {new_run_label} заменит активный запуск и пометит старый как cancelled_replaced.",
        yes=confirmed,
    ):
        return True

    print(f"Новый {new_run_label} не запущен. Чтобы продолжить старый запуск, используй:")
    print("python -m backend.pipeline_cli resume")
    return None


def _run_maybe_async(value: Any) -> Any:
    if inspect.isawaitable(value):
        return asyncio.run(value)
    return value


def _upload_gate_error_type() -> type[Exception]:
    from backend.upload_service import UploadGateBlockedError

    return UploadGateBlockedError


def _upload_confirmation_error_type() -> type[Exception]:
    from backend.upload_service import UploadConfirmationRequired

    return UploadConfirmationRequired


def _is_speed_probe_run(store: Any, run_id: str | None) -> bool:
    try:
        run = store.resolve_run(run_id) if hasattr(store, "resolve_run") else None
    except Exception:
        return False
    from backend import runs

    return isinstance(run, runs.SpeedProbeRun)


def _print_run_summary(run_or_snapshot: Any, *, title: str) -> None:
    snapshot = _snapshot(run_or_snapshot)
    print(title)
    print(f"ID запуска: {_snapshot_value(snapshot, 'run_id', 'probe_id')}")
    print(f"Статус: {_snapshot_value(snapshot, 'status')}")
    print(f"Профиль: {_snapshot_value(snapshot, 'account_profile_id')}")
    print(f"Квиз: {_snapshot_value(snapshot, 'quiz_name')}")
    if snapshot.get("kind") == "speed_probe":
        print(f"Первый лимит: {_snapshot_value(snapshot, 'first_limit_at_question')}")
        print(f"Cleanup: {_snapshot_value(snapshot, 'cleanup_status')}")
    else:
        print(f"Следующий вопрос: {_snapshot_value(snapshot, 'next_question_index')}")
    print(f"Последняя ошибка: {_format_last_error(snapshot.get('last_error'))}")


def _snapshot(run_or_snapshot: Any) -> dict[str, Any]:
    if isinstance(run_or_snapshot, Mapping):
        return dict(run_or_snapshot)
    if hasattr(run_or_snapshot, "to_dict"):
        data = run_or_snapshot.to_dict()
        if isinstance(data, Mapping):
            return dict(data)
    fields = [
        "run_id",
        "probe_id",
        "status",
        "account_profile_id",
        "quiz_name",
        "next_question_index",
        "first_limit_at_question",
        "cleanup_status",
        "last_error",
    ]
    return {
        field: getattr(run_or_snapshot, field)
        for field in fields
        if hasattr(run_or_snapshot, field)
    }


def _snapshot_value(snapshot: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = snapshot.get(key)
        if value is not None and value != "":
            return str(value)
    return "нет данных"


def _format_last_error(value: Any) -> str:
    if not value:
        return "нет"
    if isinstance(value, Mapping):
        code = value.get("code")
        message = value.get("message")
        if code and message:
            return f"{code}: {message}"
        if code:
            return str(code)
        if message:
            return str(message)
    return str(value)


def _print_confirmation_details(exc: Exception) -> None:
    action = getattr(exc, "action", "dangerous_action")
    details = getattr(exc, "details", {})
    print("Требуется подтверждение опасного действия.")
    print(f"Действие: {action}")
    if isinstance(details, Mapping):
        for key, value in details.items():
            print(f"{key}: {value}")


def _confirm_dangerous_action(message: str, *, yes: bool) -> bool:
    print(message)
    if yes:
        print("Подтверждение получено через --yes.")
        return True
    if not sys.stdin.isatty():
        print("В неинтерактивном режиме добавь --yes для подтверждения.")
        return False
    answer = input("Для подтверждения введи 'да': ").strip().casefold()
    if answer in {"да", "yes", "y"}:
        return True
    print("Действие отменено.")
    return False


def _account_switch_allowed(profile_id: str) -> bool:
    from backend import runs

    store = _make_run_store()
    active_run_id = store.get_active_run_id(required=False)
    if not active_run_id:
        return True

    active_run = store.load_run(active_run_id)
    if not runs.has_protected_progress(active_run):
        return True

    active_run_profile_id = getattr(active_run, "account_profile_id", None)
    if active_run_profile_id == profile_id:
        return True

    print(
        "Нельзя переключить account profile: есть активный запуск "
        f"{active_run_id} с профилем {active_run_profile_id}.",
        file=sys.stderr,
    )
    print("Заверши, поставь на безопасную паузу/cleanup или продолжи текущий запуск.")
    return False


def _print_public_profile(profile: Any) -> None:
    active = "да" if getattr(profile, "is_active", False) else "нет"
    phone = getattr(profile, "telegram_phone_masked", "") or "нет данных"
    session = getattr(profile, "session_path_basename", "") or "нет данных"
    print(
        "- "
        f"id={profile.id}; "
        f"name={profile.display_name}; "
        f"status={profile.status}; "
        f"active={active}; "
        f"phone={phone}; "
        f"session={session}"
    )


def _print_account_error(exc: Exception) -> int:
    print(f"Account profile error: {exc}", file=sys.stderr)
    return 1


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

    validate = subparsers.add_parser(
        "validate",
        help="Validate clean quiz JSON and optionally run interactive review.",
    )
    validate.add_argument("--file", required=True, help="Clean quiz JSON file")
    validate.add_argument("--out", required=True, help="Output directory")
    validate.add_argument(
        "--interactive",
        action="store_true",
        help="Prompt for review decisions and write review-decisions.json",
    )
    validate.set_defaults(func=validate_quiz)

    upload = subparsers.add_parser(
        "upload",
        help="Start a foreground resumable upload run.",
    )
    upload.add_argument("--file", required=True, help="Clean quiz JSON file")
    upload.add_argument("--name", required=True, help="Quiz name")
    upload.add_argument(
        "--speed",
        default=DEFAULT_UPLOAD_SPEED,
        help="Upload speed preset: normal, fast, slow, or auto",
    )
    upload.add_argument(
        "--start-from",
        type=int,
        default=1,
        help="Source question index for a new upload run",
    )
    upload.add_argument("--profile", default=None, help="Account profile override")
    upload.add_argument(
        "--yes",
        action="store_true",
        help="Confirm replacing a protected active run",
    )
    upload.set_defaults(func=upload_quiz)

    probe = subparsers.add_parser(
        "probe-speed",
        help="Run a disposable speed threshold probe.",
    )
    probe.add_argument("--file", required=True, help="Clean probe quiz JSON file")
    probe.add_argument("--questions", type=int, required=True, help="Number of source questions to probe")
    probe.add_argument(
        "--policy",
        choices=["fast-threshold"],
        default="fast-threshold",
        help="Probe delay policy",
    )
    probe.add_argument("--profile", default=None, help="Account profile override")
    probe.add_argument(
        "--confirm-active",
        action="store_true",
        help=(
            "Explicitly allow probing the active/default account profile when "
            "no --profile is given (the probe will burn its limits)."
        ),
    )
    probe.add_argument(
        "--yes",
        action="store_true",
        help="Confirm replacing a protected active run",
    )
    probe.set_defaults(func=probe_speed)

    status = subparsers.add_parser("status", help="Show upload run status.")
    status.add_argument("--run-id", default=None, help="Run id; defaults to active run")
    status.set_defaults(func=status_run)

    resume = subparsers.add_parser("resume", help="Resume an upload run.")
    resume.add_argument("--run-id", default=None, help="Run id; defaults to active run")
    resume.set_defaults(func=resume_run)

    pause = subparsers.add_parser("pause", help="Mark an upload run as paused.")
    pause.add_argument("--run-id", default=None, help="Run id; defaults to active run")
    pause.set_defaults(func=pause_run)

    rollback = subparsers.add_parser(
        "rollback",
        help="Rollback uploaded questions with explicit confirmation.",
    )
    rollback.add_argument("--to", type=int, required=True, help="Source question index")
    rollback.add_argument("--run-id", default=None, help="Run id; defaults to active run")
    rollback.add_argument("--yes", action="store_true", help="Confirm rollback")
    rollback.set_defaults(func=rollback_run)

    continue_from = subparsers.add_parser(
        "continue-from",
        help="Resume, rollback, or skip forward to a source question.",
    )
    continue_from.add_argument("question_index", type=int, help="Source question index")
    continue_from.add_argument("--run-id", default=None, help="Run id; defaults to active run")
    continue_from.add_argument(
        "--yes",
        action="store_true",
        help="Confirm rollback or skip-forward when needed",
    )
    continue_from.set_defaults(func=continue_from_run)

    account = subparsers.add_parser(
        "account",
        help="Manage account profiles.",
    )
    account_subparsers = account.add_subparsers(dest="account_command", required=True)

    account_list_parser = account_subparsers.add_parser(
        "list",
        help="List account profiles.",
    )
    account_list_parser.set_defaults(func=account_list)

    account_current_parser = account_subparsers.add_parser(
        "current",
        help="Show the active account profile.",
    )
    account_current_parser.set_defaults(func=account_current)

    account_use_parser = account_subparsers.add_parser(
        "use",
        help="Set the active account profile for new upload/probe runs.",
    )
    account_use_parser.add_argument("profile_id", help="Account profile id")
    account_use_parser.set_defaults(func=account_use)

    account_enable_parser = account_subparsers.add_parser(
        "enable",
        help="Enable an account profile.",
    )
    account_enable_parser.add_argument("profile_id", help="Account profile id")
    account_enable_parser.set_defaults(func=account_enable)

    account_disable_parser = account_subparsers.add_parser(
        "disable",
        help="Disable an account profile.",
    )
    account_disable_parser.add_argument("profile_id", help="Account profile id")
    account_disable_parser.set_defaults(func=account_disable)

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
