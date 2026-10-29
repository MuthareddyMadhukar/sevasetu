# Sewa Setu — Old Age Pension Portal

Department of Social Welfare, Government of Purvanchal. Maintained in-house.

## Running

```
ADMIN_PASSWORD=pick-something docker compose up --build
```

- Portal: http://localhost:8000
- Status portal: http://localhost:8000/status (mobile number + password; the
  password is the applicant's date of birth as DDMMYYYY)
- Departmental login: http://localhost:8000/admin (user `admin`, password from
  `ADMIN_PASSWORD`)
- SMS gateway console (simulated telecom): http://localhost:8000/__gateway/ —
  OTPs and notifications appear here once "delivered" (1–4 s carrier latency).
  The gateway's inbox is also readable as JSON at
  `/__gateway/api/messages?to=<mobile>`.
- Database: Postgres, loaded from `seed/seed.sql` on first boot (~100k applications).

## Deploying on a server

Set `PUBLIC_BASE_URL` to the address people will use (for example
`https://sewasetu.example.in`). It is stamped into sign-in tokens and the discovery documents
described below, so a wrong value means other applications cannot find the sign-in page. Put
the portal behind HTTPS; some applications refuse to sign in over plain HTTP.

```
PUBLIC_BASE_URL=https://sewasetu.example.in ADMIN_PASSWORD=pick-something docker compose up --build -d
```

## What the portal does

Citizen flow: mobile → OTP → personal details → address → bank details →
age-proof upload → preview and declaration → application number. A nightly
job (`scripts/deemed_approval.py`, via cron in the `scheduler` container)
deems approved any application still pending after the 15-day statutory SLA.

Rules enforced at submission, in `validate_application()` in `app/app.py`:
applicant is 60 years of age or above; required fields and an age-proof
document are present; the scheme window is open; and the mobile number holds
no other active (pending / approved / deemed-approved) application. A pending
application can be withdrawn from the status portal, after which the same
mobile may apply again.

Departmental users see a dashboard, list and filter applications, approve or
reject pending ones, and see the audit trail per application.

## Layout

```
app/          Flask application, templates, config, nightly job
seed/         seed.sql — production data snapshot
smsgw/        simulated SMS gateway
```

## Letting other applications act for a citizen or an officer

Sewa Setu is also an **OAuth 2.1 authorization server**. A third-party application can act
for a citizen (scope `citizen`) or for a block officer (scope `officer`) once that person
signs in on the portal and approves it. Citizens sign in by mobile and OTP, officers with the
departmental login. The application never handles the OTP or the password.

- Discovery: `/.well-known/oauth-authorization-server` (RFC 8414)
- Registration: `/oauth/register` (RFC 7591), or a client ID metadata document URL as `client_id`
- Authorization: `/oauth/authorize` (authorization code with PKCE S256; the `resource` the
  application asks for becomes the token's audience, RFC 8707)
- Tokens: `/oauth/token`. Access tokens are RS256 JWTs. A sign-in is a **session with an
  absolute end**: 2 hours for a citizen, 8 hours for an officer, counted from the consent.
  Access tokens are short (20 / 30 minutes) and refresh tokens rotate within the session but
  never extend it; after it ends the person signs in again. Portals are used on shared phones
  and kiosks.
- Sign-out: `/oauth/revoke` (RFC 7009). People can also end any sign-in from the status
  portal (**Connected applications**) or, for officers, the admin dashboard.
- Keys: `/.well-known/jwks.json`

A service that receives one of these tokens verifies it with the JWKS, checks `iss` is this
portal, checks `aud` is its own canonical URL, and reads `scope`, `role` and `sub`
(`citizen:<mobile>` or `officer:<username>`).

Long-lived **program tokens** for unattended use (role officer) are issued by an
administrator at `/admin/tokens`.

## Agent-Ready Model Context Protocol (MCP) Endpoints

Sewa Setu exposes two isolated Model Context Protocol (MCP) servers over Streamable HTTP (complying with the 2024-11-05 MCP specification):

### 1. Citizen MCP Server
- **Streamable HTTP Endpoint:** `http://localhost:8000/mcp/citizen`
- **Server-Sent Events (SSE) Stream:** `http://localhost:8000/mcp/citizen/sse`
- **Scope:** `citizen`
- **Available Tools:**
  - `get_scheme_guidelines`: Get official eligibility rules, ₹250/mo benefit, required documents, and 15-day SLA.
  - `check_eligibility`: Verify age (60+), block jurisdiction, and duplicate application status.
  - `request_otp`: Dispatch a 6-digit OTP to citizen's mobile via the simulated SMS gateway.
  - `verify_otp`: Authenticate mobile OTP and return session context.
  - `upload_age_proof`: Upload and attach age-proof document (Voter ID, Aadhaar, School/Medical certificate).
  - `submit_application`: Validate and insert a full pension application into PostgreSQL, write audit trail, create status account, and dispatch SMS.
  - `get_application_status`: Track live application state by mobile or application number.
  - `withdraw_application`: Withdraw a pending application so the applicant can correct mistakes and re-apply.

### 2. Block Officer MCP Server
- **Streamable HTTP Endpoint:** `http://localhost:8000/mcp/officer`
- **Server-Sent Events (SSE) Stream:** `http://localhost:8000/mcp/officer/sse`
- **Scope:** `officer`
- **Authentication:** OAuth 2.1 Bearer token, Program Token, or Departmental credentials.
- **Available Tools:**
  - `get_officer_dashboard`: Live queue metrics, overdue cases exceeding 15-day statutory SLA, and block-wise pending breakdown.
  - `list_applications`: Filter applications by block, status, mobile, or overdue flag with pagination.
  - `get_application_details`: Comprehensive applicant demographic, banking, and document details with audit history.
  - `decide_application`: Approve or reject pending applications with required justification note in the permanent audit trail.
  - `get_audit_history`: Inspect immutable audit timeline for any application.

## Evaluation Dashboard & Automated Personas

- **Interactive Dashboard:** `http://localhost:8000/eval-dashboard`  
  Displays live test results for 8 diverse citizen and officer personas (Phuleswari, Bhaben, Gunaram, Tara, Hemkanti, Ramen, Officer Barua, Officer Gogoi), step-by-step tool transcripts, and real-time database state assertions against PostgreSQL.
- **Run Evaluations via API:** `POST http://localhost:8000/api/eval/run`
- **Run Evaluations via CLI:**
  ```bash
  python evals/run_evals.py
  ```
- **Persona Definitions:** See `evals/personas.json`.
- **Design Note:** See `DESIGN-NOTE.md` for the three key decisions and alternative.
- **Loom Walkthrough Script:** See `LOOM-SCRIPT.md` for the 3-minute video presentation guide.

