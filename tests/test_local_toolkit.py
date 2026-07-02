from __future__ import annotations

import json
import socket
import subprocess
from dataclasses import asdict, fields

import pytest

from qsardb_client.local import (
    LocalToolkitError,
    QsarDBToolkitBackend,
    QsarDBToolkitConfig,
    ToolkitAvailability,
    ToolkitCommandResult,
    ToolkitExecutionError,
    ToolkitUnavailableError,
)


FORBIDDEN_FIELD_TERMS = {
    "ssbd",
    "hazard",
    "endpoint_weighting",
    "endpoint_weight",
    "regulatory",
    "safe",
    "unsafe",
    "prediction_value",
    "result_float",
}


def test_config_default_does_not_require_toolkit_jar() -> None:
    config = QsarDBToolkitConfig()

    assert config.toolkit_jar is None
    assert config.java_executable == "java"
    assert config.timeout_seconds == 60.0


def test_toolkit_availability_is_json_friendly() -> None:
    availability = ToolkitAvailability(
        java_executable="java",
        java_available=False,
        java_version_output=None,
        toolkit_jar=None,
        toolkit_available=False,
        limitations=("No toolkit configured.",),
    )

    assert json.loads(json.dumps(asdict(availability)))["java_executable"] == "java"


def test_toolkit_command_result_preserves_stdout_and_stderr() -> None:
    result = ToolkitCommandResult(
        command=("java", "-jar", "toolkit.jar"),
        returncode=0,
        stdout="raw stdout",
        stderr="raw stderr",
        timed_out=False,
        duration_seconds=0.1,
        dry_run=False,
        limitations=("No interpretation performed.",),
    )

    assert result.stdout == "raw stdout"
    assert result.stderr == "raw stderr"


def test_check_availability_reports_java_available_and_captures_stderr(monkeypatch) -> None:
    def fake_run(command, **kwargs):  # noqa: ANN001
        assert command == ["java", "-version"]
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert "shell" not in kwargs
        return subprocess.CompletedProcess(command, 0, stdout="", stderr='java version "17"')

    monkeypatch.setattr(subprocess, "run", fake_run)

    availability = QsarDBToolkitBackend().check_availability()

    assert availability.java_available is True
    assert availability.java_version_output == 'java version "17"'
    assert availability.toolkit_available is False
    assert "No QsarDB toolkit JAR path is configured." in availability.limitations


def test_check_availability_reports_java_unavailable_without_raising(monkeypatch) -> None:
    def fake_run(command, **kwargs):  # noqa: ANN001
        raise FileNotFoundError("missing java")

    monkeypatch.setattr(subprocess, "run", fake_run)

    availability = QsarDBToolkitBackend().check_availability()

    assert availability.java_available is False
    assert availability.java_version_output is None
    assert any("Java executable is not available" in text for text in availability.limitations)


def test_check_availability_reports_existing_toolkit_jar(tmp_path, monkeypatch) -> None:
    jar = tmp_path / "qsardb-toolkit.jar"
    jar.write_text("not a real jar", encoding="utf-8")

    def fake_run(command, **kwargs):  # noqa: ANN001
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="java ok")

    monkeypatch.setattr(subprocess, "run", fake_run)

    backend = QsarDBToolkitBackend(QsarDBToolkitConfig(toolkit_jar=str(jar)))

    availability = backend.check_availability()

    assert availability.toolkit_jar == str(jar)
    assert availability.toolkit_available is True


def test_check_availability_reports_missing_toolkit_jar(tmp_path, monkeypatch) -> None:
    missing_jar = tmp_path / "missing.jar"

    def fake_run(command, **kwargs):  # noqa: ANN001
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="java ok")

    monkeypatch.setattr(subprocess, "run", fake_run)

    backend = QsarDBToolkitBackend(QsarDBToolkitConfig(toolkit_jar=str(missing_jar)))

    availability = backend.check_availability()

    assert availability.toolkit_available is False
    assert any("does not exist" in text for text in availability.limitations)


def test_build_command_raises_when_toolkit_jar_is_none() -> None:
    backend = QsarDBToolkitBackend()

    with pytest.raises(ToolkitUnavailableError):
        backend.build_command("help")


def test_build_command_raises_when_toolkit_jar_is_missing(tmp_path) -> None:
    backend = QsarDBToolkitBackend(
        QsarDBToolkitConfig(toolkit_jar=str(tmp_path / "missing.jar"))
    )

    with pytest.raises(ToolkitUnavailableError):
        backend.build_command("help")


def test_build_command_uses_java_args_jar_and_toolkit_args(tmp_path) -> None:
    jar = tmp_path / "toolkit.jar"
    jar.write_text("fake", encoding="utf-8")
    backend = QsarDBToolkitBackend(
        QsarDBToolkitConfig(
            toolkit_jar=str(jar),
            java_executable="java-custom",
            extra_java_args=("-Xmx1g", "-Dexample=true"),
        )
    )

    command = backend.build_command("inspect", "--handle", "10967/1")

    assert command == (
        "java-custom",
        "-Xmx1g",
        "-Dexample=true",
        "-jar",
        str(jar),
        "inspect",
        "--handle",
        "10967/1",
    )


