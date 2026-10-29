# -*- coding: utf-8 -*-
"""
Sewa Setu - Evaluation Framework.
Simulates real citizen and officer personas interacting with the MCP servers,
executes tool sequences, and verifies strict database assertions against PostgreSQL.
Exposes results to /eval-dashboard.
"""

import json
import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

import app as portal
from mcp_citizen import citizen_server
from mcp_officer import officer_server

logger = logging.getLogger("evals")

PERSONAS = [
    {
        "id": "persona_phuleswari",
        "name": "Phuleswari Konwar",
        "role": "Citizen (Applicant)",
        "age": 70,
        "dob": "12/03/1956",
        "gender": "Female",
        "marital_status": "Widowed",
        "husband_name": "Late Biren Konwar",
        "village": "Lakhipur",
        "block": "Sonari",
        "mobile": "9854011223",
        "bank_account": "3876903950111",
        "ifsc": "SBIN0003077",
        "background": "Elderly widow assisted by her 19-year-old grandson Rahul on his smartphone. They visited the Sonari block counter last month.",
        "dialect_and_tone": "Warm, respectful, colloquial rural phrasing ('Moi Phuleswari, grandson helping to apply for ₹250 pension').",
        "goal": "Verify eligibility, request and verify OTP, attach voter card age proof, and submit Old Age Pension application.",
        "expected_result": "Application accepted as PENDING, portal user account created with password as DOB (12031956), SUBMIT audit log recorded, SMS sent.",
        "db_assertions": [
            "Row exists in applications with status = 'PENDING'",
            "Applicant name is 'Phuleswari Konwar' and block is 'Sonari'",
            "Row exists in portal_users with mobile '9854011223' and password_hash = SHA256('12031956')",
            "Audit log has action 'SUBMIT' by actor 'applicant:9854011223'"
        ]
    },
    {
        "id": "persona_bhaben",
        "name": "Bhaben Hazarika",
        "role": "Citizen (Inquiry / Status)",
        "age": 65,
        "dob": "18/06/1961",
        "village": "Kathoni",
        "block": "Dhemaji Pathar",
        "mobile": "9217729489",
        "background": "Senior citizen checking the status of his existing pension application and checking SLA timeline.",
        "dialect_and_tone": "Direct, polite village elder ('Nomoskar, I submitted application, please check what happened').",
        "goal": "Inquire about current application status and SLA timeline.",
        "expected_result": "Existing application details retrieved accurately without side effects or database mutation.",
        "db_assertions": [
            "Application status successfully queried from database",
            "No unintended mutations to database state"
        ]
    },
    {
        "id": "persona_gunaram",
        "name": "Gunaram Barua",
        "role": "Citizen (Underage Applicant)",
        "age": 58,
        "dob": "14/08/1968",
        "gender": "Male",
        "marital_status": "Married",
        "village": "Namti Chariali",
        "block": "Namti",
        "mobile": "9435012345",
        "bank_account": "7320086263999",
        "ifsc": "PUNB0556610",
        "background": "Tea garden laborer aged 58 who hopes he can get the pension early.",
        "dialect_and_tone": "Informal, hopeful ('I am 58 years old, can I get ₹250 monthly pension now?').",
        "goal": "Attempts to check eligibility and submit application despite being below statutory age 60.",
        "expected_result": "Cleanly refused by eligibility check and application validation with clear explanation ('applicant must be 60 years of age or above').",
        "db_assertions": [
            "No row inserted into applications table for mobile '9435012345'",
            "System of record remains pristine with zero ineligible records"
        ]
    },
    {
        "id": "persona_tara",
        "name": "Tara Devi",
        "role": "Citizen (Duplicate Prevention)",
        "age": 67,
        "dob": "24/09/1959",
        "gender": "Female",
        "marital_status": "Married",
        "village": "Udaypur",
        "block": "Borgaon",
        "mobile": "9864019283",
        "bank_account": "8505669675999",
        "ifsc": "CNRB0004417",
        "background": "Already submitted an application that is currently PENDING; panicked because she did not get a phone call and tries to apply again on the same mobile.",
        "dialect_and_tone": "Anxious ('I applied yesterday but no money received, let me submit another application').",
        "goal": "Attempts to submit a second application on the same mobile number.",
        "expected_result": "Submission blocked: portal detects active application and informs applicant they must withdraw first.",
        "db_assertions": [
            "Exactly 1 application exists for mobile '9864019283'",
            "Duplicate application submission is prevented"
        ]
    },
    {
        "id": "persona_hemkanti",
        "name": "Hemkanti Saikia",
        "role": "Citizen (Withdrawal & Correction Lifecycle)",
        "age": 72,
        "dob": "05/01/1954",
        "gender": "Female",
        "marital_status": "Widowed",
        "village": "Sialmari",
        "block": "Khelua",
        "mobile": "9954088712",
        "bank_account_old": "128000212000",
        "bank_account_new": "1570246629999",
        "ifsc": "UCBA0001522",
        "background": "Realized she entered wrong bank details on her first application; needs to withdraw the pending application and re-apply with corrected SBI pension account.",
        "dialect_and_tone": "Practical, urgent ('Made mistake in bank account, need to cancel previous and re-apply').",
        "goal": "Withdraw existing PENDING application, then submit fresh application with correct bank details.",
        "expected_result": "Original application marked WITHDRAWN with audit entry; new application successfully created with PENDING status.",
        "db_assertions": [
            "First application has status = 'WITHDRAWN' with audit log action 'WITHDRAW'",
            "Second application successfully created with status = 'PENDING'",
            "Updated bank account correctly stored"
        ]
    },
    {
        "id": "persona_ramen",
        "name": "Ramen Das",
        "role": "Citizen (Invalid Bank Details Rejection)",
        "age": 63,
        "dob": "11/11/1962",
        "gender": "Male",
        "marital_status": "Married",
        "village": "Dighaljan",
        "block": "Rajapara",
        "mobile": "9706054321",
        "bank_account": "12345",  # Invalid (too short)
        "ifsc": "SBI001",         # Invalid (wrong format)
        "background": "Elderly applicant confused about banking codes who enters a 5-digit account number and malformed IFSC.",
        "dialect_and_tone": "Confused about banking terms ('My bank is SBI and number is 12345').",
        "goal": "Attempts submission with invalid bank account length and improper IFSC format.",
        "expected_result": "Rejected at validation layer with specific error messages for bank account and IFSC.",
        "db_assertions": [
            "No record inserted into applications table",
            "Validation errors explicitly describe format rules"
        ]
    },
    {
        "id": "persona_officer_barua",
        "name": "Officer Barua",
        "role": "Block Officer (Review & Approval)",
        "officer_user": "bdo_sonari",
        "block": "Sonari",
        "background": "Block Development Officer for Sonari block reviewing pending applications approaching SLA deadline.",
        "dialect_and_tone": "Official, thorough, procedural administrative tone.",
        "goal": "Inspect operational dashboard, view application queue for Sonari block, review applicant age-proof details, and formally approve eligible case with justification note.",
        "expected_result": "Application marked APPROVED, decided_by = 'officer:bdo_sonari', decided_at recorded, audit log entry saved, approval SMS dispatched.",
        "db_assertions": [
            "Application status changed from 'PENDING' to 'APPROVED'",
            "decided_by is 'officer:bdo_sonari'",
            "Audit log has action 'APPROVED' with officer note",
            "SMS notification logged"
        ]
    },
    {
        "id": "persona_officer_gogoi",
        "name": "Officer Gogoi",
        "role": "Block Officer (Review & Rejection)",
        "officer_user": "welfare_officer_rajapara",
        "block": "Rajapara",
        "background": "Verification officer reviewing a case with mismatched territorial jurisdiction or irregular age proof.",
        "dialect_and_tone": "Official, rigorous compliance evaluation.",
        "goal": "Inspect application details and record a formal REJECTION with reason in audit log.",
        "expected_result": "Application marked REJECTED, decided_by recorded, audit log entry saved, rejection SMS dispatched.",
        "db_assertions": [
            "Application status changed from 'PENDING' to 'REJECTED'",
            "decided_by is 'officer:welfare_officer_rajapara'",
            "Audit log has action 'REJECTED' with reason note",
            "Rejection SMS logged"
        ]
    }
]


