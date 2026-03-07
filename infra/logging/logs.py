#!/usr/bin/env python3
"""Unified log viewer for Docker Compose services and the managed frontend."""

from __future__ import annotations

import argparse
import json
import queue
import re
import subprocess
import sys
import threading
import time
from collections import Counter, deque
from pathlib import Path
from typing import Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_LOG_FILE = REPO_ROOT / "logs" / "dev" / "frontend.log"
SERVICE_PATTERN = re.compile(r"^([^\s]+)\s+\|\s+(.*)$")
TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")
ANSI_PATTERN = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
LEVEL_RANKS = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
    "FATAL": 60,
}
DEFAULT_LEVEL = "INFO"


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than 0")
    return parsed


def normalize_level(level: str) -> str:
    normalized = level.strip().upper()
    if normalized == "WARN":
        return "WARNING"
    return normalized if normalized in LEVEL_RANKS else DEFAULT_LEVEL


def build_logs_command(
    services: Optional[list[str]] = None,
    tail: int = 100,
    follow: bool = False,
) -> list[str]:
    cmd = ["docker", "compose", "logs", "--no-color", "--timestamps", "--tail", str(tail)]
    if follow:
        cmd.append("--follow")
    if services:
        cmd.extend(services)
    return cmd


def compose_error_message(
    completed: Optional[subprocess.CompletedProcess[str]] = None,
    stderr: str = "",
) -> str:
    candidates = []
    if completed is not None:
        candidates.extend([completed.stderr, completed.stdout])
    candidates.append(stderr)

    for candidate in candidates:
        if candidate:
            text = candidate.strip()
            if text:
                return text

    return "docker compose logs failed"


def split_service_filters(services: Optional[list[str]]) -> tuple[Optional[list[str]], bool]:
    if not services:
        return None, True

    docker_services: list[str] = []
    include_frontend = False
    for service in services:
        name = service.strip()
        if not name:
            continue
        if name == "frontend":
            include_frontend = True
            continue
        docker_services.append(name)

    return docker_services, include_frontend


def extract_level(content: str) -> str:
    upper = content.upper()
    if "FATAL" in upper:
        return "FATAL"
    if "CRITICAL" in upper:
        return "CRITICAL"
    if "ERROR" in upper:
        return "ERROR"
    if "WARN" in upper:
        return "WARNING"
    if "DEBUG" in upper:
        return "DEBUG"
    if "INFO" in upper:
        return "INFO"
    return DEFAULT_LEVEL


def extract_timestamp(content: str) -> str:
    match = TIMESTAMP_PATTERN.search(content)
    return match.group(0) if match else ""


def parse_log_line(line: str) -> dict[str, object]:
    stripped = line.rstrip()
    match = SERVICE_PATTERN.match(stripped)
    if not match:
        return {
            "service": "unknown",
            "raw": stripped,
            "is_json": False,
            "level": DEFAULT_LEVEL,
            "timestamp": "",
            "message": stripped,
        }

    service = re.sub(r"-\d+$", "", match.group(1).strip())
    content = match.group(2).strip()

    if content.startswith("{"):
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            payload = None
        else:
            return {
                "service": service,
                "raw": stripped,
                "is_json": True,
                "level": normalize_level(str(payload.get("level", DEFAULT_LEVEL))),
                "timestamp": str(payload.get("timestamp", "")),
                "message": str(payload.get("message", content)),
            }

    return {
        "service": service,
        "raw": stripped,
        "is_json": False,
        "level": extract_level(content),
        "timestamp": extract_timestamp(content),
        "message": content,
    }


def filter_log_line(
    line: str,
    service_filter: Optional[list[str]] = None,
    level_filter: Optional[str] = None,
    search_filter: Optional[str] = None,
) -> bool:
    parsed = parse_log_line(line)

    if service_filter and parsed["service"] not in service_filter:
        return False

    if level_filter:
        required = normalize_level(level_filter)
        actual = normalize_level(str(parsed["level"]))
        if LEVEL_RANKS.get(actual, LEVEL_RANKS[DEFAULT_LEVEL]) < LEVEL_RANKS[required]:
            return False

    if search_filter and search_filter.lower() not in line.lower():
        return False

    return True


def colorize_line(line: str, parsed: dict[str, object]) -> str:
    colors = {
        "ERROR": "\033[91m",
        "CRITICAL": "\033[91m",
        "FATAL": "\033[91m",
        "WARNING": "\033[93m",
        "INFO": "\033[92m",
        "DEBUG": "\033[96m",
        "RESET": "\033[0m",
    }
    level = normalize_level(str(parsed["level"]))
    return f"{colors.get(level, colors['RESET'])}{line}{colors['RESET']}"