def test_run_dry_run_does_not_call_subprocess(tmp_path, monkeypatch) -> None:
    jar = tmp_path / "toolkit.jar"
    jar.write_text("fake", encoding="utf-8")

    def fail_run(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("subprocess.run should not be called for dry_run")

    monkeypatch.setattr(subprocess, "run", fail_run)
    backend = QsarDBToolkitBackend(QsarDBToolkitConfig(toolkit_jar=str(jar)))

    result = backend.run("metadata", dry_run=True)

    assert result.command == ("java", "-jar", str(jar), "metadata")
    assert result.returncode is None
    assert result.dry_run is True
    assert result.timed_out is False


def test_run_success_returns_raw_output(tmp_path, monkeypatch) -> None:
    jar = tmp_path / "toolkit.jar"
    jar.write_text("fake", encoding="utf-8")

    def fake_run(command, **kwargs):  # noqa: ANN001
        assert command == ["java", "-jar", str(jar), "metadata"]
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert "shell" not in kwargs
        return subprocess.CompletedProcess(command, 0, stdout="raw stdout", stderr="raw stderr")

    monkeypatch.setattr(subprocess, "run", fake_run)
    backend = QsarDBToolkitBackend(QsarDBToolkitConfig(toolkit_jar=str(jar)))

    result = backend.run("metadata")

    assert result.returncode == 0
    assert result.stdout == "raw stdout"
    assert result.stderr == "raw stderr"
    assert result.timed_out is False
    assert result.dry_run is False


def test_run_nonzero_with_check_false_returns_result(tmp_path, monkeypatch) -> None:
    jar = tmp_path / "toolkit.jar"
    jar.write_text("fake", encoding="utf-8")

    def fake_run(command, **kwargs):  # noqa: ANN001
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="bad command")

    monkeypatch.setattr(subprocess, "run", fake_run)
    backend = QsarDBToolkitBackend(QsarDBToolkitConfig(toolkit_jar=str(jar)))

    result = backend.run("bad", check=False)

    assert result.returncode == 2
    assert result.stderr == "bad command"


def test_run_nonzero_with_check_true_raises_execution_error(tmp_path, monkeypatch) -> None:
    jar = tmp_path / "toolkit.jar"
    jar.write_text("fake", encoding="utf-8")

    def fake_run(command, **kwargs):  # noqa: ANN001
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="bad command")

    monkeypatch.setattr(subprocess, "run", fake_run)
    backend = QsarDBToolkitBackend(QsarDBToolkitConfig(toolkit_jar=str(jar)))

    with pytest.raises(ToolkitExecutionError):
        backend.run("bad", check=True)


def test_run_timeout_returns_timed_out_result(tmp_path, monkeypatch) -> None:
    jar = tmp_path / "toolkit.jar"
    jar.write_text("fake", encoding="utf-8")

    def fake_run(command, **kwargs):  # noqa: ANN001
        raise subprocess.TimeoutExpired(
            command,
            timeout=kwargs["timeout"],
            output="partial stdout",
            stderr="partial stderr",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    backend = QsarDBToolkitBackend(
        QsarDBToolkitConfig(toolkit_jar=str(jar), timeout_seconds=0.01)
    )

    result = backend.run("slow")

    assert result.returncode is None
    assert result.timed_out is True
    assert result.stdout == "partial stdout"
    assert result.stderr == "partial stderr"


def test_run_passes_working_directory(tmp_path, monkeypatch) -> None:
    jar = tmp_path / "toolkit.jar"
    jar.write_text("fake", encoding="utf-8")
    seen_kwargs = {}

    def fake_run(command, **kwargs):  # noqa: ANN001
        seen_kwargs.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    backend = QsarDBToolkitBackend(
        QsarDBToolkitConfig(
            toolkit_jar=str(jar),
            working_directory=str(tmp_path),
        )
    )

    backend.run("metadata")

    assert seen_kwargs["cwd"] == str(tmp_path)


def test_no_output_is_interpreted_as_prediction_values(tmp_path, monkeypatch) -> None:
    jar = tmp_path / "toolkit.jar"
    jar.write_text("fake", encoding="utf-8")

    def fake_run(command, **kwargs):  # noqa: ANN001
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="prediction = 12.3",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    backend = QsarDBToolkitBackend(QsarDBToolkitConfig(toolkit_jar=str(jar)))

    result = backend.run("predict-like-output")

    assert result.stdout == "prediction = 12.3"
    assert not hasattr(result, "prediction")
    assert not hasattr(result, "result_float")


def test_public_exceptions_share_base_type() -> None:
    assert issubclass(ToolkitUnavailableError, LocalToolkitError)
    assert issubclass(ToolkitExecutionError, LocalToolkitError)


def test_no_forbidden_fields_are_present() -> None:
    field_names = {
        field.name.lower()
        for model in [ToolkitAvailability, ToolkitCommandResult, QsarDBToolkitConfig]
        for field in fields(model)
    }

    for forbidden in FORBIDDEN_FIELD_TERMS:
        assert all(forbidden not in field_name for field_name in field_names)


def test_wrapper_is_count_agnostic_when_building_commands(tmp_path) -> None:
    jar = tmp_path / "toolkit.jar"
    jar.write_text("fake", encoding="utf-8")
    backend = QsarDBToolkitBackend(QsarDBToolkitConfig(toolkit_jar=str(jar)))
    dynamic_args = tuple(f"arg-{index}" for index in range(137))

    command = backend.build_command(*dynamic_args)

    assert command[-137:] == dynamic_args
    assert "arg-100" in command


def test_no_live_network_calls_occur(tmp_path, monkeypatch) -> None:
    def fail_network(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("live network access was attempted")

    monkeypatch.setattr(socket, "create_connection", fail_network)

    jar = tmp_path / "toolkit.jar"
    jar.write_text("fake", encoding="utf-8")
    backend = QsarDBToolkitBackend(QsarDBToolkitConfig(toolkit_jar=str(jar)))

    result = backend.run("metadata", dry_run=True)

    assert result.dry_run is True
