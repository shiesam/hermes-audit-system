from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_ODA_PATH = "/usr/bin/ODAFileConverter_27.1.0.0/ODAFileConverter"
DEFAULT_LIBREDWG_PATH = "dwg2dxf"
DEFAULT_OUTPUT_VERSION = "ACAD2018"
DEFAULT_TIMEOUT_SECONDS = 180


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sanitize_filename(filename: str) -> str:
    path = Path(filename)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem).strip("._")
    suffix = re.sub(r"[^A-Za-z0-9.]+", "", path.suffix) or ".dwg"
    sanitized = f"{stem or 'input'}{suffix}"
    return sanitized


def _stringify_command(command: list[str]) -> str:
    return " ".join(shlex_quote(part) for part in command)


def shlex_quote(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:-]+", value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _ensure_output_path(payload: dict[str, Any], input_path: Path) -> Path:
    output_path = payload.get("output_path")
    output_dir = payload.get("output_dir")
    if output_path:
        return Path(output_path)
    if output_dir:
        return Path(output_dir) / input_path.with_suffix(".dxf").name
    return input_path.with_suffix(".dxf")


def _build_env(payload: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    env_overrides = {
        "DISPLAY": payload.get("display"),
        "XAUTHORITY": payload.get("xauthority"),
        "QT_QPA_PLATFORM": payload.get("qt_qpa_platform"),
    }
    for key, value in env_overrides.items():
        if value:
            env[key] = str(value)
    for key, value in payload.get("env", {}).items():
        env[str(key)] = str(value)
    return env


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _attempt_oda(
    payload: dict[str, Any],
    input_path: Path,
    output_path: Path,
    job_dir: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    oda_path = str(payload.get("oda_path") or DEFAULT_ODA_PATH)
    if not Path(oda_path).exists():
        return {
            "converter": "oda",
            "success": False,
            "reason": f"ODAFileConverter not found: {oda_path}",
        }

    staged_input_dir = job_dir / "oda-input"
    staged_output_dir = job_dir / "oda-output"
    staged_input_dir.mkdir(parents=True, exist_ok=True)
    staged_output_dir.mkdir(parents=True, exist_ok=True)

    staged_name = _sanitize_filename(input_path.name)
    if not staged_name.lower().endswith(".dwg"):
        staged_name = f"{Path(staged_name).stem or 'input'}.dwg"
    staged_input = staged_input_dir / staged_name
    shutil.copy2(input_path, staged_input)

    output_version = str(payload.get("output_version") or DEFAULT_OUTPUT_VERSION)
    recurse = "1" if payload.get("recurse") else "0"
    audit = "1" if payload.get("audit") else "0"
    command = [
        oda_path,
        str(staged_input_dir),
        str(staged_output_dir),
        output_version,
        "DXF",
        recurse,
        audit,
        staged_name,
    ]
    if payload.get("oda_no_gui", True):
        command.append("-n")

    env = _build_env(payload)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
            check=False,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        return {
            "converter": "oda",
            "success": False,
            "reason": f"timeout after {timeout_seconds}s",
            "command": _stringify_command(command),
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
        }

    produced_files = sorted(str(path.name) for path in staged_output_dir.glob("*.dxf"))
    if produced_files:
        produced_path = staged_output_dir / produced_files[0]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(produced_path), str(output_path))

    return {
        "converter": "oda",
        "success": output_path.exists(),
        "reason": "" if output_path.exists() else "exit without DXF output",
        "command": _stringify_command(command),
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "produced_files": produced_files,
        "staged_input_name": staged_name,
        "input_mode": "directory-batch",
    }


def _attempt_libredwg(
    payload: dict[str, Any],
    input_path: Path,
    output_path: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    libredwg_path = str(payload.get("libredwg_path") or DEFAULT_LIBREDWG_PATH)
    resolved = shutil.which(libredwg_path) if os.path.sep not in libredwg_path else libredwg_path
    if not resolved or not Path(resolved).exists():
        return {
            "converter": "libredwg",
            "success": False,
            "reason": f"dwg2dxf not found: {libredwg_path}",
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [resolved, "-y", "-o", str(output_path), str(input_path)]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        return {
            "converter": "libredwg",
            "success": False,
            "reason": f"timeout after {timeout_seconds}s",
            "command": _stringify_command(command),
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
        }

    return {
        "converter": "libredwg",
        "success": exit_code == 0 and output_path.exists(),
        "reason": "" if exit_code == 0 and output_path.exists() else "dwg2dxf did not create output",
        "command": _stringify_command(command),
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "produced_files": [output_path.name] if output_path.exists() else [],
    }


def run_dwg_to_dxf_task(payload: dict[str, Any]) -> dict[str, Any]:
    input_raw = payload.get("input_path")
    if not input_raw:
        raise ValueError("dwg_to_dxf 任務缺少 input_path")

    input_path = Path(input_raw)
    if not input_path.is_file():
        raise FileNotFoundError(f"找不到 DWG 檔案: {input_path}")

    output_path = _ensure_output_path(payload, input_path)
    overwrite = payload.get("overwrite", True)
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"輸出檔案已存在: {output_path}")
    if output_path.exists() and overwrite:
        output_path.unlink()

    timeout_seconds = int(payload.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
    preferred_converters = payload.get("preferred_converters") or ["oda", "libredwg"]
    if isinstance(preferred_converters, str):
        preferred_converters = [part.strip() for part in preferred_converters.split(",") if part.strip()]

    diagnostics_dir = Path(
        payload.get("diagnostics_dir")
        or output_path.parent / ".hermes-dwg-diagnostics" / output_path.stem
    )
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "task_type": "dwg_to_dxf",
        "status": "failed",
        "input_path": str(input_path),
        "output_path": str(output_path),
        "output_version": str(payload.get("output_version") or DEFAULT_OUTPUT_VERSION),
        "input_size_bytes": input_path.stat().st_size,
        "started_at": _utc_now_iso(),
        "attempts": [],
    }

    with tempfile.TemporaryDirectory(prefix="hermes-dwg-") as temp_dir:
        job_dir = Path(temp_dir)
        for converter in preferred_converters:
            if converter == "oda":
                attempt = _attempt_oda(payload, input_path, output_path, job_dir, timeout_seconds)
            elif converter == "libredwg":
                attempt = _attempt_libredwg(payload, input_path, output_path, timeout_seconds)
            else:
                attempt = {
                    "converter": str(converter),
                    "success": False,
                    "reason": f"unsupported converter: {converter}",
                }

            summary["attempts"].append(attempt)
            _write_json(diagnostics_dir / f"{converter}.json", attempt)

            if attempt.get("success"):
                summary.update(
                    {
                        "status": "completed",
                        "converter_used": converter,
                        "diagnostics_dir": str(diagnostics_dir),
                        "completed_at": _utc_now_iso(),
                        "produced_file": str(output_path),
                    }
                )
                _write_json(diagnostics_dir / "summary.json", summary)
                return summary

    summary.update(
        {
            "diagnostics_dir": str(diagnostics_dir),
            "completed_at": _utc_now_iso(),
            "error": "all converters failed",
        }
    )
    _write_json(diagnostics_dir / "summary.json", summary)
    return summary
