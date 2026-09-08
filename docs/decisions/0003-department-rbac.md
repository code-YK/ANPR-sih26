# ADR 0003: Department-scoped demo RBAC

Status: Accepted

Date: 2026-08-30

Owners: Team

## Context

Sentinel combines cameras and derived records from multiple government departments. The Phase 1 UI and API previously had no identity boundary, so anyone who could reach the service could read source metadata, launch analytics, edit the registry, or alter alerts. `GOV-M1-007`, `GOV-NFR-001`, and `GOV-NFR-003` require a demonstrable least-privilege boundary, but a production identity-provider integration would expand the demo beyond the current checkpoint.

## Decision

Use three fixed roles for the Phase 1 demo:

- `super_admin`: global administration, department creation, approval of department-admin requests, cross-department grants, global watchlist management, catalogue-wide operations, and all department data;
- `department_admin`: approval and account/clearance management for `department_user` registrations in the admin's home department, plus camera metadata administration in that home department; and
- `department_user`: no administrative authority; effective capabilities come from department grants.

Every department grant has `viewer` or `operator` clearance. The home-department grant is created automatically at approval and cannot be revoked. A super admin can add or revoke grants for other departments. `viewer` is read-only. `operator` also permits analytics/probe/geocode/capture actions for one authorised camera and alert acknowledge/resolve. A department admin's home grant is always `operator`.

Registration is request/approval based. A super admin approves department-admin requests. A department admin may approve only department-user requests for their own home department. Multiple department admins per department are allowed. Direct user creation, custom roles, delegation, time-bounded grants, and multi-stage approvals are not part of Phase 1.

Human authentication uses opaque random sessions in an HttpOnly, SameSite cookie; only a SHA-256 digest is stored. Passwords use the standard-library scrypt KDF with per-password salts. The demo super admin is idempotently seeded from environment variables, never from a committed credential. Analytics ingestion uses a separate worker token and cannot reuse a browser session.

The API remains the enforcement point. Camera lists, live relay, observations, alerts, analytics, journeys, reports, and survey frames are scoped by department before response. Journey results disclose the count of restricted stops but not their camera, location, time, or department. Raw RTSP/HLS/WebRTC endpoints remain server-side; clients receive only `stream_available` and use the authenticated relay.

Application audit events are append-only through the API and record actor, UTC time, action, target, department, result, and optional details for authentication, approvals, grants, account state, registry changes, watchlist changes, and alert transitions. Authenticated metadata `GET` responses and authentication/authorisation denials are also recorded centrally against the matched route template, never raw URL/query values. High-frequency HLS/media and telemetry *successful reads* are excluded to prevent audit-volume amplification; denials remain auditable. Migration `202608311800` adds a database trigger that rejects audit-row updates and deletes for the application database role. It permits only the database-managed `actor_user_id` → `NULL` update required by the existing account-deletion foreign key. A super admin may download a canonical snapshot or explicitly deliver it, with a detached SHA-256 checksum and exclusive-create semantics, to an administrator-configured external retention mount.

## Consequences

Positive:

- the demo has a small, explainable role and clearance model;
- home access needs no repetitive manual grant;
- cross-department collaboration is explicit and centrally controlled;
- frontend hiding and server-side enforcement use the same policy; and
- browser and worker credentials are separated.

Negative:

- local passwords and sessions are suitable only for the demo, not production SSO;
- the trigger protects audit rows from application-role `UPDATE`/`DELETE`, but a database superuser or schema owner can still alter the trigger or table; the application now delivers snapshots to an external mount, but that destination must be provisioned with WORM/object-lock retention before a hosted or production use;
- high-frequency HLS/media and telemetry successful reads are deliberately excluded from per-request audit to prevent audit-volume amplification;
- account recovery, MFA, CSRF tokens, rate limiting, session rotation policy, and central revocation are not production-complete; and
- the current department name is a stable key, so renaming a department is deliberately unsupported.

## Alternatives considered

- Super-admin-only approvals and grants: simpler, but it does not demonstrate delegated department governance.
- Full permission/role editor: more flexible, but too large and difficult to explain for this checkpoint.
- External OIDC/SAML identity provider: the production direction, deferred until deployment identity requirements and an authorised provider are known.

## Validation / revisit trigger

- `backend/scripts/rbac_smoke_test.py` must pass against a migrated local database.
- The general smoke suite must continue to pass with authentication and worker credentials enabled.
- Revisit before any hosted or production pilot to integrate an authorised identity provider, MFA, stronger session controls, CSRF/rate-limit protections, a tested WORM/object-lock audit-retention destination, and centrally managed secrets.
