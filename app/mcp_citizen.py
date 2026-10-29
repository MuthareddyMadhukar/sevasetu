# -*- coding: utf-8 -*-
"""
Sewa Setu - Citizen MCP Server.
Provides dedicated MCP tools for applicants and their assistants.
Runs over Streamable HTTP / SSE at /mcp/citizen.
Strictly isolated: does not expose or permit any officer actions.
"""

import os
import re
import base64
import random
import secrets
from datetime import datetime, date
from typing import Dict, Any, Optional

import app as portal
from mcp_protocol import MCPServer

citizen_server = MCPServer(
    name="sewasetu-citizen",
    version="1.0.0",
    description="Sewa Setu Citizen Assistant MCP Server for Old Age Pension Scheme applications and tracking"
)

# In-memory store for verified OTP sessions (token -> mobile, expires_at)
_VERIFIED_SESSIONS = {}


def _get_verified_mobile(session_token: Optional[str]) -> Optional[str]:
    if not session_token or session_token not in _VERIFIED_SESSIONS:
        return None
    sess = _VERIFIED_SESSIONS[session_token]
    if (datetime.now() - sess["created_at"]).total_seconds() > 7200:  # 2 hours
        _VERIFIED_SESSIONS.pop(session_token, None)
        return None
    return sess["mobile"]


# ---------------------------------------------------------------------------
# Citizen Tools
# ---------------------------------------------------------------------------

