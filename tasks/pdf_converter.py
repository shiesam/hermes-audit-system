#!/usr/bin/env python3
"""
PDF 轉換模組（增強版）
負責將 PDF 轉換為文字檔（pdftotext）
"""

import os
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# pdftotext 命令預設位置（主機端）
PDFTOTEXT_CMD = "/usr/bin/pdftotext"


class PDFConverter:
    """PDF 轉換處理器 - 將 PDF 轉為文字檔"""

    def __init__(self, output_dir: str = None, pdftotext_cmd: str = PDFTOTEXT_CMD):
        self.output_dir = output_dir or str(Path.home() / "pdf_output")
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        self.pdftotext_cmd = pdftotext_cmd

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        執行 PDF 轉換任務
        
        支援的任務欄位：
        - 案場: 案場名稱（例如 法規技術規則）
        - 工作內容: 工作描述
        - 路徑: 要處理的 PDF 目錄（例如 /srv/samba/hermes-audit/memory-bank/domainKnowledge/regulations）
        - 備註: 其他資訊
        
        若無提供路徑，則預設處理 regulations/ 目錄
        """
        try:
            logger.info(f"PDF 轉換任務啟動: {task.get('案場')} - {task.get('工作內容')}")
            
            # 取得目標目錄
            target_dir = task.get('路徑', '')
            if not target_dir:
                # 預設：法規技術規則的 regulations 目錄
                target_dir = "/srv/samba/hermes-audit/memory-bank/domainKnowledge/regulations"
            
            logger.info(f"目標目錄: {target_dir}")
            
            if not os.path.isdir(target_dir):
                return {
                    'status': 'error',
                    'message': f'目錄不存在: {target_dir}'
                }
            
            # 找出所有 PDF 檔案
            pdf_files = []
            for root, dirs, files in os.walk(target_dir):
                for f in files:
                    if f.lower().endswith('.pdf'):
                        pdf_files.append(os.path.join(root, f))
            
            if not pdf_files:
                return {
                    'status': 'ok',
                    'message': f'沒有找到 PDF 檔案，目錄: {target_dir}',
                    'output_count': 0
                }
            
            logger.info(f"找到 {len(pdf_files)} 個 PDF 檔案，開始轉換")
            
            success_count = 0
            fail_count = 0
            converted_files = []
            
            for pdf_path in pdf_files:
                txt_path = pdf_path[:-4] + '.txt'
                try:
                    result = subprocess.run(
                        [self.pdftotext_cmd, "-layout", pdf_path, txt_path],
                        capture_output=True,
                        text=True,
                        timeout=60
                    )
                    if result.returncode == 0 and os.path.exists(txt_path):
                        success_count += 1
                        converted_files.append(txt_path)
                        logger.info(f"轉換成功: {os.path.basename(pdf_path)}")
                    else:
                        fail_count += 1
                        logger.error(f"轉換失敗: {os.path.basename(pdf_path)} - {result.stderr}")
                except Exception as e:
                    fail_count += 1
                    logger.error(f"轉換錯誤: {os.path.basename(pdf_path)} - {e}")
            
            logger.info(f"PDF 轉換完成: 成功 {success_count} 件，失敗 {fail_count} 件")
            
            return {
                'status': 'ok' if fail_count == 0 else 'partial',
                'message': f'PDF 轉換完成：{task.get("案場")}，共 {len(pdf_files)} 件，成功 {success_count} 件',
                'output_count': success_count,
                'total_count': len(pdf_files),
                'success_count': success_count,
                'fail_count': fail_count,
                'converted_files': converted_files[:10]  # 僅列前 10 個
            }
            
        except Exception as e:
            logger.error(f"PDF 轉換失敗: {e}")
            return {
                'status': 'error',
                'message': f'PDF 轉換失敗：{str(e)}'
            }

    def check_dependencies(self) -> bool:
        """檢查必要的依賴是否就緒"""
        try:
            # 檢查 pdftotext 是否存在
            result = subprocess.run(
                [self.pdftotext_cmd, "--version"],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except Exception:
            logger.warning("pdftotext 未找到")
            return False


if __name__ == "__main__":
    # 測試執行
    import sys
    converter = PDFConverter()
    print(f"pdftotext 檢測: {'就緒' if converter.check_dependencies() else '未就緒'}")