def format_frontend_line(line: str) -> str:
    cleaned = ANSI_PATTERN.sub("", line).rstrip()
    cleaned = cleaned.replace("鉃?", ">")
    cleaned = re.sub(r"^[^A-Za-z/\[]*(Local:|Network:|press\s)", r"> \1", cleaned)
    return f"frontend | {cleaned}"


def read_frontend_tail_lines(path: Path, tail: int) -> list[str]:
    if not path.is_file():
        return []

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        lines = deque((format_frontend_line(line) for line in handle if line.strip()), maxlen=tail)
    return list(lines)


def run_docker_logs(services: Optional[list[str]], tail: int) -> list[str]:
    completed = subprocess.run(
        build_logs_command(services=services, tail=tail, follow=False),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(compose_error_message(completed=completed))

    output = completed.stdout.strip()
    if not output:
        return []
    return output.splitlines()


def collect_recent_lines(
    services: Optional[list[str]],
    tail: int,
    include_frontend: bool,
) -> list[str]:
    lines: list[str] = []

    if services is None or services:
        lines.extend(run_docker_logs(services=services, tail=tail))

    if include_frontend:
        lines.extend(read_frontend_tail_lines(FRONTEND_LOG_FILE, tail))

    return lines


def print_filtered_lines(
    lines: Iterable[str],
    service_filter: Optional[list[str]] = None,
    level_filter: Optional[str] = None,
    search_filter: Optional[str] = None,
    use_color: bool = True,
) -> None:
    for line in lines:
        if not line.strip():
            continue
        if not filter_log_line(
            line,
            service_filter=service_filter,
            level_filter=level_filter,
            search_filter=search_filter,
        ):
            continue

        if use_color and sys.stdout.isatty():
            parsed = parse_log_line(line)
            print(colorize_line(line.rstrip(), parsed))
        else:
            print(line.rstrip())


def show_stats(lines: list[str]) -> None:
    by_service: Counter[str] = Counter()
    by_level: Counter[str] = Counter()
    errors: list[str] = []

    for line in lines:
        if not line.strip():
            continue
        parsed = parse_log_line(line)
        by_service[str(parsed["service"])] += 1
        by_level[str(parsed["level"])] += 1
        if str(parsed["level"]) in {"ERROR", "CRITICAL", "FATAL"}:
            errors.append(line[:200])

    print("=" * 60)
    print(f"Log statistics (recent {len(lines)} lines)")
    print("=" * 60)
    print("")
    print("By service:")
    for service, count in sorted(by_service.items()):
        print(f"  {service:20s}: {count:5d}")
    print("")
    print("By level:")
    for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "FATAL"):
        count = by_level.get(level, 0)
        if count > 0:
            print(f"  {level:10s}: {count:5d}")
    if errors:
        print("")
        print("Recent error lines:")
        for item in errors[:5]:
            print(f"  {item}")
        if len(errors) > 5:
            print(f"  ... and {len(errors) - 5} more")
    print("=" * 60)


def start_docker_logs_process(services: Optional[list[str]], tail: int) -> subprocess.Popen[str]:
    return subprocess.Popen(
        build_logs_command(services=services, tail=tail, follow=True),
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )


def pump_docker_logs(proc: subprocess.Popen[str], sink: queue.Queue[tuple[str, object]]) -> None:
    assert proc.stdout is not None
    assert proc.stderr is not None

    for line in proc.stdout:
        sink.put(("line", line.rstrip("\n")))

    stderr = proc.stderr.read()
    return_code = proc.wait()
    sink.put(("docker-exit", {"returncode": return_code, "stderr": stderr}))


def tail_frontend_log(
    path: Path,
    tail: int,
    sink: queue.Queue[tuple[str, object]],
    stop_event: threading.Event,
) -> None:
    emitted_initial = False

    while not stop_event.is_set():
        if not path.exists():
            time.sleep(0.5)
            continue

        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                if not emitted_initial:
                    initial_lines = deque((line.rstrip("\n") for line in handle if line.strip()), maxlen=tail)
                    for item in initial_lines:
                        sink.put(("line", format_frontend_line(item)))
                    emitted_initial = True
                handle.seek(0, 2)
                position = handle.tell()

                while not stop_event.is_set():
                    line = handle.readline()
                    if line:
                        sink.put(("line", format_frontend_line(line.rstrip("\n"))))
                        position = handle.tell()
                        continue

                    try:
                        size = path.stat().st_size
                    except FileNotFoundError:
                        break

                    if size < position:
                        break

                    time.sleep(0.25)
        except OSError as exc:
            sink.put(("frontend-error", f"frontend log stream failed: {exc}"))
            time.sleep(0.5)

    sink.put(("frontend-exit", None))


