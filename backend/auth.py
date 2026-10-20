import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import store

router = APIRouter(prefix="/api/auth")
COOKIE = "aftercare_session"


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(min_length=12, max_length=128)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class PasswordProof(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)


class AccountRecovery(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    recovery_code: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


def encoded_password(password: str):
    salt = secrets.token_hex(16)
    return f"{salt}:{password_hash(password, salt)}"


def password_matches(password: str, encoded: str):
    salt, expected = encoded.split(":")
    return hmac.compare_digest(password_hash(password, salt), expected)


def account():
    with store.connect() as db:
        return dict(db.execute("SELECT id,username FROM users WHERE id=?", (store.current_user.get(),)).fetchone())


def password_hash(password: str, salt: str) -> str:
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


def session_user(request: Request):
    token = request.cookies.get(COOKIE, "")
    with store.connect() as db:
        row = db.execute("""SELECT users.id, username FROM sessions JOIN users ON users.id=user_id
            WHERE token=? AND expires>?""", (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
    return dict(row) if row else None


def create_session(response: Response, user_id: str):
    token = secrets.token_urlsafe(32)
    with store.connect() as db:
        db.execute("DELETE FROM sessions WHERE expires<=?", (time.time(),))
        db.execute("INSERT INTO sessions VALUES (?,?,?)",
                   (hashlib.sha256(token.encode()).hexdigest(), user_id, time.time() + 43200))
    response.set_cookie(COOKIE, token, max_age=43200, httponly=True, samesite="strict",
                        secure=os.environ.get("AFTERCARE_SECURE_COOKIE") == "1", path="/api")


def throttle(request: Request, username: str):
    key = hashlib.sha256(f"{request.client.host}:{username.lower()}".encode()).hexdigest()
    now = time.time()
    with store.connect() as db:
        db.execute("DELETE FROM login_attempts WHERE created<?", (now - 900,))
        count = db.execute("SELECT COUNT(*) FROM login_attempts WHERE key=?", (key,)).fetchone()[0]
        if count >= 10:
            raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
        db.execute("INSERT INTO login_attempts VALUES (?,?)", (key, now))
    return key


def clear_attempts(key: str):
    with store.connect() as db:
        db.execute("DELETE FROM login_attempts WHERE key=?", (key,))


@router.get("/session")
def session(request: Request):
    user = session_user(request)
    if not user:
        raise HTTPException(401, "Sign in to continue.")
    return user


@router.post("/register", status_code=201)
def register(body: Credentials, request: Request, response: Response):
    attempt_key = throttle(request, body.username)
    salt = secrets.token_hex(16)
    user = {"id": uuid4().hex, "username": body.username.lower()}
    hashed = f"{salt}:{password_hash(body.password, salt)}"
    try:
        with store.connect() as db:
            db.execute("INSERT INTO users VALUES (?,?,?)", (user["id"], user["username"], hashed))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Choose a different username.")
    create_session(response, user["id"])
    clear_attempts(attempt_key)
    return user


@router.post("/login")
def login(body: Credentials, request: Request, response: Response):
    attempt_key = throttle(request, body.username)
    with store.connect() as db:
        row = db.execute("SELECT * FROM users WHERE username=?", (body.username.lower(),)).fetchone()
    salt, expected = row["password"].split(":") if row else ("00" * 16, "00" * 64)
    if not hmac.compare_digest(password_hash(body.password, salt), expected) or not row:
        raise HTTPException(401, "Username or password is incorrect.")
    create_session(response, row["id"])
    clear_attempts(attempt_key)
    return {"id": row["id"], "username": row["username"]}


@router.post("/logout")
def logout(request: Request, response: Response):
    with store.connect() as db:
        db.execute("DELETE FROM sessions WHERE token=?",
                   (hashlib.sha256(request.cookies.get(COOKIE, "").encode()).hexdigest(),))
    response.delete_cookie(COOKIE, path="/api")
    return {"ok": True}


@router.get("/security")
def security():
    with store.connect() as db:
        configured = bool(db.execute("SELECT 1 FROM recovery_codes WHERE user_id=?", (store.current_user.get(),)).fetchone())
    return {"recovery_configured": configured}


@router.post("/recovery-code")
def create_recovery_code(body: PasswordProof, request: Request):
    user = account()
    attempt_key = throttle(request, user["username"])
    code = "AC-" + secrets.token_urlsafe(24)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT password FROM users WHERE id=?", (user["id"],)).fetchone()
        if not password_matches(body.current_password, row["password"]):
            raise HTTPException(401, "The current password is incorrect.")
        db.execute("INSERT INTO recovery_codes VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET code_hash=excluded.code_hash,created_at=excluded.created_at",
                   (user["id"], hashlib.sha256(code.encode()).hexdigest(), datetime.now(timezone.utc).isoformat()))
    clear_attempts(attempt_key)
    return {"recovery_code": code}


@router.post("/password")
def change_password(body: PasswordChange, request: Request, response: Response):
    user = account()
    attempt_key = throttle(request, user["username"])
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT password FROM users WHERE id=?", (user["id"],)).fetchone()
        if not password_matches(body.current_password, row["password"]):
            raise HTTPException(401, "The current password is incorrect.")
        if body.current_password == body.new_password:
            raise HTTPException(422, "Choose a different new password.")
        db.execute("UPDATE users SET password=? WHERE id=?", (encoded_password(body.new_password), user["id"]))
        db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        db.execute("DELETE FROM recovery_codes WHERE user_id=?", (user["id"],))
        db.execute("DELETE FROM push_devices WHERE user_id=?", (user["id"],))
    create_session(response, user["id"])
    clear_attempts(attempt_key)
    return {"ok": True}


@router.post("/recover")
def recover_account(body: AccountRecovery, request: Request):
    attempt_key = throttle(request, body.username)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("""SELECT users.id,code_hash FROM users JOIN recovery_codes ON user_id=users.id
            WHERE username=?""", (body.username.lower(),)).fetchone()
        expected = row["code_hash"] if row else "0" * 64
        if not hmac.compare_digest(hashlib.sha256(body.recovery_code.strip().encode()).hexdigest(), expected) or not row:
            raise HTTPException(401, "The username or recovery code is incorrect.")
        db.execute("UPDATE users SET password=? WHERE id=?", (encoded_password(body.new_password), row["id"]))
        db.execute("DELETE FROM recovery_codes WHERE user_id=?", (row["id"],))
        db.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
        db.execute("DELETE FROM push_devices WHERE user_id=?", (row["id"],))
    clear_attempts(attempt_key)
    return {"ok": True}
