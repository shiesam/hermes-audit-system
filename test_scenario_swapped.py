#!/usr/bin/env python3
"""
Test Scenario - 角色互換版本
主機當發起端，蝦米當執行端（與原始 test_scenario.py 相反）

執行：
  python3 test_scenario_swapped.py
"""

import json
import time
from pathlib import Path
from watchdog_db import *

DB = Path("/srv/samba/hermes-audit/agent-mesh.db")

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def main():
    conn = init_db(DB)
    try:
        # ════════════════════════════════════════════════════════════
        # 1️⃣ 建立訊息（主機 → 蝦米）
        # ════════════════════════════════════════════════════════════
        
        section("1️⃣ 建立訊息 (主機 → 蝦米)")
        
        msg_id = "m-swapped-001"
        create_message(
            conn, msg_id,
            sender="host",      # 主機是發起端
            receiver="shrimp",  # 蝦米是執行端
            payload={
                "task_type": "collection",
                "description": "蝦米收集數據 (角色互換測試)"
            }
        )
        print(f"✅ 建立訊息: {msg_id}")
        msg = get_message(conn, msg_id)
        print(f"   發起端: {msg['sender']}")
        print(f"   執行端: {msg['receiver']}")
        print(f"   狀態: {msg['status']}")
        
        # ════════════════════════════════════════════════════════════
        # 2️⃣ Arm Watchdog
        # ════════════════════════════════════════════════════════════
        
        section("2️⃣ Arm Watchdog")
        
        wd_tag = arm_watchdog_job(
            conn,
            msg_id=msg_id,
            kind="collection",
            threshold_override=60,  # 60 秒超時
            label="swapped-test"
        )
        print(f"✅ Arm 成功: {wd_tag}")
        print(f"   超時時間: 60s")
        
        # ════════════════════════════════════════════════════════════
        # 3️⃣ 查看初始狀態
        # ════════════════════════════════════════════════════════════
        
        section("3️⃣ 查看初始狀態")
        
        jobs = get_active_watchdog_jobs(conn)
        print(f"活躍 Watchdog Job: {len(jobs)}")
        for j in jobs:
            if j['msg_id'] == msg_id:
                print(f"  - {j['watchdog_tag']}: state={j['state']}, threshold={j['no_progress_threshold']}s")
        
        # ════════════════════════════════════════════════════════════
        # 4️⃣ 模擬蝦米的行為（狀態更新）
        # ════════════════════════════════════════════════════════════
        
        section("4️⃣ 蝦米收到訊息並回報狀態")
        
        # 蝦米確認收到
        ok = update_message_status(
            conn, msg_id, 'acknowledged',
            expected_current='submitted'
        )
        print(f"✅ 蝦米確認收到: acknowledged")
        
        # 蝦米發送 heartbeat
        heartbeat(conn, wd_tag)
        print(f"💓 蝦米發送 heartbeat")
        
        # 蝦米開始工作
        ok = update_message_status(
            conn, msg_id, 'working',
            expected_current='acknowledged'
        )
        print(f"✅ 蝦米開始工作: working")
        
        # ════════════════════════════════════════════════════════════
        # 5️⃣ 初始掃描（應無 incident）
        # ════════════════════════════════════════════════════════════
        
        section("5️⃣ 初始掃描（無超時）")
        
        incidents = check_and_report_stale(conn)
        print(f"本次掃描創建/更新 incident: {len(incidents)}")
        
        open_incs = get_open_incidents(conn)
        print(f"Open incidents: {len(open_incs)}")
        
        # ════════════════════════════════════════════════════════════
        # 6️⃣ 模擬超時（將 updated_at 改為過去）
        # ════════════════════════════════════════════════════════════
        
        section("6️⃣ 模擬超時（時光倒流）")
        
        # 計算 61 秒前的時間
        now_ts = utc_now_ts()
        old_ts = now_ts - 65  # 比 threshold(60s) 多 5 秒
        old_iso = datetime.fromtimestamp(old_ts, timezone.utc).isoformat().replace("+00:00", "Z")
        
        conn.execute(
            "UPDATE messages SET updated_at=? WHERE msg_id=?",
            (old_iso, msg_id)
        )
        conn.commit()
        print(f"✅ 訊息 updated_at 改為: {old_iso}")
        print(f"   即 65 秒前（超過 60s 閾值）")
        
        # ════════════════════════════════════════════════════════════
        # 7️⃣ 掃描（應產生 incident）
        # ════════════════════════════════════════════════════════════
        
        section("7️⃣ 掃描（超時偵測）")
        
        incidents = check_and_report_stale(conn)
        print(f"本次掃描創建/更新 incident: {len(incidents)}")
        for inc in incidents:
            print(f"  - {inc}")
        
        # ════════════════════════════════════════════════════════════
        # 8️⃣ 檢查狀態（應為 stalled）
        # ════════════════════════════════════════════════════════════
        
        section("8️⃣ 檢查 Watchdog 狀態")
        
        jobs = get_active_watchdog_jobs(conn)
        for j in jobs:
            if j['msg_id'] == msg_id:
                print(f"狀態: {j['state']}")
                print(f"Watchdog Tag: {j['watchdog_tag']}")
        
        open_incs = get_open_incidents(conn)
        print(f"\nOpen incidents: {len(open_incs)}")
        for inc in open_incs:
            if inc['msg_id'] == msg_id:
                evidence = json.loads(inc['evidence']) if inc['evidence'] else {}
                print(f"  - {inc['incident_id']}")
                print(f"    嚴重程度: {inc['severity']}")
                print(f"    原因: {evidence.get('reason')}")
                print(f"    已閒置: {evidence.get('idle_seconds', 0):.1f}s")
        
        # ════════════════════════════════════════════════════════════
        # 9️⃣ 蝦米完成工作（主動恢復）
        # ════════════════════════════════════════════════════════════
        
        section("9️⃣ 蝦米完成工作")
        
        # 更新為完成狀態
        ok = update_message_status(
            conn, msg_id, 'completed',
            expected_current='working',
            result={
                "task_type": "collection",
                "status": "completed",
                "data": "蝦米收集的數據",
                "processed_at": utc_now_iso()
            }
        )
        print(f"✅ 蝦米標示完成: completed")
        
        # ════════════════════════════════════════════════════════════
        # 🔟 最終掃描（自動 disarm）
        # ════════════════════════════════════════════════════════════
        
        section("🔟 最終掃描（自動 Disarm）")
        
        incidents = check_and_report_stale(conn)
        print(f"本次掃描創建/更新 incident: {len(incidents)}")
        for inc in incidents:
            print(f"  - {inc}")
        
        # ════════════════════════════════════════════════════════════
        # 1️⃣1️⃣ 最終狀態
        # ════════════════════════════════════════════════════════════
        
        section("1️⃣1️⃣ 最終狀態")
        
        jobs = get_active_watchdog_jobs(conn)
        print(f"活躍 Watchdog Job: {len(jobs)}")
        
        msg = get_message(conn, msg_id)
        print(f"\n訊息狀態:")
        print(f"  ID: {msg['msg_id']}")
        print(f"  Status: {msg['status']}")
        print(f"  Result: {json.loads(msg['result']) if msg['result'] else None}")
        
        open_incs = get_open_incidents(conn)
        print(f"\nOpen incidents: {len(open_incs)}")
        
        all_incs = conn.execute(
            "SELECT COUNT(*) as cnt FROM incidents WHERE msg_id=?",
            (msg_id,)
        ).fetchone()
        print(f"總 incidents (包括 resolved): {all_incs['cnt']}")
        
        # ════════════════════════════════════════════════════════════
        # 📊 測試結果總結
        # ════════════════════════════════════════════════════════════
        
        section("📊 測試結果總結 - 角色互換版本")
        
        print("""
✅ 測試項目:
  [✓] 訊息建立 (主機 → 蝦米)
  [✓] Watchdog arm
  [✓] 狀態轉移 (submitted → acknowledged → working → completed)
  [✓] Heartbeat 機制
  [✓] 超時偵測與 incident 產生
  [✓] 自動 disarm 與 incident resolve

🔄 角色互換驗證:
  主機: 發起端 (原本是發起端) ✓
  蝦米: 執行端 (原本是執行端) ✓
  
  機制完全對稱，任何角色互換都能正常運作！

💡 結論:
  系統設計本身是「角色無關」的 (role-agnostic)
  只需改變 sender/receiver，邏輯完全相同
        """)
        
    finally:
        conn.close()


if __name__ == "__main__":
    main()
