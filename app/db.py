from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import DATA_DIR, LOG_DIR, settings


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            create table if not exists tasks (
              id integer primary key autoincrement,
              created_at text not null,
              updated_at text not null,
              source text not null,
              requester text,
              request_text text not null,
              recipient_name text,
              recipient_phone text,
              objective text,
              constraints text,
              status text not null,
              research text,
              memory text,
              call_id text,
              call_status text,
              result_summary text,
              digest text
            );

            create table if not exists events (
              id integer primary key autoincrement,
              created_at text not null,
              task_id integer,
              sponsor text,
              event_type text not null,
              ok integer not null default 1,
              message text not null,
              payload text,
              foreign key(task_id) references tasks(id)
            );

            create table if not exists webhooks (
              id integer primary key autoincrement,
              created_at text not null,
              event_name text not null,
              channel text,
              payload text not null
            );

            create table if not exists provider_attempts (
              id integer primary key autoincrement,
              created_at text not null,
              updated_at text not null,
              task_id integer,
              domain text not null,
              provider_name text not null,
              phone text,
              email text,
              website text,
              source_note text,
              call_task_id integer,
              call_id text,
              call_status text,
              email_status text,
              outcome text,
              foreign key(task_id) references tasks(id),
              foreign key(call_task_id) references tasks(id)
            );
            """
        )


def trace(event_type: str, message: str, *, task_id: int | None = None, sponsor: str | None = None, ok: bool = True, payload: Any = None) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "at": now_iso(),
        "event_type": event_type,
        "task_id": task_id,
        "sponsor": sponsor,
        "ok": ok,
        "message": message,
        "payload": payload,
    }
    with Path(settings.trace_path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
    with connect() as conn:
        conn.execute(
            """
            insert into events(created_at, task_id, sponsor, event_type, ok, message, payload)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (record["at"], task_id, sponsor, event_type, int(ok), message, json.dumps(payload, default=str) if payload is not None else None),
        )


def create_task(source: str, request_text: str, requester: str | None, parsed: dict[str, Any]) -> int:
    ts = now_iso()
    with connect() as conn:
        cur = conn.execute(
            """
            insert into tasks(
              created_at, updated_at, source, requester, request_text, recipient_name,
              recipient_phone, objective, constraints, status
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts,
                ts,
                source,
                requester,
                request_text,
                parsed.get("recipient_name"),
                parsed.get("recipient_phone"),
                parsed.get("objective"),
                parsed.get("constraints"),
                "queued",
            ),
        )
        task_id = int(cur.lastrowid)
    trace("task.created", "Task created", task_id=task_id, payload=parsed)
    return task_id


def update_task(task_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = now_iso()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values())
    values.append(task_id)
    with connect() as conn:
        conn.execute(f"update tasks set {assignments} where id = ?", values)


def log_webhook(event_name: str, channel: str | None, payload: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            "insert into webhooks(created_at, event_name, channel, payload) values (?, ?, ?, ?)",
            (now_iso(), event_name, channel, json.dumps(payload, default=str)),
        )


def get_task(task_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("select * from tasks where id = ?", (task_id,)).fetchone()
    return dict(row) if row else None


def latest_task() -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("select * from tasks order by id desc limit 1").fetchone()
    return dict(row) if row else None


def find_task_by_call_id(call_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("select * from tasks where call_id = ? order by id desc limit 1", (call_id,)).fetchone()
    return dict(row) if row else None


def list_tasks(limit: int = 20) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("select * from tasks order by id desc limit ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def list_events(limit: int = 80) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("select * from events order by id desc limit ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def upsert_provider_attempt(**fields: Any) -> int:
    ts = now_iso()
    provider_name = fields["provider_name"]
    domain = fields["domain"]
    with connect() as conn:
        existing = conn.execute(
            "select id from provider_attempts where domain = ? and provider_name = ?",
            (domain, provider_name),
        ).fetchone()
        payload = {
            "updated_at": ts,
            "task_id": fields.get("task_id"),
            "domain": domain,
            "provider_name": provider_name,
            "phone": fields.get("phone"),
            "email": fields.get("email"),
            "website": fields.get("website"),
            "source_note": fields.get("source_note"),
            "call_task_id": fields.get("call_task_id"),
            "call_id": fields.get("call_id"),
            "call_status": fields.get("call_status"),
            "email_status": fields.get("email_status"),
            "outcome": fields.get("outcome"),
        }
        if existing:
            assignments = ", ".join(f"{key} = coalesce(?, {key})" for key in payload)
            conn.execute(
                f"update provider_attempts set {assignments} where id = ?",
                [*payload.values(), existing["id"]],
            )
            return int(existing["id"])
        cur = conn.execute(
            """
            insert into provider_attempts(
              created_at, updated_at, task_id, domain, provider_name, phone, email,
              website, source_note, call_task_id, call_id, call_status, email_status, outcome
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts,
                ts,
                payload["task_id"],
                payload["domain"],
                payload["provider_name"],
                payload["phone"],
                payload["email"],
                payload["website"],
                payload["source_note"],
                payload["call_task_id"],
                payload["call_id"],
                payload["call_status"],
                payload["email_status"],
                payload["outcome"],
            ),
        )
        return int(cur.lastrowid)


def update_provider_attempt(provider_id: int, **fields: Any) -> None:
    fields["updated_at"] = now_iso()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    with connect() as conn:
        conn.execute(f"update provider_attempts set {assignments} where id = ?", [*fields.values(), provider_id])


def list_provider_attempts(domain: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    with connect() as conn:
        if domain:
            rows = conn.execute("select * from provider_attempts where domain = ? order by id desc limit ?", (domain, limit)).fetchall()
        else:
            rows = conn.execute("select * from provider_attempts order by id desc limit ?", (limit,)).fetchall()
    return [dict(row) for row in rows]
