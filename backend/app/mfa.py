"""Optional authenticator-app MFA with encrypted TOTP secrets and recovery codes."""

import hashlib
import secrets
from datetime import datetime, timezone
from uuid import UUID

import pyotp
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from flask import Blueprint, current_app, jsonify, request, session
from sqlalchemy import delete, or_, select, update

from . import limiter
from .auth import login_required, password_hasher
from .extensions import db
from .mfa_models import MfaCredential, MfaRecoveryCode
from .tenancy import TenantAccessDenied, set_user_context

mfa_bp = Blueprint("mfa", __name__, url_prefix="/api/auth/mfa")


def _cipher() -> Fernet:
    """Return the configured encryption cipher; never store TOTP secrets in plaintext."""
    key = current_app.config.get("MFA_ENCRYPTION_KEY")
    if not isinstance(key, str) or not key:
        raise RuntimeError("MFA_ENCRYPTION_KEY is not configured.")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as error:
        raise RuntimeError("MFA_ENCRYPTION_KEY is invalid.") from error


def _credential(user_id: UUID):
    return db.session.scalar(
        select(MfaCredential).where(MfaCredential.user_id == user_id)
    )


def is_mfa_enabled(user_id: UUID) -> bool:
    """Check MFA status while login_email RLS context is active."""
    credential = _credential(user_id)
    return bool(credential and credential.enabled_at is not None)


def _normalized_recovery_code(code: str) -> str:
    return code.replace("-", "").replace(" ", "").strip().upper()


