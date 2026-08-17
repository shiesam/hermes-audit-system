#!/usr/bin/env python3
import sys, os
sys.path.insert(0, '/home/vboxuser/agent-mesh')
from watchdog_db import *

DB = Path('/home/vboxuser/agent-mesh/agent-mesh.db')

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def main():
    conn = init_db(DB)
    try:
        # 1. 메시지 생성
        section("1. 메시지 생성 m-001")
        create_message(conn, "m-001", "A", "B", {"task_type":"collection","description":"테스트"})
        print("생성 완료")
        print(get_message(conn, "m-001"))
        
        # 2. arm watchdog
        section("2. arm watchdog")
        tag = arm_watchdog_job(conn, "m-001", kind="collection")
        print(f"arm 태그: {tag}")
        
        # 3. status 확인
        section("3. status (초기)")
        status(conn)
        
        # 4. 상태 업데이트: submitted → acknowledged → working
        section("4. 상태 업데이트")
        ok1 = update_message_status(conn, "m-001", "acknowledged", expected_current="submitted")
        print(f"acknowledged: {ok1}")
        ok2 = update_message_status(conn, "m-001", "working", expected_current="acknowledged")
        print(f"working: {ok2}")
        
        # 5. 초기 scan (아직超時 아님)
        section("5. 초기 scan")
        incs = check_and_report_stale(conn)
        print(f"생성된 incident: {len(incs)}")
        for i in incs:
            print(f"  {i}")
        
        # 6. 과거 시간으로 변경
        section("6. 과거 시간으로 변경")
        conn.execute("UPDATE messages SET updated_at='2026-08-14T08:00:00Z' WHERE msg_id='m-001'")
        conn.commit()
        print("업데이트 완료")
        
        # 7. scan (超時 발생)
        section("7. scan (超時)")
        incs = check_and_report_stale(conn)
        print(f"생성된 incident: {len(incs)}")
        for i in incs:
            print(f"  {i}")
        
        # 8. 상태 확인
        section("8. 상태 확인")
        status(conn)
        
        # 9. 완료 상태로 업데이트
        section("9. 완료 상태 업데이트")
        ok3 = update_message_status(conn, "m-001", "completed", expected_current="working",
                                     result={"images":["data/img_001.png"]})
        print(f"completed: {ok3}")
        
        # 10. 최종 scan (auto-reset/disarm)
        section("10. 최종 scan")
        incs = check_and_report_stale(conn)
        print(f"생성된 incident: {len(incs)}")
        for i in incs:
            print(f"  {i}")
        
        # 11. 최종 status
        section("11. 최종 status")
        status(conn)
        
    finally:
        conn.close()
    print("\n=== 시나리오 완료 ===")

if __name__ == "__main__":
    main()
