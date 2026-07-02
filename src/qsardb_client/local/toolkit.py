"""Optional wrapper for externally supplied QsarDB toolkit JAR files."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


class LocalToolkitError(Exception):
    """Base exception for local toolkit wrapper failures."""


class JavaUnavailableError(LocalToolkitError):
    """Raised when Java is required but not available."""


class ToolkitUnavailableError(LocalToolkitError):
    """Raised when a configured toolkit JAR path is missing or invalid."""


class ToolkitExecutionError(LocalToolkitError):
    """Raised only when caller requests raising on subprocess failure."""


@dataclass(frozen=True)
class ToolkitAvailability:
    java_executable: str
    java_available: bool
    java_version_output: str | None
    toolkit_jar: str | None
    toolkit_available: bool
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class ToolkitCommandResult:
    command: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    duration_seconds: float | None
    dry_run: bool
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class QsarDBToolkitConfig:
    toolkit_jar: str | None = None
    java_executable: str = "java"
    timeout_seconds: float | None = 60.0
    extra_java_args: tuple[str, ...] = ()
    working_directory: str | None = None


class QsarDBToolkitBackend:
    """Local execution wrapper for a user-supplied QsarDB toolkit JAR."""

    def __init__(self, config: QsarDBToolkitConfig | None = None) -> None:
        self.config = config or QsarDBToolkitConfig()

    def check_availability(self) -> ToolkitAvailability:
        limitations: list[str] = []
        java_available = False
        java_version_output: str | None = None

        try:
            completed = subprocess.run(
                [self.config.java_executable, "-version"],
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
            )
            java_version_output = _combine_output(completed.stdout, completed.stderr)
            java_available = completed.returncode == 0
            if not java_available:
                limitations.append(
                    f"Java executable returned non-zero status {completed.returncode}."
                )
        except FileNotFoundError:
            limitations.append("Java executable is not available on this system.")
        except subprocess.TimeoutExpired as exc:
            java_version_output = _combine_output(exc.stdout, exc.stderr)
            limitations.append("Java availability check timed out.")
        except OSError as exc:
            limitations.append(f"Java executable could not be executed: {exc}")

        toolkit_jar = self.config.toolkit_jar
        toolkit_available = False
        if toolkit_jar is None:
            limitations.append("No QsarDB toolkit JAR path is configured.")
        elif Path(toolkit_jar).is_file():
            toolkit_available = True
        else:
            limitations.append("Configured QsarDB toolkit JAR path does not exist as a file.")

        return ToolkitAvailability(
            java_executable=self.config.java_executable,
            java_available=java_available,
            java_version_output=java_version_output,
            toolkit_jar=toolkit_jar,
            toolkit_available=toolkit_available,
            limitations=tuple(limitations),
        )

    def build_command(self, *toolkit_args: str) -> tuple[str, ...]:
        toolkit_jar = self.config.toolkit_jar
        if toolkit_jar is None:
            raise ToolkitUnavailableError("QsarDB toolkit JAR path is not configured.")
        if not Path(toolkit_jar).is_file():
            raise ToolkitUnavailableError(
                f"QsarDB toolkit JAR path does not exist as a file: {toolkit_jar}"
            )

        return (
            self.config.java_executable,
            *tuple(str(arg) for arg in self.config.extra_java_args),
            "-jar",
            str(toolkit_jar),
            *tuple(str(arg) for arg in toolkit_args),
        )

    def run(
        self,
        *toolkit_args: str,
        dry_run: bool = False,
        check: bool = False,
    ) -> ToolkitCommandResult:
        command = self.build_command(*toolkit_args)
        if dry_run:
            return ToolkitCommandResult(
                command=command,
                returncode=None,
                stdout="",
                stderr="",
                timed_out=False,
                duration_seconds=0.0,
                dry_run=True,
                limitations=(
                    "Dry run only; command was constructed but not executed.",
                    "Command output is not interpreted as prediction data.",
                ),
            )

        started = time.monotonic()
        try:
            completed = subprocess.run(
                list(command),
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
                cwd=self.config.working_directory,
            )
            duration_seconds = time.monotonic() - started
            result = ToolkitCommandResult(
                command=command,
                returncode=completed.returncode,
                stdout=completed.stdout or "",
                stderr=completed.stderr or "",
                timed_out=False,
                duration_seconds=duration_seconds,
                dry_run=False,
                limitations=(
                    "Subprocess output is preserved without scientific interpretation.",
                    "A successful command does not prove local prediction support or model validity.",
                ),
            )
        except subprocess.TimeoutExpired as exc:
            duration_seconds = time.monotonic() - started
            result = ToolkitCommandResult(
                command=command,
                returncode=None,
                stdout=_decode_timeout_output(exc.stdout),
                stderr=_decode_timeout_output(exc.stderr),
                timed_out=True,
                duration_seconds=duration_seconds,
                dry_run=False,
                limitations=(
                    "Toolkit subprocess timed out.",
                    "Partial subprocess output is preserved without scientific interpretation.",
                ),
            )

        if check and result.returncode not in (0, None):
            raise ToolkitExecutionError(
                f"Toolkit command failed with return code {result.returncode}: {command}"
            )
        return result


def _combine_output(stdout: str | bytes | None, stderr: str | bytes | None) -> str | None:
    output = "\n".join(
        text
        for text in [_decode_timeout_output(stdout), _decode_timeout_output(stderr)]
        if text
    ).strip()
    return output or None


def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)
