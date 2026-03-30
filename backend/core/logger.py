from __future__ import annotations
import os
import sys
import time
from typing import Callable

# YOMERU_DEBUG=0 silent, 1 progress, 2 verbose (default 1)
DEBUG = int(os.environ.get("YOMERU_DEBUG", "2"))

_CYAN   = "\033[36m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_GREY   = "\033[90m"
_RESET  = "\033[0m"
_BOLD   = "\033[1m"


def _c(color: str, text: str) -> str:
    return f"{color}{text}{_RESET}" if sys.stderr.isatty() else text


class PipelineLogger:
    def __init__(self, total: int, model: str, comic_format: str):
        self.total = total
        self.model = model
        self.comic_format = comic_format
        self._page_start: float = 0.0
        self._run_start: float = time.time()
        self._first_token_time: float | None = None
        self._token_count = 0
        self._in_think = False

    def run_start(self) -> None:
        if DEBUG < 1: return
        print(f"\n{_c(_BOLD, 'yomeru')} · pipeline", file=sys.stderr)
        print(f"  model   : {_c(_CYAN, self.model)}", file=sys.stderr)
        print(f"  format  : {self.comic_format}", file=sys.stderr)
        print(f"  pages   : {self.total}", file=sys.stderr)
        print(file=sys.stderr)

    def page_start(self, page: int, filename: str) -> None:
        if DEBUG < 1: return
        self._page_start = time.time()
        self._first_token_time = None
        self._token_count = 0
        self._in_think = False
        pad = len(str(self.total))
        print(f"[{page:{pad}d}/{self.total}] {_c(_GREY, filename)}", file=sys.stderr, end="  ", flush=True)

    def token(self, t: str) -> None:
        if DEBUG < 2: return
        now = time.time()
        if self._first_token_time is None:
            self._first_token_time = now
            elapsed = now - self._page_start
            print(f"\n{_c(_GREY, f'  first token: {elapsed:.1f}s')}", file=sys.stderr, flush=True)
        # track think blocks
        if "<think>" in t:
            self._in_think = True
        if "</think>" in t:
            self._in_think = False
            return
        if self._in_think:
            return
        self._token_count += 1
        print(t, file=sys.stderr, end="", flush=True)

    def page_done(self, page: int, dialogues: int, chars: int, mood: str, elapsed: float) -> None:
        if DEBUG < 1: return
        tok_s = f"{self._token_count / max(elapsed, 0.1):.0f} tok/s" if self._token_count else ""
        parts = [
            _c(_GREEN, "✓"),
            f"{elapsed:.1f}s",
            f"{dialogues}d {chars}c",
            _c(_GREY, mood),
        ]
        if tok_s and DEBUG >= 2:
            parts.append(_c(_GREY, tok_s))
        if DEBUG >= 2:
            print(file=sys.stderr)  # newline after streamed tokens
        print("  " + "  ".join(parts), file=sys.stderr)

    def page_error(self, page: int, error: str, elapsed: float) -> None:
        if DEBUG < 1: return
        if DEBUG >= 2:
            print(file=sys.stderr)
        print(f"  {_c(_RED, '✗')} {elapsed:.1f}s  {_c(_RED, error)}", file=sys.stderr)

    def run_done(self, processed: int, errors: int) -> None:
        if DEBUG < 1: return
        total_elapsed = time.time() - self._run_start
        status = _c(_GREEN, "done") if not errors else _c(_YELLOW, f"done ({errors} errors)")
        print(f"\n{status}  {processed}/{self.total} pages  {total_elapsed:.1f}s total\n", file=sys.stderr)