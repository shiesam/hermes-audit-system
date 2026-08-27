#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent
SRC_PATH = REPO_ROOT / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

import agent_executor
from hermes_audit_system.dwg_conversion import run_dwg_to_dxf_task


class DWGConversionTests(unittest.TestCase):
    def test_oda_stages_special_filename_and_moves_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            input_path = base / "CH13-01-1(G1-01).dwg"
            output_path = base / "converted" / "result.dxf"
            oda_path = base / "ODAFileConverter"
            input_path.write_bytes(b"AC1027")
            oda_path.write_text("", encoding="utf-8")

            def fake_run(command, **kwargs):
                self.assertEqual(command[-1], "-n")
                self.assertEqual(command[-2], "CH13-01-1_G1-01.dwg")
                staged_output_dir = Path(command[2])
                staged_output_dir.mkdir(parents=True, exist_ok=True)
                (staged_output_dir / "CH13-01-1_G1-01.dxf").write_text("0\nSECTION\n", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch("subprocess.run", side_effect=fake_run):
                result = run_dwg_to_dxf_task(
                    {
                        "input_path": str(input_path),
                        "output_path": str(output_path),
                        "preferred_converters": ["oda"],
                        "oda_path": str(oda_path),
                    }
                )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["converter_used"], "oda")
            self.assertTrue(output_path.exists())

    def test_falls_back_to_libredwg_when_oda_exits_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            input_path = base / "input.dwg"
            output_path = base / "output.dxf"
            oda_path = base / "ODAFileConverter"
            libredwg_path = base / "dwg2dxf"
            input_path.write_bytes(b"AC1027")
            oda_path.write_text("", encoding="utf-8")
            libredwg_path.write_text("", encoding="utf-8")

            def fake_run(command, **kwargs):
                if Path(command[0]) == oda_path:
                    return subprocess.CompletedProcess(command, 0, "", "")
                output_path.write_text("0\nSECTION\n", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch("subprocess.run", side_effect=fake_run), patch(
                "shutil.which", return_value=str(libredwg_path)
            ):
                result = run_dwg_to_dxf_task(
                    {
                        "input_path": str(input_path),
                        "output_path": str(output_path),
                        "preferred_converters": ["oda", "libredwg"],
                        "oda_path": str(oda_path),
                    }
                )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["converter_used"], "libredwg")
            self.assertEqual(len(result["attempts"]), 2)
            self.assertTrue(output_path.exists())

    def test_agent_executor_uses_task_type_key(self) -> None:
        with patch.object(agent_executor, "run_dwg_to_dxf_task", return_value={"status": "completed"}) as mocked:
            result = agent_executor.do_work(
                {
                    "task_type": "dwg_to_dxf",
                    "input_path": "/tmp/in.dwg",
                }
            )

        mocked.assert_called_once()
        self.assertEqual(result["status"], "completed")


if __name__ == "__main__":
    unittest.main()
