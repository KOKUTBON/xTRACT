from __future__ import annotations

import base64
import binascii
import hmac
import json
import logging
import mimetypes
import re
from collections.abc import Callable
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote, unquote

import xtract
from xtract.auth import AuthService, AuthUser
from xtract.auth.models import ROLE_PERMISSIONS
from xtract.core import Platform
from xtract.intake.service import IntakeError
from xtract.review.commands import REPROCESS_SCOPES, CommandError

logger = logging.getLogger("xtract.http")

STATUS_TEXT = {
    200: "OK", 201: "Created", 202: "Accepted", 204: "No Content", 400: "Bad Request",
    401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed", 409: "Conflict",
    413: "Payload Too Large", 415: "Unsupported Media Type", 422: "Unprocessable Entity",
    500: "Internal Server Error", 503: "Service Unavailable",
}  # fmt: skip
INTAKE_STATUS = {
    "UNSUPPORTED_MEDIA_TYPE": 415,
    "MEDIA_TYPE_MISMATCH": 415,
    "PAYLOAD_TOO_LARGE": 413,
    "DUPLICATE_DOCUMENT": 409,
}
SECURITY_HEADERS = [
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
]
CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
    "frame-src 'self' blob:; object-src 'self' blob:; base-uri 'none'; form-action 'self'"
)
WORKFLOW_STAGES = [
    "acquired", "ocr_executed", "to_be_verified", "validated", "protocol_pending",
    "protocol_registered", "discarded", "failed",
]  # fmt: skip
ID = r"(?P<document_id>[0-9a-fA-F-]{36})"


class HttpError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or {}


class Request:
    def __init__(self, environ: dict, max_body: int) -> None:
        self.environ = environ
        self.method = environ.get("REQUEST_METHOD", "GET").upper()
        self.path = unquote(environ.get("PATH_INFO", "/")) or "/"
        self.query = {k: v[-1] for k, v in parse_qs(environ.get("QUERY_STRING", "")).items()}
        self.max_body = max_body
        self.params: dict[str, str] = {}
        self.user: AuthUser | None = None

    def header(self, name: str) -> str:
        return self.environ.get("HTTP_" + name.upper().replace("-", "_"), "")

    @property
    def actor(self) -> str:
        if self.user:
            return self.user.display_name or self.user.user_id or "operator"
        actor = re.sub(r"[^\w.@\- ]", "", self.header("X-Operator-Id")).strip()[:80]
        return actor or "operator"

    def json(self) -> dict:
        try:
            length = int(self.environ.get("CONTENT_LENGTH") or 0)
        except ValueError as exc:
            raise HttpError(400, "INVALID_LENGTH", "Invalid Content-Length.") from exc
        if length < 0:
            raise HttpError(400, "INVALID_LENGTH", "Invalid Content-Length.")
        if length > self.max_body:
            raise HttpError(413, "PAYLOAD_TOO_LARGE", "The request body is too large.")
        raw = self.environ["wsgi.input"].read(length) if length else b""
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise HttpError(400, "INVALID_JSON", "The request body must be valid JSON.") from exc
        if not isinstance(data, dict):
            raise HttpError(400, "INVALID_JSON", "The request body must be a JSON object.")
        string_fields = (
            "filename",
            "content_base64",
            "text_content",
            "mime_type",
            "title",
            "institution_id",
            "office_id",
            "document_family",
            "value",
            "comment",
            "reason",
            "scope",
            "reason_code",
            "related_exception_id",
            "prompt",
        )
        for key in string_fields:
            if key in data and data[key] is not None and not isinstance(data[key], str):
                raise HttpError(422, "INVALID_TYPE", f"{key} must be a string or null.")
        if "force" in data and not isinstance(data["force"], bool):
            raise HttpError(422, "INVALID_TYPE", "force must be a boolean.")
        return data


class Response:
    def __init__(
        self,
        status: int = 200,
        body: bytes | str | dict | list = b"",
        content_type: str = "application/json",
        headers: list | None = None,
    ) -> None:
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        self.status = status
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = [("Content-Type", content_type), *(headers or [])]


