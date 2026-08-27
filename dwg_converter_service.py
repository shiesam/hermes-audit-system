#!/usr/bin/env python3
"""
LibreDWG DWG→DXF 轉換服務腳本
- 遞迴掃描輸入目錄下的所有 .dwg（不分大小寫）
- 跳過已存在且更新的 DXF（依 mtime 判斷）
- 轉換時使用臨時檔，成功後 rename，避免中途檔案被掃描
- 最多 4 個 worker 並行處理
- 失敗檔案寫入獨立 failed.log
- Log 採用 RotatingFileHandler（10MB, 備份 5）
"""

import os
import sys
import time
import logging
import subprocess
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from logging.handlers import RotatingFileHandler

# ===================== 設定區 =====================
INPUT_DIR = "/srv/samba/hermes-audit/"
OUTPUT_DIR = "/srv/samba/hermes-audit/.dxf-output/"
LOG_FILE = "/home/vboxuser/logs/dwg_converter.log"
FAILED_LOG_FILE = "/home/vboxuser/logs/dwg_converter_failed.log"
MAX_WORKERS = 4
DWG2DXF_BIN = "/usr/local/bin/dwg2dxf"
TIMEOUT_SEC = 45
# =============================================

# 確保輸出目錄存在
Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

# 建立 log 目錄
Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)

# 日誌設定：RotatingFileHandler(10MB, 備份 5)
logger = logging.getLogger("dwg_converter")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(LOG_FILE, maxBytes=10*1024*1024, backupCount=5)
handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
))
logger.addHandler(handler)
# 同時輸出到 stdout（systemd journal 會採集）
console = logging.StreamHandler(sys.stdout)
console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(console)

# 失敗日誌（獨立檔案，不回転）
failed_logger = logging.getLogger("dwg_failed")
failed_handler = logging.FileHandler(FAILED_LOG_FILE)
failed_handler.setFormatter(logging.Formatter(
    "%(asctime)s [FAILED] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
))
failed_logger.addHandler(failed_handler)
failed_logger.setLevel(logging.ERROR)


def convert_one_dwg(dwg_path: Path, dxf_path: Path) -> tuple:
    """
    轉換單一 DWG 為 DXF。
    - 先寫入臨時檔，成功後 rename
    - 超過 TIMEOUT_SEC 會被強制終止
    - 失敗時記錄到 failed.log
    回傳: (success: bool, skipped: bool)
    """
    dxf_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dxf = dxf_path.with_suffix(".dxf.tmp")

    try:
        result = subprocess.run(
            [DWG2DXF_BIN, str(dwg_path), "-o", str(tmp_dxf)],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SEC
        )

        if result.returncode == 0 and tmp_dxf.exists() and tmp_dxf.stat().st_size > 0:
            # 成功：rename 到正式檔名
            os.replace(tmp_dxf, dxf_path)
            logger.info(f"成功: {dwg_path.relative_to(INPUT_DIR)} -> {dxf_path.name} "
                        f"({dxf_path.stat().st_size / 1024:.1f} KB)")
            return True, False
        else:
            error_msg = result.stderr.strip() if result.stderr else "無輸出檔案"
            logger.error(f"失敗 [{dwg_path.relative_to(INPUT_DIR)}]: {error_msg}")
            failed_logger.error(f"{dwg_path} | {error_msg}")
            # 清理臨時檔
            if tmp_dxf.exists():
                tmp_dxf.unlink()
            return False, False

    except subprocess.TimeoutExpired:
        logger.error(f"逾時 [{dwg_path.relative_to(INPUT_DIR)}]: 超過 {TIMEOUT_SEC} 秒")
        failed_logger.error(f"{dwg_path} | timeout after {TIMEOUT_SEC}s")
        if tmp_dxf.exists():
            tmp_dxf.unlink()
        return False, False
    except Exception as e:
        logger.error(f"異常 [{dwg_path.relative_to(INPUT_DIR)}]: {str(e)}")
        failed_logger.error(f"{dwg_path} | exception: {str(e)}")
        if tmp_dxf.exists():
            tmp_dxf.unlink()
        return False, False


def should_convert(dwg_path: Path, dxf_path: Path) -> bool:
    """判斷是否需要重新轉換：若 DXF 已存在且其 mtime >= DWG mtime，則跳過"""
    if not dxf_path.exists():
        return True
    dwg_mtime = dwg_path.stat().st_mtime
    dxf_mtime = dxf_path.stat().st_mtime
    if dxf_mtime >= dwg_mtime:
        logger.debug(f"跳過已最新: {dwg_path.name} (DXF 較新或相同)")
        return False
    return True


def collect_dwg_files(input_dir: str) -> list:
    """遞迴收集所有 .dwg 檔案（不分大小寫）"""
    in_path = Path(input_dir)
    if not in_path.exists():
        logger.critical(f"輸入目錄不存在: {input_dir}")
        return []

    dwg_files = []
    for ext in ["*.dwg", "*.DWG"]:
        dwg_files.extend(in_path.rglob(ext))
    # 去重（因為 rglob 可能同時匹配大小寫，但實際檔案系統可能混用）
    unique_files = {}
    for f in dwg_files:
        unique_files[f.resolve()] = f
    return list(unique_files.values())


def worker_task(dwg_path: Path) -> tuple:
    """worker 函式：計算輸出路徑並執行轉換"""
    rel_path = dwg_path.relative_to(INPUT_DIR)
    dxf_path = Path(OUTPUT_DIR) / rel_path.with_suffix(".dxf")

    if not should_convert(dwg_path, dxf_path):
        logger.info(f"跳過已最新: {rel_path}")
        return False, True  # (success=False, skipped=True)

    return convert_one_dwg(dwg_path, dxf_path)


def main():
    logger.info("========================================")
    logger.info("開始執行 DWG 審計轉換作業")
    logger.info(f"輸入目錄: {INPUT_DIR}")
    logger.info(f"輸出目錄: {OUTPUT_DIR}")
    logger.info(f"最大併發 worker 數: {MAX_WORKERS}")
    logger.info("========================================")

    dwg_files = collect_dwg_files(INPUT_DIR)
    total_files = len(dwg_files)
    logger.info(f"共找到 {total_files} 個待處理的 DWG 檔案（含可能已最新）")

    if total_files == 0:
        logger.info("無任何 DWG 檔案，結束。")
        return

    success_count = 0
    skip_count = 0
    fail_count = 0
    start_time = time.time()

    # 使用 ProcessPoolExecutor 並行處理
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {executor.submit(worker_task, dwg): dwg for dwg in dwg_files}

        for future in as_completed(future_map):
            dwg = future_map[future]
            try:
                success, skipped = future.result()
                if skipped:
                    skip_count += 1
                elif success:
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                logger.error(f"Worker 執行異常 [{dwg}]: {str(e)}")
                fail_count += 1
                failed_logger.error(f"{dwg} | worker exception: {str(e)}")

    elapsed = time.time() - start_time
    logger.info("========================================")
    logger.info(f"作業完成！耗時: {elapsed:.2f} 秒")
    logger.info(f"成功: {success_count}, 跳過: {skip_count}, 失敗: {fail_count}")
    logger.info("========================================")


if __name__ == "__main__":
    main()