def follow_logs(
    services: Optional[list[str]],
    service_filter: Optional[list[str]],
    tail: int,
    level: Optional[str],
    search: Optional[str],
    include_frontend: bool,
    use_color: bool,
) -> int:
    source_queue: queue.Queue[tuple[str, object]] = queue.Queue()
    stop_event = threading.Event()
    threads: list[threading.Thread] = []
    active_sources = 0

    docker_proc: Optional[subprocess.Popen[str]] = None
    if services is None or services:
        docker_proc = start_docker_logs_process(services=services, tail=tail)
        thread = threading.Thread(target=pump_docker_logs, args=(docker_proc, source_queue), daemon=True)
        thread.start()
        threads.append(thread)
        active_sources += 1

    if include_frontend:
        thread = threading.Thread(
            target=tail_frontend_log,
            args=(FRONTEND_LOG_FILE, tail, source_queue, stop_event),
            daemon=True,
        )
        thread.start()
        threads.append(thread)
        active_sources += 1

    if active_sources == 0:
        raise RuntimeError("no log sources selected")

    print("Following logs. Press Ctrl+C to stop.")
    print("-" * 60)

    try:
        while active_sources > 0:
            try:
                event_type, payload = source_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if event_type == "line":
                line = str(payload)
                if filter_log_line(
                    line,
                    service_filter=service_filter,
                    level_filter=level,
                    search_filter=search,
                ):
                    if use_color and sys.stdout.isatty():
                        parsed = parse_log_line(line)
                        print(colorize_line(line, parsed))
                    else:
                        print(line)
                    sys.stdout.flush()
                continue

            if event_type == "docker-exit":
                active_sources -= 1
                details = payload if isinstance(payload, dict) else {}
                return_code = int(details.get("returncode", 1))
                stderr = str(details.get("stderr", "")).strip()
                if return_code != 0:
                    raise RuntimeError(compose_error_message(stderr=stderr))
                continue

            if event_type == "frontend-exit":
                active_sources -= 1
                continue

            if event_type == "frontend-error":
                print(f"[WARN] {payload}", file=sys.stderr)
                continue

        return 0
    except KeyboardInterrupt:
        print("")
        print("Log streaming stopped.")
        return 130
    finally:
        stop_event.set()
        if docker_proc is not None and docker_proc.poll() is None:
            docker_proc.terminate()
            try:
                docker_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                docker_proc.kill()
        for thread in threads:
            thread.join(timeout=2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="View recent or live logs for Docker Compose services and the managed frontend.",
    )
    parser.add_argument(
        "--tail",
        "-n",
        type=positive_int,
        default=100,
        help="show the most recent N lines per source (default: 100)",
    )
    parser.add_argument(
        "--follow",
        "-f",
        action="store_true",
        help="follow logs in real time",
    )
    parser.add_argument(
        "--service",
        "-s",
        nargs="+",
        help="filter to one or more services; use 'frontend' for the managed frontend log",
    )
    parser.add_argument(
        "--level",
        "-l",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "FATAL"],
        default=None,
        help="show only lines at or above the selected level",
    )
    parser.add_argument(
        "--search",
        "-k",
        type=str,
        default=None,
        help="show only lines containing the keyword",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="show summary statistics instead of log lines",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="disable ANSI colors",
    )
    parser.add_argument(
        "--no-frontend",
        action="store_true",
        help="do not include the managed frontend log",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    docker_services, service_requests_frontend = split_service_filters(args.service)
    include_frontend = (not args.no_frontend) and (service_requests_frontend or args.service is None)

    try:
        if args.stats:
            lines = collect_recent_lines(docker_services, args.tail, include_frontend)
            show_stats(lines)
            return 0

        if args.follow:
            return follow_logs(
                services=docker_services,
                service_filter=args.service,
                tail=args.tail,
                level=args.level,
                search=args.search,
                include_frontend=include_frontend,
                use_color=not args.no_color,
            )

        lines = collect_recent_lines(docker_services, args.tail, include_frontend)
        if not lines:
            print("No logs available.")
            return 0

        print_filtered_lines(
            lines,
            service_filter=args.service,
            level_filter=args.level,
            search_filter=args.search,
            use_color=not args.no_color,
        )
        return 0
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