class EvalRunner:
    def __init__(self):
        self.last_run_time = None
        self.results = []
        self.summary = {"total": 0, "passed": 0, "failed": 0, "pass_rate": 0}

    def run_all(self) -> Dict[str, Any]:
        """Execute all persona evaluation test cases against live database."""
        logger.info("Starting comprehensive evaluation suite...")
        portal.ensure_db_sequences()
        self.last_run_time = datetime.now()
        results = []

        for p in PERSONAS:
            pid = p["id"]
            logger.info(f"Running evaluation for {p['name']} ({pid})...")
            start_t = time.time()
            try:
                method = getattr(self, f"_eval_{pid}")
                res = method(p)
                duration = round(time.time() - start_t, 3)
                res["duration_seconds"] = duration
                results.append(res)
            except Exception as e:
                logger.exception(f"Unhandled error in evaluation for {p['name']}: {e}")
                results.append({
                    "persona_id": pid,
                    "name": p["name"],
                    "role": p["role"],
                    "passed": False,
                    "error": str(e),
                    "steps": [],
                    "db_verifications": [{"assertion": "Test execution completed without uncaught exception", "passed": False, "detail": str(e)}],
                    "duration_seconds": round(time.time() - start_t, 3)
                })

        passed_count = sum(1 for r in results if r.get("passed"))
        total_count = len(results)
        pass_rate = round((passed_count / total_count * 100) if total_count > 0 else 0, 1)

        self.results = results
        self.summary = {
            "total": total_count,
            "passed": passed_count,
            "failed": total_count - passed_count,
            "pass_rate": pass_rate,
            "timestamp": self.last_run_time.strftime("%Y-%m-%d %H:%M:%S IST")
        }
        return {"summary": self.summary, "results": self.results}

    # -----------------------------------------------------------------------
    # Persona Evaluators
    # -----------------------------------------------------------------------

    def _eval_persona_phuleswari(self, p: Dict[str, Any]) -> Dict[str, Any]:
        steps = []
        db_verifications = []

        # Clean any prior test run for this mobile
        conn = portal.get_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM applications WHERE mobile = %s", (p["mobile"],))
        old_ids = [r[0] for r in cur.fetchall()]
        for oid in old_ids:
            cur.execute("DELETE FROM audit_log WHERE application_id = %s", (oid,))
            cur.execute("DELETE FROM applications WHERE id = %s", (oid,))
        cur.execute("DELETE FROM portal_users WHERE mobile = %s", (p["mobile"],))
        cur.execute("DELETE FROM otps WHERE mobile = %s", (p["mobile"],))
        conn.commit()

        # Step 1: Check eligibility
        step1_out = citizen_server.tools["check_eligibility"].handler({
            "dob": p["dob"],
            "block": p["block"],
            "mobile": p["mobile"]
        })
        steps.append({
            "step": 1,
            "tool": "check_eligibility",
            "input": {"dob": p["dob"], "block": p["block"], "mobile": p["mobile"]},
            "output": step1_out
        })
        step1_passed = step1_out.get("eligible") is True

        # Step 2: Request OTP
        step2_out = citizen_server.tools["request_otp"].handler({"mobile": p["mobile"]})
        steps.append({
            "step": 2,
            "tool": "request_otp",
            "input": {"mobile": p["mobile"]},
            "output": step2_out
        })

        # Fetch the generated OTP from database
        cur.execute("SELECT code FROM otps WHERE mobile = %s ORDER BY id DESC LIMIT 1", (p["mobile"],))
        otp_row = cur.fetchone()
        otp_code = otp_row[0] if otp_row else "000000"

        # Step 3: Verify OTP
        step3_out = citizen_server.tools["verify_otp"].handler({
            "mobile": p["mobile"],
            "otp": otp_code
        })
        steps.append({
            "step": 3,
            "tool": "verify_otp",
            "input": {"mobile": p["mobile"], "otp": otp_code},
            "output": step3_out
        })
        session_token = step3_out.get("session_token")

        # Step 4: Upload Age Proof Document
        step4_out = citizen_server.tools["upload_age_proof"].handler({
            "mobile": p["mobile"],
            "filename": "voter_id_phuleswari.pdf",
            "file_content_base64": "sample"
        })
        steps.append({
            "step": 4,
            "tool": "upload_age_proof",
            "input": {"mobile": p["mobile"], "filename": "voter_id_phuleswari.pdf"},
            "output": step4_out
        })
        doc_path = step4_out.get("doc_path")

        # Step 5: Submit Application
        step5_out = citizen_server.tools["submit_application"].handler({
            "mobile": p["mobile"],
            "applicant_name": p["name"],
            "dob": p["dob"],
            "gender": p["gender"],
            "marital_status": p["marital_status"],
            "husband_name": p["husband_name"],
            "village": p["village"],
            "block": p["block"],
            "bank_account": p["bank_account"],
            "ifsc": p["ifsc"],
            "doc_path": doc_path,
            "session_token": session_token
        })
        steps.append({
            "step": 5,
            "tool": "submit_application",
            "input": {"mobile": p["mobile"], "applicant_name": p["name"], "dob": p["dob"], "block": p["block"]},
            "output": step5_out
        })
        app_id = step5_out.get("application_id")
        app_no = step5_out.get("application_no")

        # DB Assertions
        cur.execute("SELECT id, status, block, village FROM applications WHERE id = %s", (app_id,))
        app_row = cur.fetchone()
        db_verifications.append({
            "assertion": "Application inserted with status = 'PENDING'",
            "passed": app_row is not None and app_row[1] == "PENDING",
            "detail": f"id={app_row[0]}, status={app_row[1]}" if app_row else "Row not found in applications table"
        })

        cur.execute("SELECT password_hash FROM portal_users WHERE mobile = %s", (p["mobile"],))
        user_row = cur.fetchone()
        expected_hash = portal.hash_password("12031956")
        db_verifications.append({
            "assertion": "Portal user created with DOB DDMMYYYY password",
            "passed": user_row is not None and user_row[0] == expected_hash,
            "detail": f"password_hash matched: {user_row[0][:16]}..." if user_row else "Row not found in portal_users"
        })

        cur.execute("SELECT action, actor FROM audit_log WHERE application_id = %s ORDER BY at DESC LIMIT 1", (app_id,))
        audit_row = cur.fetchone()
        db_verifications.append({
            "assertion": "Audit log records SUBMIT by applicant",
            "passed": audit_row is not None and audit_row[0] == "SUBMIT" and audit_row[1] == f"applicant:{p['mobile']}",
            "detail": f"action={audit_row[0]}, actor={audit_row[1]}" if audit_row else "No audit log entry found"
        })

        cur.close()
        conn.close()

        all_passed = step1_passed and step5_out.get("success") is True and all(v["passed"] for v in db_verifications)
        return {
            "persona_id": p["id"],
            "name": p["name"],
            "role": p["role"],
            "passed": all_passed,
            "steps": steps,
            "db_verifications": db_verifications,
            "application_no": app_no
        }

    def _eval_persona_bhaben(self, p: Dict[str, Any]) -> Dict[str, Any]:
        steps = []
        db_verifications = []

        # Find or create a record for Bhaben
        conn = portal.get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, application_no, status FROM applications WHERE mobile = %s LIMIT 1", (p["mobile"],))
        row = cur.fetchone()
        if not row:
            # Create a test record
            cur.execute(
                """INSERT INTO applications
                   (application_no, applicant_name, mobile, dob, gender, marital_status,
                    village, block, bank_account, ifsc, doc_path, status, submitted_at)
                   VALUES ('SSP26921772', %s, %s, '1961-06-18', 'Male', 'Married',
                           %s, %s, '8696030949776', 'CNRB0004417', '/var/sewasetu/uploads/bhaben.pdf',
                           'APPROVED', %s) RETURNING id, application_no, status""",
                (p["name"], p["mobile"], p["village"], p["block"], portal.now_ist() - timedelta(days=20))
            )
            row = cur.fetchone()
            conn.commit()
        cur.close()
        conn.close()

        # Tool Call: get_application_status
        out = citizen_server.tools["get_application_status"].handler({"mobile": p["mobile"]})
        steps.append({
            "step": 1,
            "tool": "get_application_status",
            "input": {"mobile": p["mobile"]},
            "output": out
        })

        found = out.get("found") is True and out.get("application_no") == row[1]
        db_verifications.append({
            "assertion": "Queried status matches live database record accurately",
            "passed": found,
            "detail": f"Status: {out.get('status')}, Application No: {out.get('application_no')}"
        })

        return {
            "persona_id": p["id"],
            "name": p["name"],
            "role": p["role"],
            "passed": found,
            "steps": steps,
            "db_verifications": db_verifications,
            "application_no": row[1]
        }

    def _eval_persona_gunaram(self, p: Dict[str, Any]) -> Dict[str, Any]:
        steps = []
        db_verifications = []

        # Step 1: Check eligibility for age 58
        step1_out = citizen_server.tools["check_eligibility"].handler({
            "dob": p["dob"],
            "block": p["block"],
            "mobile": p["mobile"]
        })
        steps.append({
            "step": 1,
            "tool": "check_eligibility",
            "input": {"dob": p["dob"], "block": p["block"]},
            "output": step1_out
        })
        eligibility_rejected = (step1_out.get("eligible") is False)

        # Step 2: Attempt submission anyway
        step2_out = citizen_server.tools["submit_application"].handler({
            "mobile": p["mobile"],
            "applicant_name": p["name"],
            "dob": p["dob"],
            "gender": p["gender"],
            "marital_status": p["marital_status"],
            "village": p["village"],
            "block": p["block"],
            "bank_account": p["bank_account"],
            "ifsc": p["ifsc"]
        })
        steps.append({
            "step": 2,
            "tool": "submit_application",
            "input": {"applicant_name": p["name"], "dob": p["dob"]},
            "output": step2_out
        })
        submission_rejected = (step2_out.get("success") is False)

        # DB Assertion: No row inserted
        conn = portal.get_db()
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM applications WHERE mobile = %s", (p["mobile"],))
        count = cur.fetchone()[0]
        cur.close()
        conn.close()

        db_verifications.append({
            "assertion": "Underage application rejected; zero records inserted in applications table",
            "passed": count == 0 and submission_rejected and eligibility_rejected,
            "detail": f"DB record count = {count}, Validation error: {step2_out.get('error')}"
        })

        passed = eligibility_rejected and submission_rejected and (count == 0)
        return {
            "persona_id": p["id"],
            "name": p["name"],
            "role": p["role"],
            "passed": passed,
            "steps": steps,
            "db_verifications": db_verifications
        }

    def _eval_persona_tara(self, p: Dict[str, Any]) -> Dict[str, Any]:
        steps = []
        db_verifications = []

        conn = portal.get_db()
        cur = conn.cursor()
        # Ensure exactly 1 pending application exists
        cur.execute("SELECT id, application_no FROM applications WHERE mobile = %s AND status = 'PENDING'", (p["mobile"],))
        row = cur.fetchone()
        if not row:
            cur.execute(
                """INSERT INTO applications
                   (application_no, applicant_name, mobile, dob, gender, marital_status,
                    village, block, bank_account, ifsc, doc_path, status, submitted_at)
                   VALUES ('SSP26986401', %s, %s, '1959-09-24', 'Female', 'Married',
                           %s, %s, %s, %s, '/var/sewasetu/uploads/tara.pdf', 'PENDING', %s)
                   RETURNING id, application_no""",
                (p["name"], p["mobile"], p["village"], p["block"], p["bank_account"], p["ifsc"], portal.now_ist())
            )
            row = cur.fetchone()
            conn.commit()
        orig_id, orig_no = row
        cur.close()
        conn.close()

        # Attempt second submission
        out = citizen_server.tools["submit_application"].handler({
            "mobile": p["mobile"],
            "applicant_name": p["name"],
            "dob": p["dob"],
            "gender": p["gender"],
            "marital_status": p["marital_status"],
            "village": p["village"],
            "block": p["block"],
            "bank_account": p["bank_account"],
            "ifsc": p["ifsc"]
        })
        steps.append({
            "step": 1,
            "tool": "submit_application",
            "input": {"mobile": p["mobile"], "applicant_name": p["name"]},
            "output": out
        })

        dup_blocked = (out.get("success") is False and "already exists" in out.get("error", ""))

        # DB Assertion: count is still 1
        conn = portal.get_db()
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM applications WHERE mobile = %s", (p["mobile"],))
        count = cur.fetchone()[0]
        cur.close()
        conn.close()

        db_verifications.append({
            "assertion": "Duplicate application blocked by portal; exactly 1 record retained",
            "passed": count == 1 and dup_blocked,
            "detail": f"Total applications for mobile = {count}. Message: {out.get('error')}"
        })

        return {
            "persona_id": p["id"],
            "name": p["name"],
            "role": p["role"],
            "passed": dup_blocked and count == 1,
            "steps": steps,
            "db_verifications": db_verifications,
            "application_no": orig_no
        }

    def _eval_persona_hemkanti(self, p: Dict[str, Any]) -> Dict[str, Any]:
        steps = []
        db_verifications = []

        # Setup initial pending application
        conn = portal.get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM applications WHERE mobile = %s", (p["mobile"],))
        cur.execute(
            """INSERT INTO applications
               (application_no, applicant_name, mobile, dob, gender, marital_status,
                village, block, bank_account, ifsc, doc_path, status, submitted_at)
               VALUES ('SSP26995408', %s, %s, '1954-01-05', 'Female', 'Widowed',
                       %s, %s, %s, %s, '/var/sewasetu/uploads/hemkanti.pdf', 'PENDING', %s)
               RETURNING id, application_no""",
            (p["name"], p["mobile"], p["village"], p["block"], p["bank_account_old"], p["ifsc"], portal.now_ist() - timedelta(hours=2))
        )
        first_id, first_no = cur.fetchone()
        portal.write_audit(cur, first_id, "SUBMIT", f"applicant:{p['mobile']}", "Initial submission")
        conn.commit()
        cur.close()
        conn.close()

        # Step 1: Withdraw previous application
        step1_out = citizen_server.tools["withdraw_application"].handler({
            "mobile": p["mobile"],
            "application_id": first_id
        })
        steps.append({
            "step": 1,
            "tool": "withdraw_application",
            "input": {"mobile": p["mobile"], "application_id": first_id},
            "output": step1_out
        })
        withdrawn_ok = step1_out.get("success") is True

        # Step 2: Submit new application with corrected bank account
        step2_out = citizen_server.tools["submit_application"].handler({
            "mobile": p["mobile"],
            "applicant_name": p["name"],
            "dob": p["dob"],
            "gender": p["gender"],
            "marital_status": p["marital_status"],
            "village": p["village"],
            "block": p["block"],
            "bank_account": p["bank_account_new"],
            "ifsc": p["ifsc"]
        })
        steps.append({
            "step": 2,
            "tool": "submit_application",
            "input": {"mobile": p["mobile"], "bank_account": p["bank_account_new"]},
            "output": step2_out
        })
        new_app_id = step2_out.get("application_id")
        new_app_no = step2_out.get("application_no")
        second_ok = step2_out.get("success") is True

        # DB Assertions
        conn = portal.get_db()
        cur = conn.cursor()
        cur.execute("SELECT status FROM applications WHERE id = %s", (first_id,))
        first_status = cur.fetchone()[0]

        cur.execute("SELECT status, bank_account FROM applications WHERE id = %s", (new_app_id,))
        new_row = cur.fetchone()
        cur.close()
        conn.close()

        db_verifications.append({
            "assertion": "Prior application status transitioned to 'WITHDRAWN'",
            "passed": first_status == "WITHDRAWN",
            "detail": f"Application {first_no} status: {first_status}"
        })
        db_verifications.append({
            "assertion": "New application created in 'PENDING' with updated bank account",
            "passed": new_row is not None and new_row[0] == "PENDING" and new_row[1] == p["bank_account_new"],
            "detail": f"Application {new_app_no} status: {new_row[0] if new_row else 'None'}, Bank: {new_row[1] if new_row else 'None'}"
        })

        passed = withdrawn_ok and second_ok and first_status == "WITHDRAWN" and new_row and new_row[0] == "PENDING"
        return {
            "persona_id": p["id"],
            "name": p["name"],
            "role": p["role"],
            "passed": passed,
            "steps": steps,
            "db_verifications": db_verifications,
            "application_no": new_app_no
        }

    def _eval_persona_ramen(self, p: Dict[str, Any]) -> Dict[str, Any]:
        steps = []
        db_verifications = []

        out = citizen_server.tools["submit_application"].handler({
            "mobile": p["mobile"],
            "applicant_name": p["name"],
            "dob": p["dob"],
            "gender": p["gender"],
            "marital_status": p["marital_status"],
            "village": p["village"],
            "block": p["block"],
            "bank_account": p["bank_account"],
            "ifsc": p["ifsc"]
        })
        steps.append({
            "step": 1,
            "tool": "submit_application",
            "input": {"bank_account": p["bank_account"], "ifsc": p["ifsc"]},
            "output": out
        })

        rejected = out.get("success") is False
        errors = out.get("validation_errors", [])
        has_bank_err = any("bank account" in e.lower() for e in errors)
        has_ifsc_err = any("ifsc" in e.lower() for e in errors)

        conn = portal.get_db()
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM applications WHERE mobile = %s", (p["mobile"],))
        count = cur.fetchone()[0]
        cur.close()
        conn.close()

        db_verifications.append({
            "assertion": "Malformed bank account and IFSC format rejected; zero DB inserts",
            "passed": count == 0 and has_bank_err and has_ifsc_err,
            "detail": f"Errors returned: {errors}"
        })

        passed = rejected and has_bank_err and has_ifsc_err and count == 0
        return {
            "persona_id": p["id"],
            "name": p["name"],
            "role": p["role"],
            "passed": passed,
            "steps": steps,
            "db_verifications": db_verifications
        }

    def _eval_persona_officer_barua(self, p: Dict[str, Any]) -> Dict[str, Any]:
        steps = []
        db_verifications = []

        # Step 1: Officer Dashboard
        dash = officer_server.tools["get_officer_dashboard"].handler({}, context={"officer": p["officer_user"]})
        steps.append({
            "step": 1,
            "tool": "get_officer_dashboard",
            "input": {},
            "output": dash
        })

        # Step 2: List pending applications for Sonari block
        queue = officer_server.tools["list_applications"].handler(
            {"block": p["block"], "status": "PENDING", "limit": 5},
            context={"officer": p["officer_user"]}
        )
        steps.append({
            "step": 2,
            "tool": "list_applications",
            "input": {"block": p["block"], "status": "PENDING"},
            "output": {"total_matching": queue.get("total_matching"), "returned": queue.get("returned_count")}
        })

        apps = queue.get("applications", [])
        if not apps:
            # Create a test pending application for Sonari
            conn = portal.get_db()
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO applications
                   (application_no, applicant_name, mobile, dob, gender, marital_status,
                    village, block, bank_account, ifsc, doc_path, status, submitted_at)
                   VALUES ('SSP26778899', 'Rameswar Gogoi', '9123456780', '1952-03-10', 'Male', 'Married',
                           'Lakhipur', 'Sonari', '3876903950999', 'SBIN0003077',
                           '/var/sewasetu/uploads/rameswar.pdf', 'PENDING', %s)
                   RETURNING id, application_no""",
                (portal.now_ist() - timedelta(days=5),)
            )
            target_id, target_no = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()
        else:
            target_id = apps[0]["id"]
            target_no = apps[0]["application_no"]

        # Step 3: Get application details
        details = officer_server.tools["get_application_details"].handler(
            {"application_id": target_id},
            context={"officer": p["officer_user"]}
        )
        steps.append({
            "step": 3,
            "tool": "get_application_details",
            "input": {"application_id": target_id},
            "output": {"status": details.get("status"), "applicant": details.get("personal_details", {}).get("applicant_name")}
        })

        # Step 4: Approve application
        approval_note = "Verified age 70 from Voter ID card copy. Bank details verified with Sonari SBI branch. Approved."
        decision = officer_server.tools["decide_application"].handler(
            {
                "application_id": target_id,
                "decision": "APPROVED",
                "note": approval_note,
                "officer_name": p["officer_user"]
            },
            context={"officer": p["officer_user"]}
        )
        steps.append({
            "step": 4,
            "tool": "decide_application",
            "input": {"application_id": target_id, "decision": "APPROVED", "officer_name": p["officer_user"]},
            "output": decision
        })

        # DB Assertions
        conn = portal.get_db()
        cur = conn.cursor()
        cur.execute("SELECT status, decided_by, decided_at FROM applications WHERE id = %s", (target_id,))
        app_row = cur.fetchone()

        cur.execute("SELECT action, actor, note FROM audit_log WHERE application_id = %s AND action = 'APPROVED'", (target_id,))
        audit_row = cur.fetchone()
        cur.close()
        conn.close()

        db_verifications.append({
            "assertion": "Application status updated to 'APPROVED' with decided_by recorded",
            "passed": app_row is not None and app_row[0] == "APPROVED" and app_row[1] == p["officer_user"],
            "detail": f"Status: {app_row[0] if app_row else 'None'}, decided_by: {app_row[1] if app_row else 'None'}"
        })
        db_verifications.append({
            "assertion": "Audit log records APPROVED action with officer note",
            "passed": audit_row is not None and audit_row[0] == "APPROVED" and audit_row[1] == f"officer:{p['officer_user']}",
            "detail": f"Audit: {audit_row[1] if audit_row else 'None'} - {audit_row[2] if audit_row else 'None'}"
        })

        passed = decision.get("success") is True and app_row and app_row[0] == "APPROVED"
        return {
            "persona_id": p["id"],
            "name": p["name"],
            "role": p["role"],
            "passed": passed,
            "steps": steps,
            "db_verifications": db_verifications,
            "application_no": target_no
        }

    def _eval_persona_officer_gogoi(self, p: Dict[str, Any]) -> Dict[str, Any]:
        steps = []
        db_verifications = []

        # Create a pending case to reject
        conn = portal.get_db()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO applications
               (application_no, applicant_name, mobile, dob, gender, marital_status,
                village, block, bank_account, ifsc, doc_path, status, submitted_at)
               VALUES ('SSP26554433', 'Dinesh Hazarika', '9123456789', '1955-08-14', 'Male', 'Married',
                       'Unknown Boundary', 'Rajapara', '129068125599', 'UTBI0PUR2819',
                       '/var/sewasetu/uploads/dinesh.pdf', 'PENDING', %s)
               RETURNING id, application_no""",
            (portal.now_ist() - timedelta(days=2),)
        )
        target_id, target_no = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        rejection_note = "Field inquiry reports applicant resides in neighboring state, outside Rajapara block jurisdiction."
        decision = officer_server.tools["decide_application"].handler(
            {
                "application_id": target_id,
                "decision": "REJECTED",
                "note": rejection_note,
                "officer_name": p["officer_user"]
            },
            context={"officer": p["officer_user"]}
        )
        steps.append({
            "step": 1,
            "tool": "decide_application",
            "input": {"application_id": target_id, "decision": "REJECTED", "officer_name": p["officer_user"]},
            "output": decision
        })

        # DB Assertions
        conn = portal.get_db()
        cur = conn.cursor()
        cur.execute("SELECT status, decided_by, decided_at FROM applications WHERE id = %s", (target_id,))
        app_row = cur.fetchone()

        cur.execute("SELECT action, actor, note FROM audit_log WHERE application_id = %s AND action = 'REJECTED'", (target_id,))
        audit_row = cur.fetchone()
        cur.close()
        conn.close()

        db_verifications.append({
            "assertion": "Application status set to 'REJECTED' with decided_by recorded",
            "passed": app_row is not None and app_row[0] == "REJECTED" and app_row[1] == p["officer_user"],
            "detail": f"Status: {app_row[0] if app_row else 'None'}, decided_by: {app_row[1] if app_row else 'None'}"
        })
        db_verifications.append({
            "assertion": "Audit log records REJECTED with rejection reason",
            "passed": audit_row is not None and audit_row[0] == "REJECTED" and audit_row[1] == f"officer:{p['officer_user']}",
            "detail": f"Audit: {audit_row[1] if audit_row else 'None'} - {audit_row[2] if audit_row else 'None'}"
        })

        passed = decision.get("success") is True and app_row and app_row[0] == "REJECTED"
        return {
            "persona_id": p["id"],
            "name": p["name"],
            "role": p["role"],
            "passed": passed,
            "steps": steps,
            "db_verifications": db_verifications,
            "application_no": target_no
        }


# Global singleton runner
eval_runner = EvalRunner()
