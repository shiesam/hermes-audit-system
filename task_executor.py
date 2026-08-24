#!/usr/bin/env python3
"""
主機任務執行器
讀取 daily_tasks.csv，識別「待主機」的任務，自動執行

功能：
  1. 讀取 CSV 裡狀態為「待主機」的所有工作
  2. 根據「工作內容」判斷執行什麼任務
  3. 調用對應的執行模組
  4. 更新 CSV 狀態（執行中 → 完成）
  5. 生成執行日誌
"""

import os
import sys
import csv
from datetime import datetime
from pathlib import Path

# 添加 src 路徑
sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent / "tasks"))

# 導入具體的任務執行模組
try:
    from tasks.pdf_converter import PDFConverter
    from tasks.photo_organizer import PhotoOrganizer
    from tasks.report_generator import ReportGenerator
except ImportError as e:
    print(f"⚠️ 警告：無法導入任務模組 {e}")
    PDFConverter = None
    PhotoOrganizer = None
    ReportGenerator = None

class TaskExecutor:
    """主機任務執行器"""
    
    def __init__(self, csv_path: str, log_dir: str = "/var/log/hermes-tasks"):
        self.csv_path = Path(csv_path)
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.today = datetime.now().strftime("%Y-%m-%d")
        self.now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        print(f"[初始化] 任務執行器啟動")
        print(f"[初始化] CSV路徑: {self.csv_path}")
        print(f"[初始化] 日誌目錄: {self.log_dir}")
    
    def read_pending_tasks(self):
        """讀取 CSV 裡所有「待主機」的任務"""
        try:
            if not os.path.exists(self.csv_path):
                print(f"❌ 錯誤：CSV 檔案不存在 {self.csv_path}")
                return []
            
            pending_tasks = []
            with open(self.csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # 找出所有狀態為「待主機」的任務
                    if row.get('狀態') == '待主機':
                        pending_tasks.append(row)
            
            print(f"✅ 找到 {len(pending_tasks)} 項待執行任務")
            return pending_tasks
            
        except Exception as e:
            print(f"❌ 錯誤（讀取 CSV）: {e}")
            return []
    
    def execute_task(self, task):
        """根據任務內容，執行對應的操作"""
        
        案場 = task.get('案場', '未知')
        工作內容 = task.get('工作內容', '').strip()
        備註 = task.get('備註', '')
        
        print(f"\n{'='*60}")
        print(f"[執行] {案場} - {工作內容}")
        print(f"[執行] 備註: {備註}")
        print(f"{'='*60}")
        
        result = {
            'success': False,
            'message': '未知任務類型',
            'output': ''
        }
        
        # 根據工作內容判斷執行什麼任務
        if '轉 PDF' in 工作內容 or 'PDF' in 工作內容:
            result = self._execute_pdf_conversion(案場, 工作內容, 備註)
        
        elif '照片' in 工作內容 and ('整理' in 工作內容 or '分類' in 工作內容):
            result = self._execute_photo_organization(案場, 工作內容, 備註)
        
        elif '報告' in 工作內容 or '月報' in 工作內容 or '統計' in 工作內容:
            result = self._execute_report_generation(案場, 工作內容, 備註)
        
        else:
            print(f"⚠️ 警告：不認識的任務類型 '{工作內容}'")
            result['message'] = f"不認識的任務類型: {工作內容}"
        
        return result
    
    def _execute_pdf_conversion(self, 案場, 工作內容, 備註):
        """執行 DWG 轉 PDF"""
        
        if PDFConverter is None:
            return {
                'success': False,
                'message': '無法載入 PDF 轉換模組',
                'output': '模組載入失敗'
            }
        
        try:
            converter = PDFConverter(case_name=案場)
            result = converter.convert()
            
            if result['success']:
                print(f"✅ PDF 轉換成功: {result['output_count']} 個檔案")
                return {
                    'success': True,
                    'message': f"成功轉換 {result['output_count']} 個 PDF 檔案",
                    'output': result['output_dir']
                }
            else:
                print(f"❌ PDF 轉換失敗: {result['error']}")
                return {
                    'success': False,
                    'message': f"轉換失敗: {result['error']}",
                    'output': ''
                }
        
        except Exception as e:
            print(f"❌ 執行錯誤: {e}")
            return {
                'success': False,
                'message': f"執行異常: {str(e)}",
                'output': ''
            }
    
    def _execute_photo_organization(self, 案場, 工作內容, 備註):
        """執行照片整理分類"""
        
        if PhotoOrganizer is None:
            return {
                'success': False,
                'message': '無法載入照片整理模組',
                'output': '模組載入失敗'
            }
        
        try:
            organizer = PhotoOrganizer(case_name=案場)
            result = organizer.organize()
            
            if result['success']:
                print(f"✅ 照片整理成功: {result['organized_count']} 張照片")
                return {
                    'success': True,
                    'message': f"成功整理 {result['organized_count']} 張照片",
                    'output': result['output_dir']
                }
            else:
                print(f"❌ 照片整理失敗: {result['error']}")
                return {
                    'success': False,
                    'message': f"整理失敗: {result['error']}",
                    'output': ''
                }
        
        except Exception as e:
            print(f"❌ 執行錯誤: {e}")
            return {
                'success': False,
                'message': f"執行異常: {str(e)}",
                'output': ''
            }
    
    def _execute_report_generation(self, 案場, 工作內容, 備註):
        """執行報告生成"""
        
        if ReportGenerator is None:
            return {
                'success': False,
                'message': '無法載入報告生成模組',
                'output': '模組載入失敗'
            }
        
        try:
            generator = ReportGenerator(case_name=案場)
            result = generator.generate()
            
            if result['success']:
                print(f"✅ 報告生成成功: {result['report_file']}")
                return {
                    'success': True,
                    'message': f"成功生成報告",
                    'output': result['report_file']
                }
            else:
                print(f"❌ 報告生成失敗: {result['error']}")
                return {
                    'success': False,
                    'message': f"生成失敗: {result['error']}",
                    'output': ''
                }
        
        except Exception as e:
            print(f"❌ 執行錯誤: {e}")
            return {
                'success': False,
                'message': f"執行異常: {str(e)}",
                'output': ''
            }
    
    def update_csv_status(self, task, new_status, result):
        """更新 CSV 裡的任務狀態"""
        
        try:
            # 讀取所有行
            all_rows = []
            with open(self.csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                for row in reader:
                    # 如果是要更新的任務，改變狀態
                    if (row.get('日期') == task.get('日期') and
                        row.get('案場') == task.get('案場') and
                        row.get('工作內容') == task.get('工作內容')):
                        row['狀態'] = new_status
                        if new_status == '完成':
                            row['備註'] = f"{task.get('備註')} | {result['message']}"
                    all_rows.append(row)
            
            # 寫回 CSV
            with open(self.csv_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(all_rows)
            
            print(f"✅ CSV 已更新: 狀態 → {new_status}")
            return True
        
        except Exception as e:
            print(f"❌ 更新 CSV 失敗: {e}")
            return False
    
    def log_execution(self, task, result):
        """記錄執行日誌"""
        
        log_file = self.log_dir / f"task_executor_{self.today}.log"
        
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"[{self.now}] 任務: {task.get('案場')} - {task.get('工作內容')}\n")
                f.write(f"[結果] 成功: {result['success']}\n")
                f.write(f"[訊息] {result['message']}\n")
                if result['output']:
                    f.write(f"[輸出] {result['output']}\n")
                f.write(f"{'='*60}\n")
            
            print(f"✅ 日誌已記錄: {log_file}")
        
        except Exception as e:
            print(f"⚠️ 日誌記錄失敗: {e}")
    
    def run(self):
        """執行所有待機任務"""
        
        print(f"\n{'='*70}")
        print(f"  主機任務執行器 - {self.now}")
        print(f"{'='*70}\n")
        
        # 讀取待機任務
        pending_tasks = self.read_pending_tasks()
        
        if not pending_tasks:
            print("✅ 無待執行任務")
            return True
        
        # 執行每個任務
        success_count = 0
        for task in pending_tasks:
            result = self.execute_task(task)
            self.log_execution(task, result)
            
            # 根據執行結果更新 CSV
            if result['success']:
                self.update_csv_status(task, '完成', result)
                success_count += 1
            else:
                self.update_csv_status(task, '失敗', result)
        
        print(f"\n{'='*70}")
        print(f"✅ 執行完成: {success_count}/{len(pending_tasks)} 個任務成功")
        print(f"{'='*70}\n")
        
        return success_count == len(pending_tasks)

def main():
    """主程式"""
    csv_path = "/srv/samba/hermes-audit/daily_tasks.csv"
    
    executor = TaskExecutor(csv_path)
    success = executor.run()
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
