from __future__ import annotations

import logging
import sys

from app.core.trace import get_trace_id


class TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id() or "-"
        return True


def configure_logging(level: str | None = None) -> None:
    log_level_name = (level or "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    root = logging.getLogger()
    root.setLevel(log_level)
    for h in list(root.handlers):
        root.removeHandler(h)
        
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.addFilter(TraceIdFilter())
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(trace_id)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)
