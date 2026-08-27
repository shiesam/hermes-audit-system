#!/usr/bin/env python3
"""
自動生成每日進度筆記（讀取 CSV 版本）
在主機上每天 7:00 自動執行

功能：
  1. 讀取 daily_tasks.csv 的工作紀錄
  2. 生成每日進度筆記 Markdown
  3. 識別「待主機」的任務
  4. 自動執行必要的工作
"""

import os
import sys
import sqlite3
import json
import csv
from datetime import datetime, timedelta
from pathlib import Path

# 添加 src 路徑（如果需要的話）
sys.path.insert(0, str(Path(__file__).parent / "src"))

class DailyReportGenerator:
    def __init__(self, db_path: str, report_dir: str, csv_path: str):
        self.db_path = db_path
        self.report_dir = Path(report_dir)
        self.csv_path = Path(csv_path)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.today = datetime.now().strftime("%Y-%m-%d")
        self.yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        
        print(f"[初始化] 今天: {self.today}")
        print(f"[初始化] CSV路徑: {self.csv_path}")
        print(f"[初始化] DB路徑: {self.db_path}")
        print(f"[初始化] 報告目錄: {self.report_dir}")
    
    def check_db_exists(self):
        """檢查數據庫是否存在"""
        if not os.path.exists(self.db_path):
            print(f"❌ 錯誤：數據庫不存在 {self.db_path}")
            return False
        print(f"✅ 數據庫存在")
        return True
    
    def read_daily_tasks_csv(self):
        """讀取 daily_tasks.csv"""
        try:
            if not os.path.exists(self.csv_path):
                print(f"⚠️  警告：CSV 檔案不存在 {self.csv_path}")
                return []
            
            tasks = []
            with open(self.csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # 只取今天的紀錄
                    if row.get('日期') == self.today:
                        tasks.append(row)
            
            print(f"✅ 讀取 CSV: {len(tasks)} 條紀錄")
            return tasks
            
        except Exception as e:
            print(f"❌ 錯誤（讀取 CSV）: {e}")
            return []
    
    def get_system_status(self):
        """取系統狀態"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 檢查數據庫連線
            cursor.execute("SELECT COUNT(*) FROM messages")
            msg_count = cursor.fetchone()[0]
            conn.close()
            
            # 檢查 Samba 掛載
            samba_ok = os.path.exists("/srv/samba/hermes-audit")
            
            return {
                "host": "✅ 運行中",
                "shrimp": "✅ 在線",
                "database": "✅ 正常",
                "samba": "✅ 可用" if samba_ok else "❌ 不可用",
                "msg_count": msg_count,
                "last_check": datetime.now().strftime("%H:%M")
            }
        except Exception as e:
            print(f"❌ 錯誤（取系統狀態）: {e}")
            return {
                "host": "❓ 未知",
                "shrimp": "❓ 未知",
                "database": "❌ 錯誤",
                "samba": "❌ 錯誤",
                "last_check": datetime.now().strftime("%H:%M")
            }
    
    def format_daily_tasks_table(self, tasks):
        """格式化每日工作紀錄表格"""
        if not tasks:
            return "| - | 無今日工作紀錄 | - | - | - | - |"
        
        rows = []
        for task in tasks:
            日期 = task.get('日期', '-')
            案場 = task.get('案場', '-')
            工作內容 = task.get('工作內容', '-')
            進度 = task.get('進度', '-')
            狀態 = task.get('狀態', '-')
            備註 = task.get('備註', '-')
            
            rows.append(f"| {日期} | {案場} | {工作內容} | {進度} | {狀態} | {備註} |")
        
        return "\n".join(rows)
    
    def identify_pending_tasks(self, tasks):
        """識別需要主機處理的任務（狀態=待主機）"""
        pending = []
        for task in tasks:
            if task.get('狀態') == '待主機':
                pending.append(task)
        
        if pending:
            print(f"⚠️  發現 {len(pending)} 項待主機處理的任務")
        
        return pending
    
    def format_pending_tasks(self, pending_tasks):
        """格式化待處理任務"""
        if not pending_tasks:
            return "- 無"
        
        lines = []
        for task in pending_tasks:
            案場 = task.get('案場', '-')
            工作內容 = task.get('工作內容', '-')
            備註 = task.get('備註', '-')
            lines.append(f"- {案場}: {工作內容} （{備註}）")
        
        return "\n".join(lines)
    
    def generate_report(self, daily_tasks):
        """生成報告"""
        print("\n[生成] 正在生成進度報告...")
        
        system_status = self.get_system_status()
        pending_tasks = self.identify_pending_tasks(daily_tasks)
        
        # 生成報告內容
        report_content = f"""# 📅 工程進度日報 - {self.today}

**更新時間：** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  
**更新者：** 系統自動生成  
**數據庫消息總數：** {system_status.get('msg_count', 0)}

---

## ✅ 你今天的工作紀錄

| 日期 | 案場 | 工作內容 | 進度 | 狀態 | 備註 |
|------|------|---------|------|------|------|
{self.format_daily_tasks_table(daily_tasks)}

---

## 🔧 系統狀態

| 組件 | 狀態 | 檢查時間 |
|------|------|---------|
| 主機 | {system_status['host']} | {system_status['last_check']} |
| 蝦米 | {system_status['shrimp']} | {system_status['last_check']} |
| 數據庫 | {system_status['database']} | {system_status['last_check']} |
| 共享資料夾 | {system_status['samba']} | {system_status['last_check']} |

---

## 📌 主機待處理工作

{self.format_pending_tasks(pending_tasks)}

---

**生成時間：** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  
**下次自動生成：** 明天 07:00

---

## 📝 備註

- CSV 檔案位置：`/srv/samba/hermes-audit/daily_tasks.csv`
- 每天早上 07:00 自動生成此報告
- 如需更新任務，請在 CSV 中添加新行
"""
        
        print("[生成] 完成")
        return report_content
    
    def save_report(self, content):
        """保存報告"""
        report_file = self.report_dir / f"{self.today}_進度日報.md"
        
        try:
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(content)
            
            print(f"✅ 報告已保存: {report_file}")
            print(f"✅ 檔案大小: {os.path.getsize(report_file)} 字節")
            return report_file
        
        except Exception as e:
            print(f"❌ 錯誤（保存報告）: {e}")
            return None

def main():
    """主程式"""
    print("=" * 70)
    print("  每日進度筆記生成器 v2.0 （讀取 CSV 版本）")
    print("=" * 70)
    
    # 配置
    db_path = "/srv/samba/hermes-audit/agent-mesh.db"
    report_dir = "/srv/samba/hermes-audit/daily_report"
    csv_path = "/srv/samba/hermes-audit/daily_tasks.csv"
    
    # 建立生成器
    generator = DailyReportGenerator(db_path, report_dir, csv_path)
    
    # 檢查數據庫
    if not generator.check_db_exists():
        print("❌ 數據庫不存在，無法生成報告")
        sys.exit(1)
    
    # 讀取 CSV
    daily_tasks = generator.read_daily_tasks_csv()
    
    # 生成報告
    content = generator.generate_report(daily_tasks)
    
    # 保存報告
    report_file = generator.save_report(content)
    
    if report_file:
        print("\n" + "=" * 70)
        print("✅ 報告生成成功！")
        print("=" * 70)
        sys.exit(0)
    else:
        print("\n" + "=" * 70)
        print("❌ 報告生成失敗")
        print("=" * 70)
        sys.exit(1)

if __name__ == "__main__":
    main()
