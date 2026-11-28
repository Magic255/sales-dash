"""Encrypted supplier-document intake with fail-closed ClamAV scanning."""

import hashlib
import io
import socket
import struct
from datetime import datetime, timezone
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from flask import Blueprint, current_app, jsonify, request, send_file, session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from .audit import record_audit_event
from .auth import login_required
from .extensions import db
from .models import Supplier, SupplierDocument
from .permissions import company_permission_required

supplier_documents_bp = Blueprint("supplier_documents", __name__, url_prefix="/api")
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
CHUNK_BYTES = 64 * 1024


def _company_id():
    return UUID(session["company_id"])


def _detected_content_type(data):
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _clamav_scan(data):
    """Return clean/infected; raise when the scanner is unavailable or inconclusive."""
    host = current_app.config.get("SUPPLIER_DOCUMENT_CLAMD_HOST")
    port = current_app.config.get("SUPPLIER_DOCUMENT_CLAMD_PORT", 3310)
    timeout = current_app.config.get("SUPPLIER_DOCUMENT_CLAMD_TIMEOUT", 8)
    if not host:
        raise RuntimeError("Malware scanning is unavailable; supplier document uploads are disabled.")

    try:
        with socket.create_connection((host, port), timeout=timeout) as connection:
            connection.settimeout(timeout)
            connection.sendall(b"zINSTREAM\0")
            for offset in range(0, len(data), CHUNK_BYTES):
                chunk = data[offset:offset + CHUNK_BYTES]
                connection.sendall(struct.pack("!I", len(chunk)))
                connection.sendall(chunk)
            connection.sendall(struct.pack("!I", 0))
            response = bytearray()
            while len(response) <= 1024 and not response.endswith(b"\n"):
                part = connection.recv(256)
                if not part:
                    break
                response.extend(part)
    except (OSError, TimeoutError) as error:
        raise RuntimeError(
            "Malware scanning is unavailable; supplier document uploads are disabled."
        ) from error

    result = bytes(response).strip()
    if result.endswith(b": OK"):
        return "clean"
    if result.endswith(b": FOUND"):
        return "infected"
    raise RuntimeError("Malware scanner returned an invalid response; upload was blocked.")


def _encryption_cipher():
    key = current_app.config.get("SUPPLIER_DOCUMENT_ENCRYPTION_KEY")
    if not isinstance(key, str) or not key:
        raise RuntimeError("Supplier document encryption is unavailable; uploads are disabled.")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as error:
        raise RuntimeError("Supplier document encryption is unavailable; uploads are disabled.") from error


def _document_json(document):
    return {
        "id": str(document.id),
        "original_filename": document.original_filename,
        "content_type": document.content_type,
        "size_bytes": document.size_bytes,
        "sha256": document.sha256,
        "scan_status": document.scan_status,
        "scanned_at": document.scanned_at.isoformat(),
        "created_at": document.created_at.isoformat(),
    }


@supplier_documents_bp.post("/suppliers/<uuid:supplier_id>/documents")
@login_required
@company_permission_required("manage_suppliers")
def upload_supplier_document(user, supplier_id):
    company_id = _company_id()
    supplier = db.session.scalar(
        select(Supplier).where(
            Supplier.id == supplier_id, Supplier.company_id == company_id
        )
    )
    if supplier is None:
        return jsonify({"error": "Supplier not found."}), 404

    uploaded = request.files.get("file")
    if uploaded is None:
        return jsonify({"error": "Choose a supplier document to upload."}), 400

    raw = uploaded.stream.read(MAX_DOCUMENT_BYTES + 1)
    if not raw:
        return jsonify({"error": "The supplier document is empty."}), 400
    if len(raw) > MAX_DOCUMENT_BYTES:
        return jsonify({"error": "Supplier documents must be 8 MB or smaller."}), 413

    detected_type = _detected_content_type(raw)
    if detected_type is None:
        return jsonify({"error": "Only valid PDF, JPEG, PNG, and WebP documents are accepted."}), 400
    if uploaded.mimetype != detected_type:
        return jsonify({"error": "The file content does not match its declared media type."}), 400

    filename = secure_filename(uploaded.filename or "")[:180]
    if not filename:
        filename = "supplier-document"

    try:
        cipher = _encryption_cipher()
        scan_status = _clamav_scan(raw)
        if scan_status != "clean":
            record_audit_event(
                db.session, user.id, "supplier_document_rejected", company_id,
                {"supplier_id": str(supplier.id), "reason": "malware_detected"},
            )
            db.session.commit()
            return jsonify({"error": "The uploaded document failed malware scanning."}), 422

        document = SupplierDocument(
            company_id=company_id,
            supplier_id=supplier.id,
            uploaded_by_user_id=user.id,
            original_filename=filename,
            content_type=detected_type,
            size_bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            encrypted_content=cipher.encrypt(raw),
            scan_status="clean",
            scanned_at=datetime.now(timezone.utc),
        )
        db.session.add(document)
        db.session.flush()
        record_audit_event(
            db.session, user.id, "supplier_document_uploaded", company_id,
            {
                "supplier_id": str(supplier.id),
                "document_id": str(document.id),
                "sha256": document.sha256,
                "size_bytes": document.size_bytes,
            },
        )
        result = _document_json(document)
        db.session.commit()
    except RuntimeError as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 503
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "The supplier document could not be stored."}), 409

    return jsonify({"item": result}), 201


@supplier_documents_bp.get("/suppliers/<uuid:supplier_id>/documents")
@login_required
@company_permission_required("manage_suppliers")
def list_supplier_documents(_user, supplier_id):
    company_id = _company_id()
    supplier = db.session.scalar(
        select(Supplier.id).where(
            Supplier.id == supplier_id, Supplier.company_id == company_id
        )
    )
    if supplier is None:
        return jsonify({"error": "Supplier not found."}), 404
    rows = db.session.scalars(
        select(SupplierDocument).where(
            SupplierDocument.company_id == company_id,
            SupplierDocument.supplier_id == supplier_id,
        ).order_by(SupplierDocument.created_at.desc()).limit(100)
    ).all()
    return jsonify({"items": [_document_json(row) for row in rows]})


@supplier_documents_bp.get("/suppliers/<uuid:supplier_id>/documents/<uuid:document_id>")
@login_required
@company_permission_required("manage_suppliers")
def download_supplier_document(user, supplier_id, document_id):
    company_id = _company_id()
    document = db.session.scalar(
        select(SupplierDocument).where(
            SupplierDocument.id == document_id,
            SupplierDocument.supplier_id == supplier_id,
            SupplierDocument.company_id == company_id,
        )
    )
    if document is None:
        return jsonify({"error": "Supplier document not found."}), 404
    try:
        raw = _encryption_cipher().decrypt(document.encrypted_content)
    except (RuntimeError, InvalidToken):
        db.session.rollback()
        return jsonify({"error": "Supplier document could not be decrypted."}), 503

    record_audit_event(
        db.session, user.id, "supplier_document_downloaded", company_id,
        {"supplier_id": str(supplier_id), "document_id": str(document.id)},
    )
    db.session.commit()
    response = send_file(
        io.BytesIO(raw),
        mimetype=document.content_type,
        as_attachment=True,
        download_name=document.original_filename,
        max_age=0,
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
