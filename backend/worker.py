import os
import time

import psycopg
from psycopg.rows import dict_row

from rules import judge

DSN = os.environ["DATABASE_URL"]
# 领取进程名：任务改为领取中时写入，作为最终落款；改派后落款为新进程名。
WORKER_NAME = os.environ.get("WORKER_NAME", "worker-默认")
# 领取后到出结论前的停顿，便于在专页观察领取中并执行改派。
PROCESS_DELAY = float(os.environ.get("PROCESS_DELAY", "2"))


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
                created_by text NOT NULL,
                created_at timestamptz NOT NULL,
                claimed_by text NOT NULL DEFAULT '',
                assign_to text NOT NULL DEFAULT ''
            )"""
        )
        # 兼容已存在的库：补齐领取落款列、改派指名列与改派履历表。
        conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS claimed_by text NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS assign_to text NOT NULL DEFAULT ''")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS reassignments (
                id serial PRIMARY KEY,
                job_id integer NOT NULL REFERENCES jobs(id),
                old_claim text NOT NULL DEFAULT '',
                new_claim text NOT NULL,
                reassigned_by text NOT NULL,
                note text NOT NULL DEFAULT '',
                created_at timestamptz NOT NULL
            )"""
        )
        conn.commit()


def claim_once(conn):
    row = conn.execute(
        """WITH picked AS (
             SELECT id FROM jobs
             WHERE status = 'pending' AND (assign_to = '' OR assign_to = %s)
             ORDER BY id
             FOR UPDATE SKIP LOCKED
             LIMIT 1
           )
           UPDATE jobs SET status = 'running', claimed_by = %s, assign_to = ''
           FROM picked
           WHERE jobs.id = picked.id
           RETURNING jobs.id, jobs.cyan_mm, jobs.magenta_mm, jobs.claimed_by""",
        (WORKER_NAME, WORKER_NAME),
    ).fetchone()
    return row


def finish(conn, row, verdict, reason):
    # 只回写仍由本进程领取的任务：改派后行已回到队列，原进程不再落款。
    done = conn.execute(
        """UPDATE jobs SET status = 'done', verdict = %s, reason = %s
           WHERE id = %s AND status = 'running' AND claimed_by = %s""",
        (verdict, reason, row["id"], WORKER_NAME),
    )
    return done.rowcount == 1


def main():
    ensure()
    while True:
        row = None
        with connect() as conn:
            row = claim_once(conn)
            # 先提交认领：领取中状态与领取进程名立刻对专页可见，也释放行锁以便改派。
            conn.commit()
            if row is not None:
                time.sleep(PROCESS_DELAY)
                verdict, reason = judge(row["cyan_mm"], row["magenta_mm"])
                kept = finish(conn, row, verdict, reason)
                conn.commit()
                if not kept:
                    # 任务已被改派回队列，由新领取名重新认领并落款，本进程不落款。
                    print(f"job {row['id']} 已改派，{WORKER_NAME} 放弃落款", flush=True)
        if row is None:
            time.sleep(0.4)


if __name__ == "__main__":
    main()
