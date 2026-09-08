from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.auth import CLEARANCES, REQUESTED_ROLES, USER_STATUSES


def _clean_email(value: str) -> str:
    value = value.strip().lower()
    if "@" not in value or value.startswith("@") or value.endswith("@") or len(value) > 254:
        raise ValueError("enter a valid email address")
    return value


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    _normalise_email = field_validator("email")(_clean_email)


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    active: bool
    created_at: datetime


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.strip().split())
        if not value:
            raise ValueError("department name must not be blank")
        if "/" in value:
            raise ValueError("department name must not contain '/'")
        return value


class GrantOut(BaseModel):
    department: str
    clearance: str
    is_home: bool
    granted_at: datetime


class UserOut(BaseModel):
    id: int
    full_name: str
    email: str
    role: str
    home_department: str | None
    status: str
    grants: list[GrantOut]
    created_at: datetime


class AuthMe(UserOut):
    pass


class RegistrationCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=128)
    requested_department: str
    requested_role: str = "department_user"

    _normalise_email = field_validator("email")(_clean_email)

    @field_validator("full_name", "requested_department")
    @classmethod
    def clean_text(cls, value: str) -> str:
        value = " ".join(value.strip().split())
        if not value:
            raise ValueError("value must not be blank")
        return value

    @field_validator("requested_role")
    @classmethod
    def valid_role(cls, value: str) -> str:
        if value not in REQUESTED_ROLES:
            raise ValueError(f"requested_role must be one of {REQUESTED_ROLES}")
        return value


class RegistrationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: str
    requested_department: str
    requested_role: str
    status: str
    reviewed_by: int | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    created_at: datetime


class RegistrationSubmitted(BaseModel):
    request_id: int
    status: str


class RegistrationApproval(BaseModel):
    clearance: str = "viewer"

    @field_validator("clearance")
    @classmethod
    def valid_clearance(cls, value: str) -> str:
        if value not in CLEARANCES:
            raise ValueError(f"clearance must be one of {CLEARANCES}")
        return value


class RegistrationRejection(BaseModel):
    reason: str = Field(min_length=2, max_length=500)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        value = " ".join(value.strip().split())
        if len(value) < 2:
            raise ValueError("reason must contain at least two characters")
        return value


class GrantUpdate(BaseModel):
    clearance: str

    @field_validator("clearance")
    @classmethod
    def valid_clearance(cls, value: str) -> str:
        if value not in CLEARANCES:
            raise ValueError(f"clearance must be one of {CLEARANCES}")
        return value


class UserStatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def valid_status(cls, value: str) -> str:
        if value not in USER_STATUSES:
            raise ValueError(f"status must be one of {USER_STATUSES}")
        return value


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_user_id: int | None
    actor_email: str | None
    action: str
    target_type: str
    target_id: str | None
    department: str | None
    result: str
    details: dict | None
    occurred_at: datetime


class AuditEventPage(BaseModel):
    """One page of audit history, plus the total so a caller can page.

    `total` is the count *after* the caller's own visibility filter, so a
    department admin is never told how many events exist outside their scope.
    """

    total: int
    limit: int
    offset: int
    events: list[AuditEventOut]
