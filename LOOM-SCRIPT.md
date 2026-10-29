# Sewa Setu: Agent-Ready Transformation
## 3-Minute Loom Video Presentation Script

**Speaker:** Build for Bharat Fellow (AI Track)  
**Audience:** Director, Department of Social Welfare, Government of Purvanchal  
**Target Duration:** Exactly 3 minutes (180 seconds)  
**Setup:** Picture-in-picture (Face camera in corner, Screen sharing browser and terminal)  

---

### [0:00 – 0:30] Introduction & The Mission Accomplished
**Visual:** Face on camera; screen shows the Sewa Setu portal home page at `http://localhost:8000` with the new navigation bar.

> *"Hello Director. When you described that 70-year-old grandmother who came to Sonari block counter because an AI assistant gave outdated information and couldn't apply for her pension, the mission became crystal clear: bring Sewa Setu into the agentic era without compromising the portal as our single system of record.*
>
> *Today, I am proud to report that Sewa Setu is fully agent-ready. Any AI assistant—whether running on a grandson’s phone or an officer’s laptop—can now securely check eligibility, submit verified applications, and review cases under our statutory 15-day SLA."*

---

### [0:30 – 1:15] Architecture & The Two Isolated MCP Servers
**Visual:** Switch screen to split view showing `/mcp` gateway overview and the two live endpoints: `/mcp/citizen` and `/mcp/officer`.

> *"To make this possible, we built two separate Model Context Protocol (MCP) servers over streamable HTTP.*
>
> *First, the **Citizen MCP** at `/mcp/citizen`. A citizen's assistant only sees what a citizen needs: checking eligibility, requesting and verifying mobile OTPs, uploading age proof, submitting applications, checking status, and withdrawing if needed. Crucially, a citizen assistant cannot even see officer tools. No prompt injection can trick it into approving a pension.*
>
> *Second, the **Block Officer MCP** at `/mcp/officer`, protected by OAuth 2.1 tokens. It gives block officers tools to monitor overdue applications exceeding our 15-day SLA, filter pending queues by block like Sonari or Rajapara, inspect voter ID documents, and record formal approvals or rejections with immutable audit notes.*
>
> *Both servers talk directly to our Postgres database using the exact same validation logic as the web portal. The portal remains the sole system of record."*

---

### [1:15 – 2:15] Personas, Evals & The Live Dashboard
**Visual:** Switch screen to `http://localhost:8000/eval-dashboard`. Show the 8 personas, the 100% pass rate badge, and expand a tool call transcript.

> *"We didn’t just build tools; we tested them against real humans. On our `/eval-dashboard`, we created eight specific personas reflecting Purvanchal's reality.*
>
> *Meet **Phuleswari Konwar**, age 70, from Lakhipur village in Sonari, applying with her grandson Rahul. Her conversation requests an OTP, verifies it, uploads her voter card, and creates a PENDING application while setting up her status portal account with her date of birth.*
>
> *We tested **Gunaram Barua**, a tea laborer aged 58. The assistant catches his age before any database insert, explaining he must be 60.*
>
> *We tested **Tara Devi**, who panicked and tried applying twice; the assistant safely stopped the duplicate.*
>
> *We tested **Hemkanti Saikia**, who entered the wrong bank account, withdrew her pending application, and successfully re-applied.*
>
> *And we tested **Officer Barua**, who reviewed Sonari's pending queue and approved Phuleswari's case with an audit trail note.*
>
> *Every single test asserts direct database truth in PostgreSQL: checking rows, password hashes, and audit logs. All eight pass with zero regressions."*

---

### [2:15 – 2:45] Key Learnings & What We'd Do With More Time
**Visual:** Click 'Run Evaluations Live' button on the dashboard to show instant test execution and DB assertion checks turning green.

> *"What did we learn? First, pre-screening before authentication saves enormous citizen frustration. Second, small models perform dramatically better when tool definitions are concise and strictly isolated.*
>
> *If given another week, the one thing I would build differently is a **voice-first multimodal bridge**. Senior citizens in remote villages shouldn't have to type. An IVR or WhatsApp voice-note pipeline with regional Assamese and Bengali acoustic models would allow elders to simply speak, with the assistant driving the same MCP tools under the hood."*

---

### [2:45 – 3:00] Conclusion & Delivery
**Visual:** Face on camera; screen shows the submission checklist: GitHub repo, MCP endpoints, officer credentials.

> *"Sewa Setu is now live, verified, and running on open standards. The code is pushed to `sewasetu-assistant`, the eval dashboard is active, and the department is ready for the future of public service. Thank you."*
