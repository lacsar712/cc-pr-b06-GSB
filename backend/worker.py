import os
import time

import psycopg
from psycopg.rows import dict_row

from rules import judge

DSN = os.environ["DATABASE_URL"]
CLAIM_NAME = os.environ.get("CLAIM_NAME", "领取进程甲")
DELAY = float(os.environ.get("PROCESS_DELAY_SECONDS", "6"))
POLL = float(os.environ.get("POLL_INTERVAL_SECONDS", "0.4"))


def connect():
    last = None
    for _ in range(40):
        try:
            return psycopg.connect(DSN, row_factory=dict_row)
        except psycopg.OperationalError as exc:
            last = exc
            time.sleep(1)
    raise last


def ensure():
    with connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                id serial PRIMARY KEY,
                sheet text NOT NULL,
                cyan_mm double precision NOT NULL,
                magenta_mm double precision NOT NULL,
                status text NOT NULL,
                verdict text NOT NULL DEFAULT '',
                reason text NOT NULL DEFAULT '',
                claim_name text NOT NULL DEFAULT '',
                created_by text NOT NULL,
                created_at timestamptz NOT NULL
            )"""
        )
        # 旧库补列：领取落款在任务转为领取中时写入，出结论后保留
        conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS claim_name text NOT NULL DEFAULT ''")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS reassignments (
                id serial PRIMARY KEY,
                job_id integer NOT NULL REFERENCES jobs(id),
                sheet text NOT NULL DEFAULT '',
                from_name text NOT NULL,
                to_name text NOT NULL,
                operator text NOT NULL,
                created_at timestamptz NOT NULL
            )"""
        )
        conn.commit()


def claim_once(conn):
    """行锁领走一条待处理任务：置为领取中并写下本进程名作为落款，随即提交。

    提交后落款即对外可见，计算结论前的等待窗口里印刷员可以改派。
    """
    row = conn.execute(
        """WITH picked AS (
             SELECT id FROM jobs
             WHERE status = 'pending'
             ORDER BY id
             FOR UPDATE SKIP LOCKED
             LIMIT 1
           )
           UPDATE jobs SET status = 'running', claim_name = %s
           FROM picked
           WHERE jobs.id = picked.id
           RETURNING jobs.id, jobs.sheet, jobs.cyan_mm, jobs.magenta_mm""",
        (CLAIM_NAME,),
    ).fetchone()
    return row


def finish(job):
    """写回结论。只动状态与结论，不碰 claim_name：等待期间可能已被改派成新名。"""
    verdict, reason = judge(job["cyan_mm"], job["magenta_mm"])
    with connect() as conn:
        conn.execute(
            "UPDATE jobs SET status = 'done', verdict = %s, reason = %s WHERE id = %s AND status = 'running'",
            (verdict, reason, job["id"]),
        )
        conn.commit()
    print(f"[{CLAIM_NAME}] 任务 #{job['id']}（{job['sheet']}）出结论：{verdict}", flush=True)


def main():
    ensure()
    print(f"[{CLAIM_NAME}] 领取进程就绪，处理耗时 {DELAY:.0f} 秒", flush=True)
    while True:
        with connect() as conn:
            job = claim_once(conn)
            conn.commit()
        if job is None:
            time.sleep(POLL)
            continue
        print(f"[{CLAIM_NAME}] 领取任务 #{job['id']}（{job['sheet']}），落款={CLAIM_NAME}", flush=True)
        # 落款已落库并可见；这段时间专页能看到领取中，也能改派
        time.sleep(DELAY)
        finish(job)


if __name__ == "__main__":
    main()
