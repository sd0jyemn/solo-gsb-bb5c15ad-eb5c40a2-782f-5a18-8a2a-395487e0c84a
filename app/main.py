"""FastAPI 入口：DNS SOA 序列号审计 API。"""

from __future__ import annotations

from datetime import date
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response, status

from . import database
from .schemas import AuditCreate, AuditOut
from .service import build_audit


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 依赖安装后、开始接流量前完成数据库初始化。
    database.init_db()
    yield


app = FastAPI(
    title="DNS SOA 序列号审计 API",
    description=(
        "按 RFC 1982 模运算审计 SOA serial 的前进/倒退/相等/不可比较，"
        "标出可能使从服务器拒绝更新的节点，并给出 YYYYMMDDnn 下一序列号建议。"
    ),
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/", tags=["meta"])
def root() -> dict:
    return {
        "service": "dns-soa-serial-audit",
        "docs": "/docs",
        "health": "/healthz",
        "create_audit": "POST /audits",
        "get_audit": "GET /audits/{id}",
        "reference": "RFC 1982",
    }


@app.get("/healthz", tags=["meta"])
def healthz() -> dict:
    return {"status": "ok"}


@app.post(
    "/audits",
    response_model=AuditOut,
    status_code=status.HTTP_201_CREATED,
    tags=["audits"],
    summary="创建 serial 审计",
    responses={409: {"model": AuditOut, "description": "下一序列号建议冲突（记录仍已保存）"}},
)
def create_audit(payload: AuditCreate, response: Response) -> dict:
    status_code, document = build_audit(
        zone=payload.zone,
        serials=payload.serials,
        today_utc=date.today(),
    )
    audit_id = database.insert_audit(
        zone=document["zone"],
        created_at=document["created_at"],
        result=document,
    )
    document["id"] = audit_id
    response.status_code = status_code
    return document


@app.get(
    "/audits/{audit_id}",
    response_model=AuditOut,
    tags=["audits"],
    summary="按 ID 查询审计记录",
)
def get_audit(audit_id: int) -> dict:
    record = database.get_audit(audit_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="审计记录不存在")
    return record
