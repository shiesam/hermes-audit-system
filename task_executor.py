#!/usr/bin/env python3
"""
任務執行器 - 讀取 daily_tasks.csv 並執行待主機任務
"""

import os
import sys
import csv
import logging
from datetime import datetime
from pathlib import Path

# 確保可以匯入 tasks 模組
sys.path.insert(0, str(Path(__file__).parent))

LOG_DIR = "/home/vboxuser/logs/hermes-tasks"
LOG_FILE = f"{LOG_DIR}/task_executor_{datetime.now().strftime('%Y-%m-%d')}.log"

Path(LOG_DIR).mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

CSV_PATH = "/srv/samba/hermes-audit/daily_tasks.csv"


def read_pending_tasks():
    """讀取 CSV，找出所有狀態為「待主機」的任務"""
    pending = []
    if not os.path.exists(CSV_PATH):
        logger.warning(f"CSV 檔案不存在: {CSV_PATH}")
        return pending

    with open(CSV_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('狀態') == '待主機':
                pending.append(row)

    logger.info(f"找到 {len(pending)} 項待主機任務")
    return pending


def determine_module(task_content):
    """根據工作內容判斷要執行什麼模組"""
    content = task_content.lower()
    if '轉 pdf' in content or 'pdf' in content:
        return 'pdf_converter'
    elif '照片' in content and '整理' in content:
        return 'photo_organizer'
    elif '報告' in content or '月報' in content or '統計' in content:
        return 'report_generator'
    else:
        return None


def execute_pdf_converter(task):
    """PDF 轉換模組"""
    try:
        from tasks.pdf_converter import PDFConverter
        converter = PDFConverter()
        return converter.execute(task)
    except Exception as e:
        logger.error(f"PDF 轉換失敗: {e}")
        return {'status': 'error', 'message': str(e)}


def execute_photo_organizer(task):
    """照片整理模組"""
    try:
        from tasks.photo_organizer import PhotoOrganizer
        organizer = PhotoOrganizer()
        return organizer.execute(task)
    except Exception as e:
        logger.error(f"照片整理失敗: {e}")
        return {'status': 'error', 'message': str(e)}


def execute_report_generator(task):
    """報告生成模組"""
    try:
        from tasks.report_generator import ReportGenerator
        generator = ReportGenerator()
        return generator.execute(task)
    except Exception as e:
        logger.error(f"報告生成失敗: {e}")
        return {'status': 'error', 'message': str(e)}


def execute_task(task):
    """執行單一任務"""
    module_name = determine_module(task.get('工作內容', ''))

    if module_name is None:
        logger.error(f"無法識別任務類型: {task.get('工作內容')}")
        return False

    logger.info(f"調用模組: {module_name}")

    if module_name == 'pdf_converter':
        result = execute_pdf_converter(task)
    elif module_name == 'photo_organizer':
        result = execute_photo_organizer(task)
    elif module_name == 'report_generator':
        result = execute_report_generator(task)
    else:
        logger.error(f"未知模組: {module_name}")
        return False

    # 檢查結果
    status = result.get('status', 'error')
    logger.info(f"任務結果: {status} - {result.get('message', '')}")
    return status == 'ok'


def update_csv_status(task_id, new_status):
    """更新 CSV 中任務的狀態"""
    rows = []
    if not os.path.exists(CSV_PATH):
        logger.warning(f"CSV 檔案不存在: {CSV_PATH}")
        return False

    with open(CSV_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            if row.get('id') == task_id:
                row['狀態'] = new_status
                logger.info(f"更新任務 {task_id} 狀態 -> {new_status}")
            rows.append(row)

    with open(CSV_PATH, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return True


def main():
    logger.info("=" * 60)
    logger.info("任務執行器開始運行")
    logger.info("=" * 60)

    pending_tasks = read_pending_tasks()

    if not pending_tasks:
        logger.info("無待主機任務，結束")
        return

    for task in pending_tasks:
        task_id = task.get('id', 'unknown')
        logger.info(f"處理任務: {task_id} - {task.get('案場')} - {task.get('工作內容')}")

        success = execute_task(task)
        new_status = '完成' if success else '失敗'
        update_csv_status(task_id, new_status)
        logger.info(f"任務 {task_id} 處理結束，狀態: {new_status}")

    logger.info("任務執行器運行結束")


if __name__ == "__main__":
    main()