def _matching_totp_step(secret: str, code: str):
    """Return the accepted TOTP step within one-step clock tolerance."""
    if not code.isdigit() or len(code) != 6:
        return None
    totp = pyotp.TOTP(secret)
    current_step = int(datetime.now(timezone.utc).timestamp() // totp.interval)
    for step in (current_step, current_step - 1, current_step + 1):
        at_step = datetime.fromtimestamp(step * totp.interval, timezone.utc)
        if totp.verify(code, for_time=at_step):
            return step
    return None


def _verify_code(user_id: UUID, credential: MfaCredential, code: str):
    """Verify a TOTP once per time step or atomically consume a recovery code."""

    if not isinstance(code, str) or not 6 <= len(code) <= 32:
        return False, False
    if code.isdigit() and len(code) == 6:
        try:
            secret = _cipher().decrypt(credential.secret_ciphertext.encode()).decode()
        except (InvalidToken, ValueError, RuntimeError):
            return False, False
        step = _matching_totp_step(secret, code)
        if step is None:
            return False, False
        accepted = db.session.execute(
            update(MfaCredential)
            .where(
                MfaCredential.user_id == user_id,
                or_(
                    MfaCredential.last_used_step.is_(None),
                    MfaCredential.last_used_step < step,
                ),
            )
            .values(last_used_step=step)
            .returning(MfaCredential.user_id)
        ).scalar_one_or_none()
        return accepted is not None, False

    normalized = _normalized_recovery_code(code)
    if len(normalized) != 10 or not normalized.isalnum():
        return False, False
    digest = hashlib.sha256(normalized.encode("ascii")).hexdigest()
    consumed_id = db.session.execute(
        delete(MfaRecoveryCode)
        .where(
            MfaRecoveryCode.user_id == user_id,
            MfaRecoveryCode.code_hash == digest,
        )
        .returning(MfaRecoveryCode.id)
    ).scalar_one_or_none()
    return consumed_id is not None, consumed_id is not None


@mfa_bp.get("/status")
@login_required
def mfa_status(user):
    credential = _credential(user.id)
    return jsonify({"enabled": bool(credential and credential.enabled_at is not None)})


@mfa_bp.post("/setup")
@login_required
@limiter.limit("5 per hour")
def begin_mfa_setup(user):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    password = data.get("current_password", "")
    if not isinstance(password, str) or not password or len(password) > 1024:
        return jsonify({"error": "Enter your current password to set up MFA."}), 400
    if not user.password_hash:
        return jsonify({"error": "A password is required before enabling MFA."}), 403
    try:
        password_hasher.verify(user.password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return jsonify({"error": "Current password is incorrect."}), 403

    try:
        cipher = _cipher()
        existing = _credential(user.id)
        if existing and existing.enabled_at is not None:
            return jsonify({"error": "MFA is already enabled."}), 409
        account_email = user.email
        secret = pyotp.random_base32()
        encrypted = cipher.encrypt(secret.encode()).decode()
        if existing:
            existing.secret_ciphertext = encrypted
        else:
            db.session.add(
                MfaCredential(user_id=user.id, secret_ciphertext=encrypted)
            )
        db.session.commit()
    except RuntimeError:
        db.session.rollback()
        return jsonify({"error": "MFA setup is not available until server encryption is configured."}), 503
    except Exception:
        db.session.rollback()
        current_app.logger.warning("MFA setup could not be started.")
        return jsonify({"error": "MFA setup could not be started. Try again."}), 503

    uri = pyotp.TOTP(secret).provisioning_uri(
        name=account_email, issuer_name="SALES DASH"
    )
    return jsonify(
        {
            "secret": secret,
            "provisioning_uri": uri,
            "message": "Add this account to your authenticator app, then confirm with its six-digit code.",
        }
    )


@mfa_bp.post("/confirm")
@login_required
@limiter.limit("10 per hour")
def confirm_mfa_setup(user):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    code = data.get("code", "")
    credential = db.session.scalar(
        select(MfaCredential).where(MfaCredential.user_id == user.id).with_for_update()
    )
    if not credential or credential.enabled_at is not None:
        return jsonify({"error": "Start a new MFA setup before confirming."}), 409
    if not isinstance(code, str) or not code.isdigit() or len(code) != 6:
        return jsonify({"error": "Enter the six-digit code from your authenticator app."}), 400
    try:
        secret = _cipher().decrypt(credential.secret_ciphertext.encode()).decode()
    except (InvalidToken, ValueError, RuntimeError):
        return jsonify({"error": "MFA setup is unavailable. Start again or contact support."}), 503
    matched_step = _matching_totp_step(secret, code)
    if matched_step is None:
        return jsonify({"error": "That authenticator code is not valid. Try again."}), 400

    credential.last_used_step = matched_step
    recovery_codes = [secrets.token_hex(5).upper() for _ in range(10)]
    credential.enabled_at = datetime.now(timezone.utc)
    db.session.execute(
        delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id)
    )
    db.session.add_all(
        MfaRecoveryCode(
            user_id=user.id,
            code_hash=hashlib.sha256(code_value.encode("ascii")).hexdigest(),
        )
        for code_value in recovery_codes
    )
    from .audit import record_audit_event

    record_audit_event(db.session, user.id, "mfa_enabled")
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.warning("MFA confirmation could not be saved.")
        return jsonify({"error": "MFA could not be enabled. Try again."}), 503
    return jsonify(
        {
            "enabled": True,
            "recovery_codes": [
                f"{value[:5]}-{value[5:]}" for value in recovery_codes
            ],
            "message": "MFA is enabled. Save these recovery codes now; they will not be shown again.",
        }
    )


@mfa_bp.post("/disable")
@login_required
@limiter.limit("5 per hour")
def disable_mfa(user):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    password = data.get("current_password", "")
    code = data.get("code", "")
    if (
        not isinstance(password, str)
        or not password
        or len(password) > 1024
        or not isinstance(code, str)
    ):
        return jsonify({"error": "Enter your current password and an authenticator or recovery code."}), 400
    if not user.password_hash:
        return jsonify({"error": "A password is required to disable MFA."}), 403
    try:
        password_hasher.verify(user.password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return jsonify({"error": "Current password is incorrect."}), 403

    credential = _credential(user.id)
    if not credential or credential.enabled_at is None:
        return jsonify({"error": "MFA is not enabled."}), 409
    valid, recovery_used = _verify_code(user.id, credential, code)
    if not valid:
        db.session.rollback()
        return jsonify({"error": "Authenticator or recovery code is incorrect."}), 403

    db.session.delete(credential)
    db.session.execute(
        delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id)
    )
    user.auth_version += 1
    from .audit import record_audit_event

    if recovery_used:
        record_audit_event(db.session, user.id, "mfa_recovery_code_used")
    record_audit_event(db.session, user.id, "mfa_disabled")
    db.session.commit()
    session.clear()
    return jsonify({"enabled": False, "authenticated": False, "message": "MFA is disabled. Sign in again."})


@mfa_bp.post("/challenge")
@limiter.limit("5 per minute")
@limiter.limit("10 per hour")
def complete_mfa_login():
    user_id = session.get("mfa_pending_user_id")
    auth_version = session.get("mfa_pending_auth_version")
    issued_at = session.get("mfa_pending_at")
    if not user_id or not isinstance(issued_at, int):
        return jsonify({"error": "Your sign-in challenge has expired. Sign in again."}), 401
    if datetime.now(timezone.utc).timestamp() - issued_at > 300:
        session.clear()
        return jsonify({"error": "Your sign-in challenge has expired. Sign in again."}), 401

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    code = data.get("code", "")
    if not isinstance(code, str) or not 6 <= len(code) <= 32:
        return jsonify({"error": "Enter your authenticator or recovery code."}), 400
    try:
        user = set_user_context(db.session, UUID(user_id))
        if user.auth_version != auth_version:
            session.clear()
            return jsonify({"error": "Your sign-in challenge has expired. Sign in again."}), 401
        credential = _credential(user.id)
        if not credential or credential.enabled_at is None:
            session.clear()
            return jsonify({"error": "Your sign-in challenge is no longer valid."}), 401
        valid, recovery_used = _verify_code(user.id, credential, code)
        if not valid:
            db.session.rollback()
            return jsonify({"error": "Authenticator or recovery code is incorrect."}), 401

        from .audit import record_audit_event

        if recovery_used:
            record_audit_event(db.session, user.id, "mfa_recovery_code_used")
        record_audit_event(db.session, user.id, "login_succeeded")
        authenticated_user_id = user.id
        authenticated_auth_version = user.auth_version
        db.session.commit()
    except (TenantAccessDenied, ValueError, TypeError, RuntimeError):
        db.session.rollback()
        session.clear()
        current_app.logger.warning("MFA sign-in could not be completed.")
        return jsonify({"error": "Your sign-in challenge is no longer valid."}), 401

    session.clear()
    session["user_id"] = str(authenticated_user_id)
    session["auth_version"] = authenticated_auth_version
    session.permanent = True
    return jsonify({"authenticated": True})
