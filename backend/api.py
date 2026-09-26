import os
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from psycopg.rows import dict_row

DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54394/printreg")
SECRET = os.environ.get("JWT_SECRET", "print-register-dev-secret")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)
USERS = {
    "printer": {"role": "writer", "password_hash": pwd.hash("print123456")},
    "checker": {"role": "reader", "password_hash": pwd.hash("check123456")},
}


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
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
);
CREATE TABLE IF NOT EXISTS reassignments (
    id serial PRIMARY KEY,
    job_id integer NOT NULL REFERENCES jobs(id),
    old_claim text NOT NULL DEFAULT '',
    new_claim text NOT NULL,
    reassigned_by text NOT NULL,
    note text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL
);
"""


class LoginIn(BaseModel):
    username: str
    password: str


class JobIn(BaseModel):
    sheet: str
    cyan_mm: float
    magenta_mm: float


class ReassignIn(BaseModel):
    new_claim: str
    note: str = ""


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        payload = jwt.decode(credentials.credentials, SECRET, algorithms=["HS256"])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="无效令牌") from exc
    if payload.get("sub") not in USERS:
        raise HTTPException(status_code=401, detail="无效令牌")
    return {"username": payload["sub"], "role": payload.get("role")}


def require_writer(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "writer":
        raise HTTPException(status_code=403, detail="仅印刷员可操作")
    return user


app = FastAPI(title="印刷套准复核台")


@app.on_event("startup")
def startup():
    with connect() as conn:
        conn.execute(SCHEMA)
        # 兼容已存在的库：补齐领取落款列、改派指名列。
        conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS claimed_by text NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS assign_to text NOT NULL DEFAULT ''")
        n = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
        if n == 0:
            now = datetime.now(timezone.utc)
            conn.execute(
                """INSERT INTO jobs (sheet, cyan_mm, magenta_mm, status, verdict, reason, created_by, created_at)
                   VALUES
                   ('封面-01', 0.05, -0.04, 'pending', '', '', 'printer', %s),
                   ('内页-09', 0.40, 0.02, 'pending', '', '', 'printer', %s)""",
                (now, now),
            )
        conn.commit()


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "print-register-review"}


@app.post("/api/auth/login")
def login(body: LoginIn):
    user = USERS.get(body.username.strip())
    if not user or not pwd.verify(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    token = jwt.encode({"sub": body.username.strip(), "role": user["role"], "exp": exp}, SECRET, algorithm="HS256")
    return {"access_token": token, "username": body.username.strip(), "role": user["role"]}


@app.get("/api/jobs")
def list_jobs(_user: dict = Depends(current_user)):
    with connect() as conn:
        return conn.execute(
            """SELECT id, sheet, cyan_mm, magenta_mm, status, verdict, reason,
                      created_by, claimed_by, assign_to
               FROM jobs ORDER BY id DESC"""
        ).fetchall()


@app.get("/api/reassignments")
def list_reassignments(_user: dict = Depends(current_user)):
    with connect() as conn:
        return conn.execute(
            """SELECT r.id, r.job_id, j.sheet AS sheet, r.old_claim, r.new_claim,
                      r.reassigned_by, r.note, r.created_at
               FROM reassignments r JOIN jobs j ON j.id = r.job_id
               ORDER BY r.id DESC"""
        ).fetchall()


@app.get("/api/claimants")
def list_claimants(_user: dict = Depends(current_user)):
    # 汇总在落款、指派、履历中出现过的领取名，供专页筛选与改派下拉使用。
    with connect() as conn:
        rows = conn.execute(
            """SELECT claimed_by AS name FROM jobs WHERE claimed_by <> ''
               UNION
               SELECT assign_to AS name FROM jobs WHERE assign_to <> ''
               UNION
               SELECT new_claim AS name FROM reassignments WHERE new_claim <> ''"""
        ).fetchall()
    return [r["name"] for r in rows]


@app.post("/api/jobs", status_code=202)
def enqueue(body: JobIn, user: dict = Depends(require_writer)):
    with connect() as conn:
        row = conn.execute(
            """INSERT INTO jobs (sheet, cyan_mm, magenta_mm, status, created_by, created_at)
               VALUES (%s, %s, %s, 'pending', %s, %s)
               RETURNING id, sheet, status, verdict""",
            (body.sheet.strip(), body.cyan_mm, body.magenta_mm, user["username"], datetime.now(timezone.utc)),
        ).fetchone()
        conn.commit()
    return row


@app.post("/api/jobs/{job_id}/reassign", status_code=200)
def reassign(job_id: int, body: ReassignIn, user: dict = Depends(require_writer)):
    new_claim = body.new_claim.strip()
    if not new_claim:
        raise HTTPException(status_code=400, detail="请填写新的领取名")
    with connect() as conn:
        job = conn.execute(
            "SELECT id, status, claimed_by FROM jobs WHERE id = %s FOR UPDATE",
            (job_id,),
        ).fetchone()
        if job is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if job["status"] == "done":
            raise HTTPException(status_code=409, detail="已出结论，不可改派")
        if job["status"] != "running":
            raise HTTPException(status_code=409, detail="任务尚未被领取，无需改派")
        if new_claim == job["claimed_by"]:
            raise HTTPException(status_code=400, detail="新领取名与当前领取名相同")
        now = datetime.now(timezone.utc)
        # 回到待处理队列并指名给新进程；清空当前落款，待新进程领取后写入新名。
        conn.execute(
            """UPDATE jobs
               SET status = 'pending', assign_to = %s, claimed_by = ''
               WHERE id = %s""",
            (new_claim, job_id),
        )
        conn.execute(
            """INSERT INTO reassignments
                   (job_id, old_claim, new_claim, reassigned_by, note, created_at)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (job_id, job["claimed_by"], new_claim, user["username"], body.note.strip(), now),
        )
        conn.commit()
    return {
        "id": job_id,
        "status": "pending",
        "claimed_by": "",
        "assign_to": new_claim,
        "old_claim": job["claimed_by"],
        "new_claim": new_claim,
    }
