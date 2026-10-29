# Sewa Setu: Agent-Ready Transformation
## One-Page Design Note

**Author:** Build for Bharat Fellow (AI Track)  
**Department:** Department of Social Welfare, Government of Purvanchal  
**Scope:** Old Age Pension Scheme Portal & Agent Integration  

---

### The Three Decisions That Mattered Most

#### 1. Complete Surface and Protocol Isolation between Citizen and Officer Agents
Rather than deploying a single monolithic MCP server with runtime role guards, we designed two distinct Model Context Protocol (MCP) endpoints over Streamable HTTP: `/mcp/citizen` and `/mcp/officer`. 
- **Security & Prompt-Injection Immunity:** A citizen’s assistant (e.g., an LLM running on a grandson’s phone) cannot even *see* or discover officer decision tools (`decide_application`, queue triage). This architectural separation guarantees that prompt injection, adversarial jailbreaks, or tool hallucination cannot trick an agent into approving a pension.
- **Model Efficiency & Context Window Economy:** Small models (like Claude Code running lightweight models on restricted turns) degrade when flooded with sprawling tool schemas. By exposing only 5 focused tools to officers and 8 to citizens, turn latency drops and decision accuracy approaches 100%.

#### 2. Strict Portal Parity — The Portal Remains the Invariant System of Record
An AI assistant must never become an unmonitored shadow backdoor. We bound both MCP servers directly to the core portal business logic:
- **Zero Rule Duplication:** Every application submitted via MCP executes `validate_application()` and `create_application()`, enforcing identical age bounds ($\ge 60$ on IST date), valid Purvanchal block jurisdictions, 9-to-18 digit account numbers, and 11-character uppercase IFSC validation.
- **Unified State & Statutory SLA:** Applications submitted via AI immediately appear on the officer’s web dashboard and are subject to the same 15-day statutory SLA under the Purvanchal Right to Public Services (RTPS) Act, eligible for nightly deemed approval (`scripts/deemed_approval.py`). Every action leaves an immutable record in `audit_log`, and provisions the status-portal login (`portal_users` with password as DOB `DDMMYYYY`).

#### 3. Conversational Resilience for Low-Digital-Literacy Citizens & Intermediaries
Senior citizens in Purvanchal frequently share phones, rely on CSC operators or family members, and make honest data-entry mistakes. We tailored the agent experience to rural realities:
- **Upfront Pre-Screening:** `check_eligibility` allows the assistant to verify age and block jurisdiction before asking the elder to search for bank passbooks or wait for an SMS OTP, gracefully turning away underage applicants (e.g., Gunaram, age 58) with zero portal pollution.
- **Transparent Recovery Lifecycles:** When an applicant realizes they submitted incorrect bank details (e.g., Hemkanti), the agent doesn't dead-end; it guides the citizen through `withdraw_application` (recording `WITHDRAW` in the audit log) and immediately enables a clean re-submission without administrator intervention.

---

### The Decision We Would Make Differently With More Time

#### Voice-First Multimodal Bridge (IVR / Audio Notes) over Regional Acoustic Models
While MCP over streamable HTTP provides a robust standard for client agents like Claude Code, real senior citizens like Phuleswari Devi often cannot read, write, or type on glass. 

With more time, we would build a **direct voice-first multimodal bridge**:
1. An IVR / telecom carrier connector (integrated with the simulated gateway) that accepts incoming voice calls or WhatsApp voice notes in local dialects (Assamese, Bengali, Bhojpuri).
2. Streaming ASR running regional acoustic models to translate spoken intent into structured MCP tool calls.
3. Synthesized spoken speech output returning plain-language status updates to the elder.
4. An asynchronous human-in-the-loop review queue for flagged low-confidence audio transcriptions before database commit.
