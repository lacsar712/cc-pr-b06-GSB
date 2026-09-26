import os
import sys
import threading
import time
from pathlib import Path

import pgserver

sys.path.insert(0, str(Path(__file__).parent))

PG_DIR = "/tmp/pgdata-test"
os.environ["CLAIM_NAMES"] = "领取进程甲,领取进程乙"

pg = pgserver.get_server(PG_DIR)
DSN = pg.get_uri()
os.environ["DATABASE_URL"] = DSN

import worker
from rules import judge
from fastapi.testclient import TestClient
import api

worker.DSN = DSN
api.DSN = DSN

with TestClient(app := api.app) as client:
    def login(u, p):
        r = client.post("/api/auth/login", json={"username": u, "password": p})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    hp = login("printer", "print123456")
    hr = login("checker", "check123456")

    # 新任务落入待处理
    r = client.post("/api/jobs", json={"sheet": "插页-X", "cyan_mm": 0.5, "magenta_mm": 0.0}, headers=hp)
    assert r.status_code == 202
    new_id = r.json()["id"]
    assert r.json()["status"] == "pending"

    # 领取：写领取中 + 进程名
    worker.DELAY = 0.0
    conn = worker.connect()
    job = worker.claim_once(conn)
    conn.commit()
    assert job is not None, "应能领到任务"

    # 专页立刻能看到领取进程名（领取态）
    claims = client.get("/api/claims?scope=in_transit", headers=hp).json()
    assert any(c["id"] == job["id"] and c["claim_name"] == worker.CLAIM_NAME and c["status"] == "running" for c in claims), claims
    print(f"OK 领取中可见落款: #{job['id']} -> {worker.CLAIM_NAME}")

    # 待处理任务不能改派（409）
    r = client.post(f"/api/jobs/{new_id}/reassign", json={"to_name": "领取进程乙"}, headers=hp)
    assert r.status_code == 409, (r.status_code, r.text)
    print("OK 未领取任务改派被拒:", r.json()["detail"])

    # 只读账号不能改派（403）
    r = client.post(f"/api/jobs/{job['id']}/reassign", json={"to_name": "领取进程乙"}, headers=hr)
    assert r.status_code == 403, (r.status_code, r.text)
    print("OK 只读账号改派被拒:", r.json()["detail"])
    # 只读账号能看落款与履历
    assert client.get("/api/claims", headers=hr).status_code == 200
    assert client.get("/api/reassignments", headers=hr).status_code == 200

    # 同名校验
    r = client.post(f"/api/jobs/{job['id']}/reassign", json={"to_name": worker.CLAIM_NAME}, headers=hp)
    assert r.status_code == 422

    # 印刷员改派给另一领取名
    other = "领取进程乙" if worker.CLAIM_NAME == "领取进程甲" else "领取进程甲"
    r = client.post(f"/api/jobs/{job['id']}/reassign", json={"to_name": other}, headers=hp)
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["from_name"] == worker.CLAIM_NAME and rec["to_name"] == other and rec["operator"] == "printer"
    print(f"OK 改派: {rec['from_name']} -> {rec['to_name']} by {rec['operator']}")

    # 履历有一条
    hist = client.get("/api/reassignments", headers=hp).json()
    assert len(hist) == 1 and hist[0]["job_id"] == job["id"], hist

    # 出结论：落款应为新名，不被 worker 覆盖
    expected_verdict, _ = judge(job["cyan_mm"], job["magenta_mm"])
    worker.finish(job)
    final = client.get(f"/api/jobs", headers=hp).json()
    row = next(j for j in final if j["id"] == job["id"])
    assert row["status"] == "done" and row["verdict"] == expected_verdict, row
    assert row["claim_name"] == other, row
    print(f"OK 改派后出结论落款为新名: {row['claim_name']} / {row['verdict']}")

    # 已出结论不可改派（409）
    r = client.post(f"/api/jobs/{job['id']}/reassign", json={"to_name": worker.CLAIM_NAME}, headers=hp)
    assert r.status_code == 409, (r.status_code, r.text)
    print("OK 已出结论改派被拒:", r.json()["detail"])

    # 按领取人筛选：已落款列表只含该领取人
    rows_a = client.get("/api/claims?scope=done&claimant=" + other, headers=hp).json()
    assert all(c["claim_name"] == other for c in rows_a) and any(c["id"] == job["id"] for c in rows_a)
    print(f"OK 按领取人筛选（{other}）: {len(rows_a)} 条已落款")

    # 领取另一进程名、不改派直接出结论，落款保留为领取者
    conn = worker.connect()
    job2 = worker.claim_once(conn)
    conn.commit()
    if job2 is not None:
        worker.finish(job2)
        final = client.get("/api/jobs", headers=hp).json()
        row2 = next(j for j in final if j["id"] == job2["id"])
        assert row2["claim_name"] == worker.CLAIM_NAME and row2["status"] == "done", row2
        print(f"OK 未改派任务落款保留: #{job2['id']} -> {row2['claim_name']}")

    # claimants 接口含两个进程名
    names = client.get("/api/claimants", headers=hp).json()["claimants"]
    assert "领取进程甲" in names and "领取进程乙" in names, names

    # 未登录 401
    assert client.get("/api/claims").status_code == 401

print("\n全部断言通过 ✔")
pg.cleanup()