@citizen_server.register_tool(
    name="get_scheme_guidelines",
    description="Retrieve official guidelines, rules, required documents, pension amount, and processing timelines for the Government of Purvanchal Old Age Pension Scheme.",
    input_schema={
        "type": "object",
        "properties": {},
        "required": []
    }
)
def get_scheme_guidelines(args: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    hours_left = portal.deadline_remaining()
    return {
        "scheme_name": "Government of Purvanchal - Old Age Pension Scheme (Sewa Setu)",
        "department": "Department of Social Welfare",
        "monthly_pension": "₹250 per month",
        "eligibility_criteria": {
            "minimum_age": portal.MIN_AGE,
            "residence": "Resident of Purvanchal within recognized blocks",
            "recognized_blocks": portal.BLOCKS,
            "income_or_other_criteria": "Universal for senior citizens aged 60+ in eligible blocks"
        },
        "required_documents": [
            "Age proof document (Voter ID card, Aadhaar, School Certificate, or Medical Board Age Certificate)",
            "Active 10-digit mobile number for OTP verification and SMS updates",
            "Valid Bank Account Number (9 to 18 digits)",
            "Bank IFSC Code (11 characters, e.g., SBIN0003077)"
        ],
        "application_deadline": portal.SCHEME_DEADLINE.strftime("%Y-%m-%d %H:%M IST"),
        "hours_remaining": hours_left if hours_left is not None else 0,
        "is_window_open": hours_left is not None,
        "statutory_sla": f"{portal.SLA_DAYS} days under the Purvanchal Right to Public Services (RTPS) Act",
        "deemed_approval": f"If an application is not processed by a block officer within {portal.SLA_DAYS} days, it is automatically approved by law.",
        "status_tracking": "Applicants can track their application at any time using their mobile number and date of birth (DDMMYYYY) as password."
    }


@citizen_server.register_tool(
    name="check_eligibility",
    description="Check whether an applicant meets the scheme's criteria before applying. Checks age (60+), block, active application on mobile, and window.",
    input_schema={
        "type": "object",
        "properties": {
            "dob": {
                "type": "string",
                "description": "Date of birth in DD/MM/YYYY format, e.g., '15/04/1954'"
            },
            "block": {
                "type": "string",
                "description": f"Block in Purvanchal. Must be one of: {', '.join(portal.BLOCKS)}"
            },
            "mobile": {
                "type": "string",
                "description": "Optional 10-digit mobile number to verify if an active application already exists"
            }
        },
        "required": ["dob", "block"]
    }
)
def check_eligibility(args: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    dob_raw = args.get("dob", "")
    block_raw = (args.get("block") or "").strip()
    mobile_raw = (args.get("mobile") or "").strip()

    dob = portal.parse_dob(dob_raw)
    checks = []
    eligible = True

    # 1. Scheme deadline check
    if portal.now_ist() > portal.SCHEME_DEADLINE:
        checks.append({"rule": "Scheme Window", "passed": False, "detail": "The scheme application window has closed."})
        eligible = False
    else:
        checks.append({"rule": "Scheme Window", "passed": True, "detail": "Application window is currently open."})

    # 2. DOB and Age check
    if dob is None:
        checks.append({"rule": "Age Requirement", "passed": False, "detail": "Date of birth must be in DD/MM/YYYY format."})
        eligible = False
        age = None
    else:
        age = portal.age_on(dob, portal.now_ist().date())
        if age < portal.MIN_AGE:
            checks.append({"rule": "Age Requirement", "passed": False,
                           "detail": f"Applicant is {age} years old. Must be at least {portal.MIN_AGE} years of age."})
            eligible = False
        else:
            checks.append({"rule": "Age Requirement", "passed": True,
                           "detail": f"Applicant is {age} years old (meets minimum requirement of {portal.MIN_AGE})."})

    # 3. Block check
    if block_raw not in portal.BLOCKS:
        checks.append({"rule": "Block Jurisdiction", "passed": False,
                       "detail": f"'{block_raw}' is not a recognized block. Must be one of: {', '.join(portal.BLOCKS)}"})
        eligible = False
    else:
        checks.append({"rule": "Block Jurisdiction", "passed": True, "detail": f"'{block_raw}' is recognized."})

    # 4. Mobile duplication check
    existing_app = None
    if mobile_raw:
        if len(mobile_raw) == 10 and mobile_raw.isdigit():
            conn = portal.get_db()
            cur = conn.cursor()
            existing = portal.active_application(cur, mobile_raw)
            cur.close()
            conn.close()
            if existing:
                existing_app = {"id": existing[0], "application_no": existing[1], "status": existing[2]}
                checks.append({
                    "rule": "Single Active Application",
                    "passed": False,
                    "detail": f"Mobile {mobile_raw} already holds an active application {existing[1]} ({existing[2]}). Must withdraw before re-applying."
                })
                eligible = False
            else:
                checks.append({"rule": "Single Active Application", "passed": True, "detail": "No active application on this mobile."})

    return {
        "eligible": eligible,
        "age": age,
        "checks": checks,
        "existing_application": existing_app,
        "recommendation": "You are eligible to apply!" if eligible else "Applicant is currently not eligible. Please review failed checks above."
    }


@citizen_server.register_tool(
    name="request_otp",
    description="Send a 6-digit OTP to the citizen's mobile number via SMS to authenticate identity before applying or managing applications.",
    input_schema={
        "type": "object",
        "properties": {
            "mobile": {
                "type": "string",
                "description": "10-digit Indian mobile number (e.g. '9217729489')"
            }
        },
        "required": ["mobile"]
    }
)
def request_otp(args: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    mobile = (args.get("mobile") or "").strip()
    if len(mobile) != 10 or not mobile.isdigit():
        return {
            "success": False,
            "error": "Invalid mobile number. Please provide a 10-digit mobile number."
        }

    code = f"{random.randint(100000, 999999):06d}"
    conn = portal.get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO otps (mobile, code, created_at) VALUES (%s, %s, %s)",
                (mobile, code, datetime.now()))
    conn.commit()
    cur.close()
    conn.close()

    portal.send_sms(mobile, f"Your Sewa Setu OTP is {code}. Valid for 5 minutes.")
    return {
        "success": True,
        "mobile": mobile,
        "message": f"OTP sent to {mobile}. Valid for {portal.OTP_VALIDITY_SECONDS // 60} minutes. Check SMS inbox or SMS gateway console.",
        "validity_seconds": portal.OTP_VALIDITY_SECONDS
    }


@citizen_server.register_tool(
    name="verify_otp",
    description="Verify the 6-digit OTP received on the applicant's mobile number. Returns an authentication session token.",
    input_schema={
        "type": "object",
        "properties": {
            "mobile": {
                "type": "string",
                "description": "10-digit mobile number"
            },
            "otp": {
                "type": "string",
                "description": "6-digit OTP code"
            }
        },
        "required": ["mobile", "otp"]
    }
)
def verify_otp(args: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    mobile = (args.get("mobile") or "").strip()
    code = (args.get("otp") or "").strip()

    conn = portal.get_db()
    cur = conn.cursor()
    cur.execute("SELECT code, created_at FROM otps WHERE mobile = %s ORDER BY id DESC LIMIT 1", (mobile,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row or row[0] != code:
        return {
            "verified": False,
            "error": "Invalid OTP. Please check the code and try again."
        }

    age = (datetime.now() - row[1]).total_seconds()
    if age > portal.OTP_VALIDITY_SECONDS:
        return {
            "verified": False,
            "error": "OTP has expired. Please request a new OTP."
        }

    session_token = "sess_" + secrets.token_urlsafe(24)
    _VERIFIED_SESSIONS[session_token] = {
        "mobile": mobile,
        "created_at": datetime.now()
    }

    return {
        "verified": True,
        "mobile": mobile,
        "session_token": session_token,
        "message": "Mobile number verified successfully. You may now submit your pension application."
    }


@citizen_server.register_tool(
    name="upload_age_proof",
    description="Attach an age-proof document (e.g. Voter ID, School Certificate, Medical Certificate). Accepts base64 encoded data, or 'sample' to generate standard sample proof.",
    input_schema={
        "type": "object",
        "properties": {
            "mobile": {
                "type": "string",
                "description": "10-digit mobile number of the applicant"
            },
            "filename": {
                "type": "string",
                "description": "Filename with extension (e.g., 'voter_id.jpg', 'aadhaar.pdf', 'age_proof.png')"
            },
            "file_content_base64": {
                "type": "string",
                "description": "Base64 encoded file content, or 'sample' to generate a valid test placeholder document"
            }
        },
        "required": ["mobile", "filename"]
    }
)
def upload_age_proof(args: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    mobile = (args.get("mobile") or "").strip()
    filename = (args.get("filename") or "").lower().strip()
    content_b64 = args.get("file_content_base64", "sample")

    ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
    if ext not in ("pdf", "jpg", "jpeg", "png"):
        return {
            "success": False,
            "error": "Invalid document format. Allowed extensions are: PDF, JPG, JPEG, PNG."
        }

    if content_b64 == "sample" or not content_b64:
        content = f"%PDF-1.4 Simulated Age Proof for {mobile} - Sewa Setu Portal".encode("utf-8")
        if not filename.endswith(".pdf"):
            filename = f"{filename}.pdf"
    else:
        try:
            content = base64.b64decode(content_b64)
        except Exception:
            return {"success": False, "error": "Invalid base64 encoding for file content."}

    if len(content) > 5 * 1024 * 1024:
        return {"success": False, "error": "File size exceeds maximum permitted limit of 5 MB."}

    os.makedirs(portal.UPLOAD_DIR, exist_ok=True)
    safe_name = os.path.basename(filename)
    path = os.path.join(portal.UPLOAD_DIR, f"{mobile}_{safe_name}")
    with open(path, "wb") as fh:
        fh.write(content)

    return {
        "success": True,
        "doc_path": path,
        "filename": safe_name,
        "size_bytes": len(content),
        "message": "Age-proof document uploaded successfully."
    }


@citizen_server.register_tool(
    name="submit_application",
    description="Submit a complete Old Age Pension application. Strict portal validation rules apply. If successful, creates an application, registers a status-portal account (password is DOB as DDMMYYYY), logs the audit trail, and sends an SMS acknowledgment.",
    input_schema={
        "type": "object",
        "properties": {
            "mobile": {
                "type": "string",
                "description": "10-digit mobile number of the applicant"
            },
            "applicant_name": {
                "type": "string",
                "description": "Full name of the senior citizen"
            },
            "dob": {
                "type": "string",
                "description": "Date of birth in DD/MM/YYYY format"
            },
            "gender": {
                "type": "string",
                "enum": ["Male", "Female", "Other"],
                "description": "Gender of the applicant"
            },
            "marital_status": {
                "type": "string",
                "enum": ["Married", "Widowed", "Unmarried", "Divorced"],
                "description": "Marital status"
            },
            "husband_name": {
                "type": "string",
                "description": "Husband's name if applicable (e.g. for widows)"
            },
            "village": {
                "type": "string",
                "description": "Village name in Purvanchal"
            },
            "block": {
                "type": "string",
                "description": f"Block name. Must be one of: {', '.join(portal.BLOCKS)}"
            },
            "bank_account": {
                "type": "string",
                "description": "Bank account number (9 to 18 digits)"
            },
            "ifsc": {
                "type": "string",
                "description": "11-character bank IFSC code (e.g., 'SBIN0003077')"
            },
            "doc_path": {
                "type": "string",
                "description": "Path to uploaded age-proof document. If omitted, a verified document will be auto-attached."
            },
            "session_token": {
                "type": "string",
                "description": "Optional verified session token from verify_otp"
            }
        },
        "required": [
            "mobile", "applicant_name", "dob", "gender", "marital_status",
            "village", "block", "bank_account", "ifsc"
        ]
    }
)
def submit_application(args: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    mobile = (args.get("mobile") or "").strip()
    session_token = args.get("session_token")

    # If session token is provided, ensure it matches mobile
    if session_token:
        verified_mobile = _get_verified_mobile(session_token)
        if verified_mobile and verified_mobile != mobile:
            return {"success": False, "error": f"Session token mobile ({verified_mobile}) does not match application mobile ({mobile})."}

    # Document path: if missing, auto-generate standard sample document
    doc_path = args.get("doc_path")
    if not doc_path:
        os.makedirs(portal.UPLOAD_DIR, exist_ok=True)
        doc_path = os.path.join(portal.UPLOAD_DIR, f"{mobile}_voter_id.pdf")
        if not os.path.exists(doc_path):
            with open(doc_path, "wb") as f:
                f.write(f"%PDF-1.4 Age proof document for {mobile}".encode("utf-8"))

    # Strict portal validation
    errors, cleaned = portal.validate_application(args, doc_path)
    if errors:
        return {
            "success": False,
            "error": "Validation failed: " + "; ".join(errors),
            "validation_errors": errors
        }

    conn = portal.get_db()
    cur = conn.cursor()

    # Active application duplicate prevention
    existing = portal.active_application(cur, mobile)
    if existing:
        cur.close()
        conn.close()
        return {
            "success": False,
            "error": f"Application {existing[1]} ({existing[2]}) already exists for mobile {mobile}. A pending application can be withdrawn from the status portal if you need to apply afresh.",
            "existing_application": {"id": existing[0], "application_no": existing[1], "status": existing[2]}
        }

    # Insert into applications, portal_users, and audit_log
    new_id, app_no = portal.create_application(cur, mobile, cleaned)
    conn.commit()
    cur.close()
    conn.close()

    # Send confirmation SMS
    portal.send_sms(
        mobile,
        f"Sewa Setu: application {app_no} received. Track at the status portal with mobile no. and password (DOB as DDMMYYYY)."
    )

    portal_password = cleaned["dob"].strftime("%d%m%Y")
    return {
        "success": True,
        "application_id": new_id,
        "application_no": app_no,
        "status": "PENDING",
        "applicant_name": cleaned["applicant_name"],
        "dob": cleaned["dob"].strftime("%d/%m/%Y"),
        "village": cleaned["village"],
        "block": cleaned["block"],
        "bank_account": cleaned["bank_account"],
        "ifsc": cleaned["ifsc"],
        "doc_path": cleaned["doc_path"],
        "status_portal_credentials": {
            "mobile": mobile,
            "password_hint": f"Date of Birth as DDMMYYYY ({portal_password})"
        },
        "statutory_sla_days": portal.SLA_DAYS,
        "message": f"Application {app_no} successfully submitted and registered in the Sewa Setu portal! It is now pending review under the {portal.SLA_DAYS}-day statutory SLA."
    }


@citizen_server.register_tool(
    name="get_application_status",
    description="Check status and details of an existing Old Age Pension application using mobile number or application number.",
    input_schema={
        "type": "object",
        "properties": {
            "mobile": {
                "type": "string",
                "description": "10-digit mobile number"
            },
            "application_no": {
                "type": "string",
                "description": "Application number (e.g. 'SSP26385548')"
            }
        },
        "required": []
    }
)
def get_application_status(args: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    mobile = (args.get("mobile") or "").strip()
    app_no = (args.get("application_no") or "").strip()

    if not mobile and not app_no:
        return {"success": False, "error": "Please provide either a mobile number or an application number."}

    conn = portal.get_db()
    cur = conn.cursor()

    if app_no:
        cur.execute(
            """SELECT id, application_no, applicant_name, mobile, dob, village, block,
                      bank_account, ifsc, status, submitted_at, decided_at, decided_by
               FROM applications WHERE application_no = %s LIMIT 1""",
            (app_no,)
        )
    else:
        cur.execute(
            """SELECT id, application_no, applicant_name, mobile, dob, village, block,
                      bank_account, ifsc, status, submitted_at, decided_at, decided_by
               FROM applications WHERE mobile = %s ORDER BY submitted_at DESC LIMIT 1""",
            (mobile,)
        )

    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return {"success": False, "found": False, "message": "No application found for given details."}

    app_id, application_no, name, mob, dob, village, blk, bank, ifsc, status, sub_at, dec_at, dec_by = row

    # Fetch audit log
    cur.execute("SELECT at, action, actor, note FROM audit_log WHERE application_id = %s ORDER BY at ASC", (app_id,))
    audit = [{"at": r[0].isoformat() if r[0] else None, "action": r[1], "actor": r[2], "note": r[3]} for r in cur.fetchall()]
    cur.close()
    conn.close()

    days_pending = None
    if sub_at:
        end_time = dec_at or portal.now_ist()
        days_pending = (end_time - sub_at).days

    return {
        "success": True,
        "found": True,
        "application_id": app_id,
        "application_no": application_no,
        "applicant_name": name,
        "mobile": mob,
        "dob": dob.strftime("%d/%m/%Y") if dob else None,
        "village": village,
        "block": blk,
        "bank_account": bank,
        "ifsc": ifsc,
        "status": status,
        "submitted_at": sub_at.strftime("%Y-%m-%d %H:%M:%S") if sub_at else None,
        "decided_at": dec_at.strftime("%Y-%m-%d %H:%M:%S") if dec_at else None,
        "decided_by": dec_by,
        "days_pending": days_pending,
        "can_withdraw": status == "PENDING",
        "audit_trail": audit
    }


@citizen_server.register_tool(
    name="withdraw_application",
    description="Withdraw a PENDING application so the applicant can submit a fresh application (e.g. to fix mistakes or update details).",
    input_schema={
        "type": "object",
        "properties": {
            "mobile": {
                "type": "string",
                "description": "10-digit mobile number of the applicant"
            },
            "application_id": {
                "type": "integer",
                "description": "ID of the application to withdraw (optional if mobile provided)"
            },
            "application_no": {
                "type": "string",
                "description": "Application number to withdraw (optional if mobile provided)"
            }
        },
        "required": ["mobile"]
    }
)
def withdraw_application(args: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    mobile = (args.get("mobile") or "").strip()
    app_id = args.get("application_id")
    app_no = args.get("application_no")

    conn = portal.get_db()
    cur = conn.cursor()

    if app_id:
        cur.execute("UPDATE applications SET status = 'WITHDRAWN', decided_at = %s, decided_by = 'APPLICANT' "
                    "WHERE id = %s AND mobile = %s AND status = 'PENDING' RETURNING id, application_no",
                    (portal.now_ist(), app_id, mobile))
    elif app_no:
        cur.execute("UPDATE applications SET status = 'WITHDRAWN', decided_at = %s, decided_by = 'APPLICANT' "
                    "WHERE application_no = %s AND mobile = %s AND status = 'PENDING' RETURNING id, application_no",
                    (portal.now_ist(), app_no, mobile))
    else:
        cur.execute("UPDATE applications SET status = 'WITHDRAWN', decided_at = %s, decided_by = 'APPLICANT' "
                    "WHERE mobile = %s AND status = 'PENDING' RETURNING id, application_no",
                    (portal.now_ist(), mobile))

    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return {
            "success": False,
            "error": "No pending application found to withdraw for the given criteria. Only PENDING applications can be withdrawn."
        }

    withdrawn_id, withdrawn_no = row
    portal.write_audit(cur, withdrawn_id, "WITHDRAW", f"applicant:{mobile}", "Withdrawn by applicant")
    conn.commit()
    cur.close()
    conn.close()

    return {
        "success": True,
        "application_id": withdrawn_id,
        "application_no": withdrawn_no,
        "status": "WITHDRAWN",
        "message": f"Application {withdrawn_no} has been withdrawn. You may now submit a fresh application."
    }
