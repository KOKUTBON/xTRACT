"""User, role, and permission data structures for institutional RBAC."""

from __future__ import annotations

from dataclasses import dataclass, field

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        "doc:read",
        "field:edit",
        "doc:approve",
        "doc:discard",
        "doc:reprocess",
        "export:read",
        "admin:manage",
    },
    "supervisor": {
        "doc:read",
        "field:edit",
        "doc:approve",
        "doc:discard",
        "doc:reprocess",
        "export:read",
    },
    "operator": {
        "doc:read",
        "field:edit",
        "doc:approve",
        "export:read",
    },
    "viewer": {
        "doc:read",
        "export:read",
    },
    "auditor": {
        "doc:read",
        "export:read",
    },
}

ALL_PERMISSIONS: set[str] = {
    "doc:read",
    "field:edit",
    "doc:approve",
    "doc:discard",
    "doc:reprocess",
    "export:read",
    "admin:manage",
}


@dataclass
class AuthUser:
    """Authenticated institutional operator context."""

    user_id: str
    display_name: str
    email: str = ""
    institution_id: str = "default"
    office_id: str = "general"
    roles: list[str] = field(default_factory=lambda: ["operator"])
    auth_method: str = "anonymous"

    @property
    def permissions(self) -> set[str]:
        perms: set[str] = set()
        for role in self.roles:
            perms.update(ROLE_PERMISSIONS.get(role.lower(), set()))
        return perms

    def has_permission(self, permission: str) -> bool:
        if "admin" in [r.lower() for r in self.roles]:
            return True
        return permission in self.permissions

    def has_role(self, *roles: str) -> bool:
        user_roles = {r.lower() for r in self.roles}
        return any(role.lower() in user_roles for role in roles)

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "display_name": self.display_name,
            "email": self.email,
            "institution_id": self.institution_id,
            "office_id": self.office_id,
            "roles": sorted(self.roles),
            "permissions": sorted(self.permissions),
            "auth_method": self.auth_method,
        }
