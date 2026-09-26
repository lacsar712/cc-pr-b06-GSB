import os
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query
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

# 可被改派的领取名：领取进程通过 CLAIM_NAME 注册，印刷员把任务改派给其中之一
KNOWN_CLAIMANTS = [
    name.strip()
    for name in os.environ.get("CLAIM_NAMES", "领取进程甲,领取进程乙").split(",")
    if name.strip()
]


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
    claim_name text NOT NULL DEFAULT '',
    created_by text NOT NULL,
    created_at timestamptz NOT NULL
);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS claim_name text NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS reassignments (
    id serial PRIMARY KEY,
    job_id integer NOT NULL REFERENCES jobs(id),
    sheet text NOT NULL DEFAULT '',
    from_name text NOT NULL,
    to_name text NOT NULL,
    operator text NOT NULL,
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
    to_name: str


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
        raise HTTPException(status_code=403, detail="只读账号不能改派")
    return user


app = FastAPI(title="印刷套准复核台")


@app.on_event("startup")
def startup():
    with connect() as conn:
        conn.execute(SCHEMA)
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


JOB_COLS = "id, sheet, cyan_mm, magenta_mm, status, verdict, reason, claim_name, created_by"


@app.get("/api/jobs")
def list_jobs(_user: dict = Depends(current_user)):
    with connect() as conn:
        return conn.execute(
            f"SELECT {JOB_COLS} FROM jobs ORDER BY id DESC"
        ).fetchall()


@app.post("/api/jobs", status_code=202)
def enqueue(body: JobIn, user: dict = Depends(require_writer)):
    with connect() as conn:
        row = conn.execute(
            """INSERT INTO jobs (sheet, cyan_mm, magenta_mm, status, created_by, created_at)
               VALUES (%s, %s, %s, 'pending', %s, %s)
               RETURNING id, sheet, status, verdict, claim_name""",
            (body.sheet.strip(), body.cyan_mm, body.magenta_mm, user["username"], datetime.now(timezone.utc)),
        ).fetchone()
        conn.commit()
    return row


@app.get("/api/claimants")
def claimants(_user: dict = Depends(current_user)):
    """可被改派的领取名，以及当前库里实际出现过落款的领取名。"""
    with connect() as conn:
        seen = [
            r["claim_name"]
            for r in conn.execute(
                "SELECT DISTINCT claim_name FROM jobs WHERE claim_name <> '' ORDER BY claim_name"
            ).fetchall()
        ]
    names = list(dict.fromkeys(KNOWN_CLAIMANTS + seen))
    return {"claimants": names}


@app.get("/api/claims")
def list_claims(
    claimant: str | None = Query(None, description="按领取人筛选"),
    scope: str = Query("all", pattern="^(in_transit|done|all)$"),
    _user: dict = Depends(current_user),
):
    """领取落款视图：只返回已被领取进程领走（有落款）的任务。

    scope=in_transit 只看领取中；scope=done 只看已落款（已出结论）。
    """
    sql = f"SELECT {JOB_COLS} FROM jobs WHERE claim_name <> ''"
    params: list = []
    if claimant:
        sql += " AND claim_name = %s"
        params.append(claimant)
    if scope == "in_transit":
        sql += " AND status = 'running'"
    elif scope == "done":
        sql += " AND status = 'done'"
    sql += " ORDER BY id DESC"
    with connect() as conn:
        return conn.execute(sql, params).fetchall()


@app.get("/api/reassignments")
def list_reassignments(_user: dict = Depends(current_user)):
    with connect() as conn:
        return conn.execute(
            """SELECT id, job_id, sheet, from_name, to_name, operator, created_at
               FROM reassignments ORDER BY id DESC"""
        ).fetchall()


@app.post("/api/jobs/{job_id}/reassign", status_code=200)
def reassign(job_id: int, body: ReassignIn, user: dict = Depends(require_writer)):
    """把领取中的任务改派给另一领取名并记履历。已出结论的不可改派。"""
    to_name = body.to_name.strip()
    if not to_name:
        raise HTTPException(status_code=422, detail="请填写改派后的领取名")
    with connect() as conn:
        job = conn.execute(
            "SELECT id, sheet, status, claim_name FROM jobs WHERE id = %s FOR UPDATE",
            (job_id,),
        ).fetchone()
        if job is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if job["status"] == "done":
            raise HTTPException(status_code=409, detail="已出结论，不可改派")
        if job["status"] != "running":
            raise HTTPException(status_code=409, detail="任务尚未被领取，无需改派")
        if not job["claim_name"]:
            raise HTTPException(status_code=409, detail="任务还没有领取落款")
        if job["claim_name"] == to_name:
            raise HTTPException(status_code=422, detail="新领取名与当前领取人相同")
        conn.execute("UPDATE jobs SET claim_name = %s WHERE id = %s", (to_name, job_id))
        record = conn.execute(
            """INSERT INTO reassignments (job_id, sheet, from_name, to_name, operator, created_at)
               VALUES (%s, %s, %s, %s, %s, %s)
               RETURNING id, job_id, sheet, from_name, to_name, operator, created_at""",
            (
                job_id,
                job["sheet"],
                job["claim_name"],
                to_name,
                user["username"],
                datetime.now(timezone.utc),
            ),
        ).fetchone()
        conn.commit()
    return record
