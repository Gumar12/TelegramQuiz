"""Core pipeline contracts for the DOCX-first parser flow."""

from backend.pipeline.document_ir import BoldSpan, DocumentBlock, DocumentIR
from backend.pipeline.encoding import (
    configure_cli_output_utf8,
    detect_suspect_encoding,
    normalize_text,
    write_json_utf8,
    write_text_utf8,
)
from backend.pipeline.reports import EncodingReport, ReportIssue

__all__ = [
    "BoldSpan",
    "DocumentBlock",
    "DocumentIR",
    "EncodingReport",
    "ReportIssue",
    "configure_cli_output_utf8",
    "detect_suspect_encoding",
    "normalize_text",
    "write_json_utf8",
    "write_text_utf8",
]