def create_app(platform: Platform) -> Callable:
    """Create the WSGI application serving the REST API and the operator portal."""
    cfg = platform.config
    auth_service = getattr(platform, "auth", None) or AuthService(cfg)
    routes: list[tuple[str, re.Pattern, Callable]] = []

    def require_permission(req: Request, permission: str) -> None:
        if not req.user:
            raise HttpError(401, "UNAUTHORIZED", "Authentication required.")
        if not req.user.has_permission(permission):
            raise HttpError(
                403,
                "FORBIDDEN",
                f"Permission '{permission}' is required for this action.",
                {"required_permission": permission, "user_roles": req.user.roles},
            )

    def route(method: str, pattern: str):
        def register(handler):
            routes.append((method, re.compile(f"^{pattern}$"), handler))
            return handler

        return register

    def require_document(document_id: str) -> dict:
        doc = platform.db.get_document(document_id)
        if not doc:
            raise HttpError(404, "NOT_FOUND", f"Document {document_id} not found")
        return doc

    def institution_scope(req: Request, requested: str | None = None) -> str:
        if not req.user or not req.user.institution_id:
            raise HttpError(403, "FORBIDDEN", "An institution identity is required.")
        if requested is not None and requested != req.user.institution_id:
            raise HttpError(403, "FORBIDDEN", "Access is limited to your institution.")
        return req.user.institution_id

    def require_scoped_document(req: Request, document_id: str) -> dict:
        doc = require_document(document_id)
        if doc["institution_id"] != institution_scope(req):
            raise HttpError(404, "NOT_FOUND", f"Document {document_id} not found")
        return doc

    def workspace(document_id: str) -> dict:
        data = platform.projections.get_document_workspace(document_id)
        if not data:
            raise HttpError(404, "NOT_FOUND", f"Document {document_id} not found")
        return data

    # ------------------------------------------------------------------ system

    @route("GET", "/api/v1/health")
    def health(req):
        return Response(
            200, {"status": "healthy", "service": "xtract", "version": xtract.__version__}
        )

    @route("GET", "/api/v1/branding")
    def branding(req):
        return Response(200, cfg.get_institution_profile())

    @route("GET", "/api/v1/packs")
    def list_packs(req):
        return Response(
            200,
            {
                "active_pack": cfg.deployment_pack or cfg.config_pack,
                "packs": cfg.available_packs(),
            },
        )

    @route("GET", "/api/v1/auth/config")
    def auth_config_route(req):
        return Response(200, auth_service.get_auth_config())

    @route("GET", "/api/v1/auth/me")
    def auth_me(req):
        if not req.user:
            raise HttpError(401, "UNAUTHORIZED", "Not authenticated.")
        return Response(200, req.user.to_dict())

    @route("POST", "/api/v1/auth/token")
    def auth_token(req):
        data = req.json()
        payload_token = str(data.get("api_token") or "")
        is_admin = (
            req.user
            and req.user.auth_method != "anonymous"
            and req.user.has_permission("admin:manage")
        )
        is_token_match = (
            cfg.api_token
            and payload_token
            and hmac.compare_digest(payload_token.encode(), cfg.api_token.encode())
        )
        if not (is_admin or is_token_match):
            raise HttpError(
                403 if req.user and req.user.auth_method != "anonymous" else 401,
                "FORBIDDEN" if req.user and req.user.auth_method != "anonymous" else "UNAUTHORIZED",
                "Admin authorization or valid api_token required.",
            )
        if not (cfg.jwt_secret or cfg.api_token):
            raise HttpError(
                503, "TOKEN_ISSUANCE_UNAVAILABLE", "No token signing secret configured."
            )
        # The shared bootstrap credential can provision institutions. An institutional
        # administrator may only delegate within their own institution.
        if is_token_match or (req.user and req.user.auth_method == "token"):
            token_institution = data.get("institution_id") or cfg.default_institution
        else:
            token_institution = institution_scope(req, data.get("institution_id"))
        user_id = str(
            data.get("user_id") or (req.user.user_id if req.user else req.actor) or "operator"
        )
        roles = data.get("roles")
        if roles is not None and (
            not isinstance(roles, list)
            or not roles
            or any(not isinstance(role, str) or role not in ROLE_PERMISSIONS for role in roles)
        ):
            raise HttpError(
                422, "INVALID_TYPE", "roles must be a non-empty list of supported roles."
            )
        expires_in = data.get("expires_in", 86400)
        if type(expires_in) is not int or not 1 <= expires_in <= 86400:
            raise HttpError(
                422, "INVALID_EXPIRY", "expires_in must be an integer from 1 to 86400 seconds."
            )
        token = auth_service.create_token(
            user_id=user_id,
            display_name=data.get("display_name"),
            email=str(data.get("email") or ""),
            roles=roles,
            institution_id=token_institution,
            office_id=data.get("office_id"),
            expires_in=expires_in,
        )
        return Response(
            200,
            {
                "access_token": token,
                "token_type": "Bearer",
                "expires_in": expires_in,
                "user_id": user_id,
                "roles": roles or ["operator"],
            },
        )

    @route("GET", "/api/v1/config")
    def config(req):
        return Response(
            200,
            {
                "version": xtract.__version__,
                "institution": cfg.get_institution_profile(),
                "config_pack": cfg.deployment_pack or cfg.config_pack,
                "available_packs": cfg.available_packs(),
                "document_families": platform.document_families(),
                "workflow_stages": WORKFLOW_STAGES,
                "reprocess_scopes": list(REPROCESS_SCOPES),
                "defaults": {
                    "institution_id": institution_scope(req),
                    "office_id": req.user.office_id,
                },
                "offices": cfg.offices,
                "max_upload_bytes": cfg.max_upload_bytes,
                "allowed_mime_types": sorted(platform.intake.config.allowed_mime_types),
                "ocr_engines": platform.ocr.engine_status(),
                "auth_required": auth_service.auth_required,
                "auth": auth_service.get_auth_config(),
            },
        )

    @route("GET", "/api/v1/stats")
    def stats(req):
        require_permission(req, "doc:read")
        return Response(
            200,
            platform.projections.get_stats(institution_scope(req, req.query.get("institution_id"))),
        )

    @route("GET", "/api/v1/connectors")
    def list_connectors(req):
        require_permission(req, "doc:read")
        return Response(200, {"connectors": platform.dispatcher.available_connectors()})

    # ------------------------------------------------------------------ documents

    @route("POST", "/api/v1/documents")
    def upload(req):
        require_permission(req, "field:edit")
        data = req.json()
        institution_id = institution_scope(req, data.get("institution_id"))
        office_id = data.get("office_id") or req.user.office_id
        if cfg.allowed_offices is not None and office_id not in cfg.allowed_offices:
            raise HttpError(422, "INVALID_OFFICE", "Choose an enabled institution office.")
        filename = str(data.get("filename") or "document")
        family = data.get("document_family") or "auto"
        if family != "auto" and family not in {
            f["family_code"] for f in platform.document_families()
        }:
            raise HttpError(422, "INVALID_FAMILY", "Unknown document family.")
        if data.get("content_base64"):
            try:
                content = base64.b64decode(data["content_base64"], validate=True)
            except (binascii.Error, ValueError) as exc:
                raise HttpError(
                    400, "INVALID_CONTENT", "content_base64 is not valid base64."
                ) from exc
        elif isinstance(data.get("text_content"), str):
            content = data["text_content"].encode("utf-8")
            data.setdefault("mime_type", "text/plain")
        else:
            raise HttpError(400, "MISSING_CONTENT", "Provide content_base64 or text_content.")
        try:
            doc, job = platform.intake.ingest_document(
                institution_id=institution_id,
                office_id=str(office_id)[:64],
                document_family=str(data.get("document_family") or "auto"),
                filename=filename,
                content=content,
                mime_type=data.get("mime_type"),
                title=data.get("title"),
                actor_id=req.actor,
            )
        except IntakeError as err:
            raise HttpError(
                INTAKE_STATUS.get(err.code, 400), err.code, err.message, err.details
            ) from err
        return Response(
            201,
            {
                "status": "accepted",
                "document_id": doc["document_id"],
                "job_id": job.job_id,
                "title": doc["title"],
                "workflow_stage": doc["current_workflow_stage"],
                "created_at": doc["created_at"],
            },
            headers=[("Location", f"/api/v1/documents/{doc['document_id']}")],
        )

    @route("GET", "/api/v1/documents")
    def search(req):
        require_permission(req, "doc:read")
        try:
            limit = max(1, min(int(req.query.get("limit", 200)), 1000))
        except ValueError:
            limit = 200
        return Response(
            200,
            platform.projections.search_documents(
                text_query=req.query.get("q") or None,
                workflow_stage=req.query.get("stage") or None,
                institution_id=institution_scope(req, req.query.get("institution_id")),
                limit=limit,
            ),
        )

    @route("GET", f"/api/v1/documents/{ID}")
    def get_workspace(req):
        return Response(200, workspace(req.params["document_id"]))

    @route("GET", f"/api/v1/documents/{ID}/source")
    def source(req):
        doc = require_document(req.params["document_id"])
        meta = doc["metadata_json"]
        try:
            content = platform.storage.get_object("documents-source", meta["source_object_key"])
        except (KeyError, FileNotFoundError) as exc:
            raise HttpError(404, "NOT_FOUND", "The original file is not available.") from exc
        filename = re.sub(r'["\\\r\n]', "_", meta.get("original_filename", "document"))
        disposition = "attachment" if req.query.get("download") else "inline"
        return Response(
            200,
            content,
            meta.get("mime_type", "application/octet-stream"),
            [
                ("Content-Disposition", f"{disposition}; filename*=UTF-8''{quote(filename)}"),
                ("Content-Security-Policy", "sandbox; frame-ancestors 'self'"),
                ("X-Frame-Options", "SAMEORIGIN"),
            ],
        )

    @route("GET", f"/api/v1/documents/{ID}/ocr")
    def ocr_output(req):
        doc = require_document(req.params["document_id"])
        key = f"{doc['institution_id']}/{doc['document_id']}/normalized_output.json"
        try:
            return Response(200, platform.storage.get_object("ocr-artifacts", key))
        except FileNotFoundError as exc:
            raise HttpError(404, "NOT_FOUND", "OCR has not produced output yet.") from exc

    @route("GET", f"/api/v1/documents/{ID}/export")
    def export_document(req):
        require_permission(req, "export:read")
        record = platform.exporter.research_record(
            req.params["document_id"], include_text=req.query.get("include_text") == "true"
        )
        if not record:
            raise HttpError(404, "NOT_FOUND", "Document not found")
        return Response(
            200,
            record,
            headers=[
                ("Content-Disposition", f'attachment; filename="{req.params["document_id"]}.json"')
            ],
        )

    @route("PUT", f"/api/v1/documents/{ID}/fields/(?P<field_code>[a-z0-9_]+)")
    def update_field(req):
        require_permission(req, "field:edit")
        data = req.json()
        platform.commands.update_field(
            req.params["document_id"],
            req.params["field_code"],
            data.get("value"),
            req.actor,
            comment=data.get("comment"),
            force=bool(data.get("force")),
        )
        return Response(200, workspace(req.params["document_id"]))

    @route("POST", f"/api/v1/documents/{ID}/fields/(?P<field_code>[a-z0-9_]+)/confirm")
    def confirm_field(req):
        require_permission(req, "field:edit")
        platform.commands.confirm_field(
            req.params["document_id"], req.params["field_code"], req.actor
        )
        return Response(200, workspace(req.params["document_id"]))

    @route("POST", f"/api/v1/documents/{ID}/review/complete")
    def complete_review(req):
        require_permission(req, "doc:approve")
        platform.commands.complete_review(
            req.params["document_id"], req.actor, req.json().get("comment")
        )
        return Response(200, workspace(req.params["document_id"]))

    @route("POST", f"/api/v1/documents/{ID}/review/reopen")
    def reopen_review(req):
        require_permission(req, "doc:approve")
        platform.commands.reopen_review(
            req.params["document_id"], req.actor, req.json().get("reason", "")
        )
        return Response(200, workspace(req.params["document_id"]))

    @route("POST", f"/api/v1/documents/{ID}/discard")
    def discard(req):
        require_permission(req, "doc:discard")
        platform.commands.discard(
            req.params["document_id"], req.actor, req.json().get("reason", "")
        )
        return Response(200, workspace(req.params["document_id"]))

    @route("POST", f"/api/v1/documents/{ID}/reprocess")
    def reprocess(req):
        require_permission(req, "doc:reprocess")
        data = req.json()
        if data.get("related_exception_id"):
            exc = platform.db.get_exception(data["related_exception_id"])
            if not exc or exc["document_id"] != req.params["document_id"]:
                raise HttpError(404, "NOT_FOUND", "Related exception not found for this document.")
        result = platform.commands.request_reprocessing(
            req.params["document_id"],
            str(data.get("scope", "extraction")),
            req.actor,
            reason_code=str(data.get("reason_code") or "operator_request"),
            comment=str(data.get("comment") or ""),
            related_exception_id=data.get("related_exception_id"),
        )
        return Response(202, result)

    @route("POST", f"/api/v1/documents/{ID}/integration/retry")
    def retry_integration(req):
        require_permission(req, "doc:reprocess")
        result = platform.commands.request_reprocessing(
            req.params["document_id"], "integration", req.actor, reason_code="integration_retry"
        )
        return Response(202, result)

    @route("POST", f"/api/v1/documents/{ID}/assistant")
    def ask(req):
        card = platform.assistant.answer(
            req.params["document_id"], str(req.json().get("prompt", "")), req.actor
        )
        if not card:
            raise HttpError(404, "NOT_FOUND", "Document not found")
        return Response(200, card)

    # ------------------------------------------------------------------ queues

    @route("GET", "/api/v1/review-queue")
    def review_queue(req):
        require_permission(req, "doc:read")
        return Response(
            200,
            platform.projections.get_review_queue(
                institution_scope(req, req.query.get("institution_id"))
            ),
        )

    @route("GET", "/api/v1/exceptions")
    def exceptions(req):
        require_permission(req, "doc:read")
        status = req.query.get("status") or None
        if status not in (None, "open", "resolved"):
            raise HttpError(422, "INVALID_STATUS", "status must be open or resolved")
        return Response(
            200,
            platform.projections.get_exception_inbox(
                institution_scope(req, req.query.get("institution_id")), status
            ),
        )

    @route("POST", "/api/v1/exceptions/(?P<exception_id>[0-9a-fA-F-]{36})/resolve")
    def resolve_exception(req):
        require_permission(req, "field:edit")
        exc = platform.commands.resolve_exception(
            req.params["exception_id"], req.actor, str(req.json().get("comment", ""))
        )
        return Response(
            200, {"exception_id": exc["exception_id"], "status": exc["exception_status"]}
        )

    # ------------------------------------------------------------------ exports

    def export_stage(req) -> str:
        stage = req.query.get("stage", "validated")
        if stage not in ("validated", "all", *WORKFLOW_STAGES):
            raise HttpError(422, "INVALID_STAGE", "Unknown stage filter")
        return stage

    def stamp() -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    @route("GET", "/api/v1/export/documents.jsonl")
    def export_jsonl(req):
        require_permission(req, "export:read")
        body = "".join(
            platform.exporter.iter_jsonl(
                export_stage(req),
                req.query.get("include_text") == "true",
                institution_id=institution_scope(req, req.query.get("institution_id")),
            )
        )
        return Response(
            200,
            body,
            "application/x-ndjson; charset=utf-8",
            [("Content-Disposition", f'attachment; filename="xtract-documents-{stamp()}.jsonl"')],
        )

    @route("GET", "/api/v1/export/documents.json")
    def export_json(req):
        require_permission(req, "export:read")
        return Response(
            200,
            platform.exporter.export_json(
                export_stage(req),
                institution_id=institution_scope(req, req.query.get("institution_id")),
            ),
            headers=[
                ("Content-Disposition", f'attachment; filename="xtract-documents-{stamp()}.json"')
            ],
        )

    @route("GET", "/api/v1/export/fields.csv")
    def export_csv(req):
        require_permission(req, "export:read")
        return Response(
            200,
            platform.exporter.export_csv(
                export_stage(req),
                institution_id=institution_scope(req, req.query.get("institution_id")),
            ),
            "text/csv; charset=utf-8",
            [("Content-Disposition", f'attachment; filename="xtract-fields-{stamp()}.csv"')],
        )

    # ------------------------------------------------------------------ static portal

    portal_root = cfg.portal_dir.resolve()
    # Branding directory can be customized via XTRACT_BRANDING_DIR
    branding_root = cfg.branding_dir.resolve()

    def static(req) -> Response:
        if req.method not in ("GET", "HEAD"):
            raise HttpError(405, "METHOD_NOT_ALLOWED", "Method not allowed")
        if req.path.startswith("/branding/"):
            base, relative = branding_root, req.path[len("/branding/") :]
        else:
            base, relative = portal_root, req.path.lstrip("/") or "index.html"
        target = (base / relative).resolve()
        if not target.is_relative_to(base) or not target.is_file() or target.name.endswith(".md"):
            raise HttpError(404, "NOT_FOUND", f"Not found: {req.path}")
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type.endswith("javascript"):
            content_type += "; charset=utf-8"
        return Response(
            200,
            target.read_bytes(),
            content_type,
            [("Cache-Control", "no-cache"), ("Content-Security-Policy", CSP)],
        )

    # ------------------------------------------------------------------ dispatch

    def authorized(req: Request) -> bool:
        req.user = auth_service.authenticate(req)
        if not req.path.startswith("/api/") or req.path in (
            "/api/v1/health",
            "/api/v1/branding",
            "/api/v1/packs",
            "/api/v1/auth/config",
            "/api/v1/auth/token",
        ):
            return True
        return req.user is not None

    def handle(req: Request) -> Response:
        if not authorized(req):
            raise HttpError(401, "UNAUTHORIZED", "A valid API token is required.")
        if not req.path.startswith("/api/"):
            return static(req)
        path_matched = False
        for method, pattern, handler in routes:
            match = pattern.match(req.path.rstrip("/") or "/")
            if not match:
                continue
            path_matched = True
            if method == req.method or (method == "GET" and req.method == "HEAD"):
                req.params = match.groupdict()
                # Check every document route before reading artifacts or applying commands.
                if "document_id" in req.params:
                    require_permission(req, "doc:read")
                    require_scoped_document(req, req.params["document_id"])
                if "exception_id" in req.params:
                    require_permission(req, "doc:read")
                    exc = platform.db.get_exception(req.params["exception_id"])
                    if not exc:
                        raise HttpError(404, "NOT_FOUND", "Exception not found")
                    require_scoped_document(req, exc["document_id"])
                return handler(req)
        if path_matched:
            raise HttpError(405, "METHOD_NOT_ALLOWED", "Method not allowed")
        raise HttpError(404, "NOT_FOUND", f"Not found: {req.path}")

    def application(environ, start_response):
        req = Request(environ, max_body=int(cfg.max_upload_bytes * 1.4) + 65536)
        cors = []
        origin = req.header("Origin")
        if origin and origin in cfg.cors_origins:
            cors = [
                ("Access-Control-Allow-Origin", origin),
                ("Vary", "Origin"),
                (
                    "Access-Control-Allow-Headers",
                    "Authorization, Content-Type, X-Operator-Id, "
                    "X-Forwarded-User, X-Forwarded-Roles, X-Forwarded-Email, "
                    "X-Forwarded-Institution, X-Forwarded-Office",
                ),
                ("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS"),
            ]
        if req.method == "OPTIONS":
            response = Response(204)
        else:
            try:
                response = handle(req)
            except HttpError as err:
                response = Response(
                    err.status, {"error": err.code, "message": err.message, "details": err.details}
                )
            except CommandError as err:
                response = Response(
                    err.status, {"error": err.code, "message": err.message, "details": err.details}
                )
            except Exception:
                logger.exception("Unhandled error for %s %s", req.method, req.path)
                response = Response(
                    500, {"error": "INTERNAL_ERROR", "message": "Unexpected server error."}
                )
        supplied = {name.lower() for name, _ in response.headers}
        headers = (
            response.headers
            + [(k, v) for k, v in SECURITY_HEADERS if k.lower() not in supplied]
            + cors
        )
        if req.path.startswith("/api/"):
            headers.append(("Cache-Control", "no-store"))
        headers.append(("Content-Length", str(len(response.body))))
        start_response(f"{response.status} {STATUS_TEXT.get(response.status, 'OK')}", headers)
        return [b""] if req.method == "HEAD" else [response.body]

    application.platform = platform
    return application
