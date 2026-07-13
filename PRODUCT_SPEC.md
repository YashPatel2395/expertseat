# ExpertSeat — Product Specification

**Version**: 0.2 (Expanded)
**Status**: Active — updated 2026-07-13
**Date**: 2026-07-13

---

## 1. Mission

ExpertSeat enables recruiting teams to add AI domain experts to interview panels when no qualified human panelist is available. Every AI panelist is disclosed to candidates, operates within recruiter-defined constraints, and produces evidence-backed output for human review. AI is always disclosed. Recruiters control everything. Humans make all final hiring decisions.

---

## 2. Problem Statement

Hiring teams frequently lack internal domain expertise for evaluating specialist roles:
- A startup hiring its first ML engineer has no ML engineers to conduct technical interviews
- A team hiring a staff security engineer has nobody qualified to probe security depth
- Distributed teams can't always schedule synchronous expert interviews across time zones

Current workarounds — hiring external consultants, skipping domain panels, or relying on job boards — are expensive, slow, or result in poor signal.

ExpertSeat provides AI panelists that can fill these gaps while keeping human reviewers in the decision loop.

---

## 3. Core Concepts

### 3.1 Blueprint

A **Blueprint** is a structured specification for an AI Role Agent. It defines:
- Domain and role context (e.g., "Staff Backend Engineer — distributed systems focus")
- Question bank and evaluation criteria sourced from the recruiter
- Behavioral constraints (tone, depth, follow-up limits)
- Evidence sources the agent is allowed to reference
- Scoring rubrics for each evaluation dimension

Blueprints are created and owned by organizations. They are versioned. See Section 12 for the complete Blueprint schema.

### 3.2 Role Agent

A **Role Agent** is an instantiation of a Blueprint for a specific interview. It:
- Operates within the constraints defined by its Blueprint
- Asks questions in sequence or adaptively based on candidate responses
- References only permitted evidence sources
- Does not make hiring recommendations — it produces scored observations

A Role Agent is not a general-purpose AI assistant. Its scope is strictly limited to the interview context. Recruiters can mute, unmute, deactivate, or take over from the agent at any time.

### 3.3 Custom vs. Verified Blueprints

**Custom Blueprints** are created by the recruiter's organization. They are unaudited and may reflect the organization's own biases or gaps. Organizations bear responsibility for their content. Custom Blueprints must never be labeled or presented as independently validated.

**Verified Domain Blueprints** (planned, post-pilot) require a substantially higher standard:
- Reviewed by qualified domain experts in the relevant profession
- Validated competencies mapped to actual job requirements
- Questions and scenarios independently reviewed for relevance and fairness
- Rubrics and answer indicators tested against known-good human assessments
- Measured agreement between AI evaluations and qualified human evaluator scores
- Re-validated when major domain changes occur

A structural checklist alone does not constitute Verification. Verified status means ExpertSeat has completed the above steps for that domain and is prepared to defend the rubric. Verified Blueprints cover only the specific domain reviewed — a Verified Blueprint for one profession says nothing about another.

Verified Blueprints are architecturally possible from the start (the schema supports the `verified_status` flag), but no domain will be marked Verified until the full review process has been completed.

### 3.4 Evidence

Every Role Agent question and scoring observation must be grounded in **evidence**:
- The job description provided at blueprint creation
- Domain reference material explicitly uploaded by the recruiter
- The candidate's own submission (resume, portfolio, code samples)
- The candidate's responses during the interview

Role Agents may not introduce factual claims that cannot be traced to one of the above sources.

---

## 4. User Roles

ExpertSeat has three actor types in the MVP:

| Role | Description | Can Do |
|---|---|---|
| **Recruiter** | Primary platform user within an org | Create blueprints, schedule interviews, run control room, review reports |
| **Hiring Manager** | Optional reviewer within the same org | View reports, accept/reject/flag observations, cannot modify blueprints |
| **Candidate** | External interview participant | Receive disclosure, complete consent, participate in interview |

In the MVP, candidates do not have platform accounts. They interact via a consent link only.

All recruiters within an org have equal permissions in the MVP. Role-based access control within orgs is a post-pilot feature.

---

## 5. Interview Lifecycle

An interview moves through the following lifecycle phases:

1. **Blueprint Selected** — Recruiter selects or creates a Blueprint for the role.
2. **Interview Scheduled** — Interview is created and pinned to a specific Blueprint version.
3. **Consent Sent** — Candidate receives disclosure email with consent link.
4. **Consent Completed** — Candidate acknowledges AI participation and provides consent. The interview cannot proceed without this.
5. **Interview Active** — Interview begins. Role Agent joins (browser simulator M4 or Zoom M7). Recruiter activates the agent from the control room.
6. **Interview In Progress** — Agent asks questions, captures responses, generates observations. Recruiter monitors and can intervene at any time.
7. **Interview Completed** — Interview concludes. Agent produces draft report.
8. **Report Under Review** — Recruiter and/or hiring manager review observations. Each observation is accepted, modified, or rejected.
9. **Report Finalized** — All observations reviewed. Report is available for comparison and export. Hiring decision is made by a human outside the platform.
10. **Archived** — Interview and report retained per org retention policy, then deleted.

See Section 14 for the interview state machine.

---

## 6. Consent Workflow

ExpertSeat requires explicit candidate consent before any AI agent participates in an interview. The consent workflow must:

1. **Deliver disclosure** via email link containing:
   - The name and role of the position being interviewed for
   - An explicit statement that an AI system will participate as a panelist
   - The name of the system (ExpertSeat Role Agent)
   - What the agent will do: ask questions, observe responses, produce a report for human review
   - What the agent will not do: make hiring decisions, access data outside the interview
   - A clear mechanism to decline without penalty
2. **Capture consent** — candidate must click an explicit consent button (not implied by joining the meeting)
3. **Record consent** — the system stores: candidate identifier, timestamp (UTC), disclosure version shown, IP address (for audit purposes)
4. **Gate the interview** — the interview session cannot be created and the agent cannot be activated without a confirmed consent record
5. **Handle withdrawal** — if a candidate withdraws consent mid-interview, the agent is immediately deactivated and the recruiter is notified

Consent records are immutable once created. Withdrawal creates a separate withdrawal record; it does not delete the original consent.

---

## 7. Scoring System

### 7.1 Scoring Principles

- **"No evidence, no score"** — A score cannot be assigned to an evaluation dimension unless at least one evidence citation is attached. This is a hard system rule, not a guideline.
- **"Insufficient evidence"** — When the agent cannot gather enough evidence to score a dimension (candidate did not answer, question was skipped, STT failed), the dimension is flagged as **Insufficient evidence** rather than scored 0 or left blank.
- Scores are **observations**, not verdicts. They represent the agent's evidence-grounded assessment of a specific dimension in a specific interview, not a definitive judgment of the candidate.
- Human reviewers may override any score. Overrides are recorded in the audit log with the reviewer's ID and rationale.

### 7.2 Score Scale

Scores are integers from 1 to 5 per dimension:

| Score | Label | Meaning |
|---|---|---|
| 1 | Significantly below expectations | Strong negative evidence relative to the rubric |
| 2 | Below expectations | Some gaps relative to the rubric |
| 3 | Meets expectations | Evidence matches the rubric criteria |
| 4 | Above expectations | Stronger evidence than minimum rubric criteria |
| 5 | Significantly above expectations | Exceptional evidence well beyond rubric criteria |

An unscored dimension carries either "Insufficient evidence" or is left unscored if the question was not reached.

### 7.3 Aggregate Score

No aggregate or composite score is displayed by default. Recruiter can enable a weighted average across dimensions, but the weight configuration must be explicit and is part of the Blueprint. The UI labels any aggregate clearly as a "weighted average of observations" not a candidate score.

---

## 8. Evidence Requirements

Every observation produced by a Role Agent must include at least one evidence citation. Evidence citations reference one of:

- `jd_section` — a specific section of the uploaded job description
- `blueprint_ref` — a specific question or rubric element in the blueprint
- `resume_section` — a specific section of the candidate's resume
- `reference_doc_section` — a specific passage in uploaded domain reference material
- `transcript_segment` — a time-stamped segment of the interview transcript

Evidence citations include: source type, source identifier, excerpt text (up to 500 characters), and the relevance explanation (why this evidence supports the observation).

If an agent generates an observation without any evidence citation, the system rejects it at the output validation layer and substitutes an "Insufficient evidence" flag. This cannot be disabled by blueprint configuration.

---

## 9. Recruiter Commands

The recruiter has exactly 12 control actions available from the Recruiter Control Room during an active interview:

| # | Command | Description |
|---|---|---|
| 1 | **Activate agent** | Brings the agent from standby into the live interview; agent begins with its opening greeting |
| 2 | **Deactivate agent** | Immediately silences and removes the agent from active participation; interview may continue with human panelists |
| 3 | **Mute agent** | Prevents the agent from speaking; agent continues listening and generating internal observations |
| 4 | **Unmute agent** | Re-enables agent speech output after a mute |
| 5 | **Take over** | Temporarily suspends the agent's question flow; recruiter takes the floor; agent resumes on command |
| 6 | **Ask agent to repeat** | Agent repeats its most recent question or statement verbatim |
| 7 | **Skip question** | Advances the agent past the current question to the next in sequence; skipped question is marked as not asked in the report |
| 8 | **Flag observation** | Marks a draft observation for mandatory human review; flagged observations cannot be auto-accepted |
| 9 | **Approve observation** | Accepts a draft observation into the final report as written |
| 10 | **Reject observation** | Removes a draft observation from the final report; rejection is logged with the reviewer ID |
| 11 | **Request summary** | Agent produces a mid-interview summary of observations generated so far (does not end the interview) |
| 12 | **End interview** | Formally ends the interview session; agent completes any open observations and submits the draft report |

Commands 1–7 are available during an active interview session. Commands 8–10 are available in the report review phase. Commands 11–12 are available during the active interview.

---

## 10. Blueprint Schema

A Blueprint has the following fields. All fields are stored on the `blueprints` and `blueprint_versions` tables.

### 10.1 Identity and Versioning

| # | Field | Type | Description |
|---|---|---|---|
| 1 | `id` | UUID | Immutable blueprint identifier |
| 2 | `org_id` | UUID | Owning organization (immutable) |
| 3 | `name` | string (255) | Human-readable blueprint name |
| 4 | `version_number` | integer | Auto-incrementing version; versions are immutable once activated |
| 5 | `version_label` | string (100) | Optional human label (e.g., "v1.2 — updated rubrics") |
| 6 | `created_at` | timestamp (UTC) | When this version was created |
| 7 | `created_by` | UUID (user) | Recruiter who created/activated this version |
| 8 | `activated_at` | timestamp (UTC) | When this version was first used in a live interview; null if never used |
| 9 | `is_active` | boolean | Whether this is the current active version for new interviews |
| 10 | `verified_status` | enum: `custom`, `verified` | Whether this blueprint has passed ExpertSeat's verification process |
| 11 | `verified_at` | timestamp (UTC) | When verified status was granted; null for custom |

### 10.2 Role Context

| # | Field | Type | Description |
|---|---|---|---|
| 12 | `domain` | string (255) | Professional domain (e.g., "Backend Engineering", "Security Engineering") |
| 13 | `role_title` | string (255) | Specific role (e.g., "Staff Backend Engineer") |
| 14 | `role_level` | enum: `junior`, `mid`, `senior`, `staff`, `principal`, `lead`, `manager` | Seniority level |
| 15 | `role_context_narrative` | text | Free-text description of role responsibilities, team context, and what the interview should assess |
| 16 | `interview_language` | string (5) | BCP-47 language tag (e.g., "en-US"); determines STT/TTS language |

### 10.3 Evaluation Dimensions

| # | Field | Type | Description |
|---|---|---|---|
| 17 | `dimensions` | array of DimensionConfig | Ordered list of evaluation dimensions |
| 18 | `DimensionConfig.id` | string | Unique within blueprint (e.g., "dim_system_design") |
| 19 | `DimensionConfig.name` | string | Human-readable dimension name |
| 20 | `DimensionConfig.weight` | float (0–1) | Weight for aggregate score; all weights must sum to 1.0 if aggregate score is enabled |
| 21 | `DimensionConfig.description` | text | What this dimension measures |
| 22 | `DimensionConfig.rubric` | object (score_1 through score_5) | Rubric descriptors for each score level; used by agent for scoring rationale |

### 10.4 Question Bank

| # | Field | Type | Description |
|---|---|---|---|
| 23 | `questions` | array of QuestionConfig | Ordered list of interview questions |
| 24 | `QuestionConfig.id` | string | Unique within blueprint |
| 25 | `QuestionConfig.question_text` | text | The question text the agent will ask |
| 26 | `QuestionConfig.dimension_id` | string | Which dimension this question is designed to assess |
| 27 | `QuestionConfig.is_required` | boolean | Whether this question must be asked; non-required questions may be skipped if time runs short |
| 28 | `QuestionConfig.expected_duration_minutes` | integer | Estimated time for this question and its follow-ups |
| 29 | `QuestionConfig.follow_up_limit` | integer | Max number of follow-up questions the agent may ask before moving on |
| 30 | `QuestionConfig.follow_up_guidance` | text | Optional guidance to agent on what to probe in follow-ups |
| 31 | `QuestionConfig.answer_indicators` | array of string | Optional list of content indicators a strong answer should include (not revealed to candidate) |

### 10.5 Behavioral Constraints

| # | Field | Type | Description |
|---|---|---|---|
| 32 | `agent_tone` | enum: `professional`, `conversational`, `technical` | Overall tone for agent interactions |
| 33 | `max_total_follow_ups` | integer | Global cap on follow-up questions across the entire interview |
| 34 | `time_limit_minutes` | integer | Maximum interview duration; agent wraps up gracefully at the limit |
| 35 | `allow_adaptive_questions` | boolean | Whether agent may generate new questions not in the question bank based on candidate responses |
| 36 | `adaptive_question_dimension_scope` | array of dimension IDs | If adaptive questions enabled, which dimensions the agent may generate adaptive questions for |

### 10.6 Evidence Sources

| # | Field | Type | Description |
|---|---|---|---|
| 37 | `evidence_sources` | array of EvidenceSourceConfig | Which evidence sources are permitted for this blueprint |
| 38 | `EvidenceSourceConfig.source_type` | enum: `job_description`, `resume`, `reference_doc`, `transcript` | Source type |
| 39 | `EvidenceSourceConfig.required` | boolean | Whether this source must be provided before the interview can be activated |

### 10.7 Output Configuration

| # | Field | Type | Description |
|---|---|---|---|
| 40 | `show_aggregate_score` | boolean | Whether to display a weighted aggregate score in the report |
| 41 | `report_include_transcript` | boolean | Whether the full transcript is appended to the report |
| 42 | `report_include_follow_up_log` | boolean | Whether follow-up question log is included in the report |
| 43 | `observation_format` | enum: `structured`, `narrative` | Whether observations are output as structured fields or narrative paragraphs |

---

## 11. Observation Schema

Every scored observation produced by a Role Agent has exactly the following 11 fields:

| # | Field | Type | Description |
|---|---|---|---|
| 1 | `question_text` | text | The exact question that was asked (as delivered, including any rephrasing) |
| 2 | `candidate_response` | text | Verbatim or lightly cleaned transcript segment representing the candidate's answer |
| 3 | `evidence_citations` | array of EvidenceCitation | One or more evidence citations supporting this observation (minimum 1 required for a scored observation) |
| 4 | `dimension_id` | string | The evaluation dimension this observation scores |
| 5 | `score` | integer (1–5) or null | Numeric score; null if `insufficient_evidence_flag` is true |
| 6 | `score_rationale` | text | Agent's explanation of the score relative to the rubric; must reference the evidence citations |
| 7 | `insufficient_evidence_flag` | boolean | True if the agent could not gather enough evidence to produce a score; when true, `score` is null |
| 8 | `agent_confidence` | float (0.0–1.0) | Agent's self-reported confidence in the observation; informational only, does not affect score |
| 9 | `human_review_status` | enum: `pending`, `approved`, `rejected`, `flagged` | Current review state; starts as `pending` |
| 10 | `reviewer_id` | UUID or null | User ID of the recruiter or hiring manager who last reviewed this observation |
| 11 | `reviewed_at` | timestamp (UTC) or null | When the observation was last reviewed; null until first review action |

**System rule**: An observation with `score` set and `evidence_citations` empty is invalid and will be rejected by the output validator. This enforces **"No evidence, no score"** at the API layer.

**System rule**: When `insufficient_evidence_flag` is true, `score` must be null. The output validator enforces this and will not accept a scored observation with the insufficient evidence flag set.

---

## 12. Blueprint Versioning

Blueprint versioning is resolved as follows:

- Every Blueprint has a `version_number` (integer, starting at 1).
- When a recruiter saves changes to a Blueprint, a new version is created. The previous version is not modified.
- A version is **immutable** once it has been `activated` (i.e., used in at least one interview session). Any further changes create a new version.
- Versions that have never been activated can be edited in place (they exist as drafts).
- When an interview is scheduled, it is pinned to the current active Blueprint version at the time of scheduling. Subsequent Blueprint edits do not affect that interview.
- The `version_number` used for each interview is recorded in the interview record and in the generated report.
- The UI warns recruiters before activating a new Blueprint version if there are upcoming interviews using the previous version, so they can decide whether to re-pin.

This is the resolved policy. There are no open questions about Blueprint versioning.

---

## 13. Interview State Machine

The interview passes through the following states. All transitions are server-side events.

```
CREATED
  |
  v
CONSENT_PENDING          (consent email sent to candidate)
  |
  v (candidate completes consent)
CONSENT_COMPLETED
  |
  v (recruiter activates interview)
AGENT_STANDBY            (agent is in the meeting, waiting for recruiter activation)
  |
  v (recruiter clicks "Activate agent")
INTERVIEW_ACTIVE         (agent is asking questions, generating observations)
  |
  +----> AGENT_MUTED     (recruiter muted agent; agent still listening)
  |         |
  |         v (recruiter unmutes)
  |      INTERVIEW_ACTIVE
  |
  +----> RECRUITER_TAKEOVER  (recruiter has the floor; agent paused)
  |         |
  |         v (recruiter returns control)
  |      INTERVIEW_ACTIVE
  |
  v (recruiter clicks "End interview" or time limit reached)
COMPLETING               (agent finalizing open observations, generating draft report)
  |
  v
REPORT_DRAFT             (draft report available; all observations in pending review status)
  |
  v (all observations reviewed)
REPORT_FINALIZED         (report locked; no further changes without explicit unlock)
  |
  v (retention policy expiry)
ARCHIVED
```

**Invalid transitions**: An interview cannot move from CONSENT_PENDING to AGENT_STANDBY — consent must complete first. An interview cannot move to REPORT_FINALIZED if any observation has `human_review_status = pending`. These constraints are enforced at the API layer.

**Failure states**:
- `AGENT_DISCONNECTED` — agent lost its Zoom connection; recruiter is notified; reconnect attempted automatically
- `AGENT_ERROR` — unrecoverable agent error; recruiter must take over; partial observations are saved

---

## 14. Recruiter Control Room

The Recruiter Control Room is the live interface available to the recruiter during an active interview. It is available in both the browser simulator (M4) and the Zoom integration (M8).

### 14.1 Control Room Panels

**Live Status Panel**
- Agent connection status (connected / muted / disconnected)
- Current question number and total questions
- Time elapsed vs. time limit
- Active dimension being assessed

**Observation Feed**
- Live stream of draft observations as the agent generates them
- Each observation shows: question, response summary, dimension, draft score, evidence citations
- Quick actions: Flag, Approve, Reject (available during interview and post-interview)

**Transcript Panel**
- Live transcript of the interview (recruiter view only)
- Per-speaker attribution (agent vs. candidate)
- Confidence indicator per transcript segment

**Command Bar**
- All 12 recruiter commands (see Section 9) available as buttons
- Command confirmation dialog for destructive commands (Deactivate, End interview)
- Command history log

### 14.2 Control Room Guarantees

- Command responses must be acknowledged within 2 seconds or the UI shows a "Command pending" state
- If the agent loses contact with the control server, it silences itself within 30 seconds
- Control room is accessible on desktop browsers (Chrome, Firefox, Edge); mobile is not supported in MVP

---

## 15. Report Structure

A finalized ExpertSeat interview report contains:

1. **Report Header**: Interview ID, candidate name, role, Blueprint name and version, interview date, interviewer names (human panelists + "ExpertSeat Role Agent"), report generated timestamp
2. **Consent Record**: Confirmation that consent was obtained; consent timestamp; disclosure version
3. **Observations by Dimension**: For each evaluation dimension, all observations associated with that dimension, grouped and presented in order, with scores, rationale, and evidence citations
4. **Skipped Questions**: List of any questions that were skipped and the reason (recruiter skip command, time limit reached)
5. **Insufficient Evidence Flags**: Dimensions where evidence was insufficient for scoring, with explanation
6. **Aggregate Score** (if enabled in blueprint): Weighted average across dimensions, labeled as "weighted average of observations"
7. **Human Review Summary**: Which observations were approved, modified, or rejected, and by whom
8. **Modification Log**: Append-only list of any changes made to observations after initial generation
9. **Transcript** (if enabled in blueprint): Full interview transcript with speaker attribution
10. **Report Footer**: Export timestamp, report version, ExpertSeat version used

Reports are immutable once finalized. Any re-opening creates a new revision; the previous revision is retained.

---

## 16. Compliance Considerations

ExpertSeat is designed with the following compliance posture:

### 16.1 EU AI Act

AI-assisted hiring is classified as high-risk under EU AI Act Annex III. ExpertSeat's design aligns with high-risk obligations:
- AI is disclosed to all participants before the interview
- Humans make all final hiring decisions; AI cannot forward decisions to any system
- All model outputs are logged with evidence citations
- Human oversight (recruiter control room) is mandatory, not optional

Before any EU commercial launch, a formal conformity assessment must be completed (planned M10).

### 16.2 NYC Local Law 144 and Illinois AEIA

Both laws regulate AI tools in employment. Obligations relevant to ExpertSeat:
- Candidate disclosure: handled by consent workflow (Section 6)
- Bias audit requirement: planned for M10; customers in scope must obtain audits
- Terms of service require customers to comply with applicable employment laws in their jurisdiction

### 16.3 GDPR / CCPA

- Data minimization: only interview-relevant data is collected
- Consent is recorded with timestamp and disclosure version
- Data subject access requests (DSAR) workflow: planned post-M7
- Configurable data retention per organization
- Subprocessor DPAs required before regulated-jurisdiction launch
- No candidate data sold or used for model training without explicit separate consent

### 16.4 Recording Laws

Interview audio is processed in real time for transcription but is not recorded by default. Any recording capability requires:
- Separate explicit opt-in consent from all parties
- Legal review before enabling in any jurisdiction
- Recording to be disabled by default in all org configurations

---

## 17. Non-Goals and Exclusions

These are things ExpertSeat explicitly does not try to do:
- Replace human judgment in hiring
- Claim scientific validity of AI interview scores
- Provide a candidate-facing self-assessment product
- Operate as a general-purpose AI assistant
- Record interviews without explicit consent from all parties
- Train AI models on candidate interview data without explicit consent
- Make or forward autonomous hiring decisions to any ATS or HRIS
- Integrate with Google Meet (explicitly out of scope)
- Integrate with Webex (not committed; may follow after Zoom is stable)
- Provide mobile clients in the MVP
- Offer a Verified Blueprint library in the MVP (planned post-pilot only)
- Operate a candidate portal for self-service report access (planned post-pilot)
- Integrate with ATS systems (Lever, Greenhouse, Workday) in the MVP

---

## 18. Milestone Scope Summary

| Milestone | Description | Key Deliverables |
|---|---|---|
| M0 | Foundation | Repo, Docker Compose, FastAPI skeleton, Next.js skeleton, CI, linting |
| M1 | Auth | Organization model, user accounts, JWT auth, org isolation, RBAC skeleton |
| M2 | Blueprint | Blueprint CRUD, versioning, schema validation, blueprint activation |
| M3 | Candidates/Interviews | Candidate records, interview scheduling, consent workflow, consent gate |
| M4 | Browser Simulator | End-to-end interview in browser (no live video), agent question generation, evidence citation, "No evidence, no score" enforcement, recruiter controls, structured report generation, human review workflow |
| M5 | Reporting | Report finalization, audit log, modification log, export, recording consent workflow, data retention policies |
| M6 | Zoom Feasibility Spike | Prove two-way audio, waiting-room handling, bot identity, STT/TTS latency in a real Zoom meeting |
| M7 | Zoom Integration | Full Zoom connector: agent joins as named participant, STT/TTS, mute/unmute, reconnect, failure reporting |
| M8 | Control Room | Full recruiter control room UI for live Zoom interviews; all 12 commands wired to live meeting |
| M9 | Comparison | Multi-candidate report comparison against same Blueprint rubric |
| M10 | Security Hardening | Security audit, PII scrubbing, bias audit capability, CVE scanning, EU AI Act conformity assessment documentation |
| M11 | Pilot Readiness | Ops runbooks, monitoring, HA configuration, pilot customer onboarding |

---

## 19. Browser Simulator (M4)

The browser simulator is a complete end-to-end interview flow in the web browser without live video. It must be built before Zoom integration because it proves all agent logic, evidence handling, and report generation before adding the complexity of a live meeting.

The simulator includes:
- Text-based interview interface (recruiter and candidate views)
- Role Agent question generation from blueprint + evidence
- Evidence citation tracking — every agent output linked to a source
- "No evidence, no score" enforcement — validated at the output parser
- All 12 recruiter commands available in the simulator control room
- Post-interview structured report generation
- Human review workflow with observation approve/flag/reject

The simulator does not include STT/TTS (text input only) or live video/audio. Those are introduced at M6/M7.

---

## 20. Zoom Integration (M7)

### 20.1 MVP Zoom Meeting Behavior

The MVP Zoom meeting behavior includes all of the following. None are optional:
- AI joins as a visible, named participant ("ExpertSeat — AI Panelist")
- Static profile image (no generated video avatar)
- Incoming meeting audio captured for live transcription (speech-to-text)
- Disclosed text-to-speech: AI speech returned to the meeting, recruiter-controlled
- Agent joins muted; recruiter activates when ready
- Recruiter can mute/unmute the agent at any time
- Recruiter can take over (deactivate agent) at any time
- Reconnection and failure reporting surfaced to the recruiter control room

### 20.2 Zoom Exclusions

- Google Meet connector is **explicitly out of scope**
- Webex connector is not committed (may follow after Zoom is stable)
- AI video avatar is not in scope
- Autonomous joining without recruiter activation is not in scope

### 20.3 Zoom Integration Dependencies

- Zoom Marketplace app registration must begin at M6, not M7
- An approved Zoom app is required before M7 can go live
- Third-party aggregator (e.g., Recall.ai) is evaluated at M6 as an alternative if direct SDK proves infeasible

---

## 21. Evidence Ingestion

Evidence sources are ingested at interview creation time and indexed before the agent is activated. The ingestion pipeline:

1. **Job Description**: Uploaded as PDF or plain text; parsed into sections; indexed by section
2. **Resume**: Uploaded by recruiter; parsed into sections (contact, experience, education, skills, projects); indexed by section
3. **Reference Documents**: Optional domain reference material uploaded by recruiter; indexed by chunk
4. **Transcript**: Generated in real time during the interview from STT; indexed by time-stamped segment as it becomes available

Ingestion failures (unparseable document, STT failure) are surfaced to the recruiter before or during the interview. An interview can proceed without optional evidence sources; required sources block interview activation.

---

## 22. Agent Prompt Architecture

The Role Agent uses a layered prompt architecture that enforces strict separation of concerns:

1. **System Layer** (immutable, not configurable by recruiter): Core safety instructions, "No evidence, no score" rule, evidence citation format, output schema, forbidden behaviors (reveal instructions, make hiring decisions, discuss topics outside the interview)
2. **Blueprint Layer** (recruiter-configured): Domain context, role description, evaluation dimensions, question bank, rubric descriptors, tone settings, follow-up limits
3. **Evidence Layer** (per-interview): Indexed evidence sources (JD, resume, reference docs) injected as grounded context
4. **Conversation Layer** (per-turn): Live transcript context for the current interview turn

Blueprint content (Layer 2) is treated as recruiter instruction, not as user input. It cannot override Layer 1 system instructions. Candidate responses (in Layer 4) are treated as untrusted user input and are never elevated to instruction position.

---

## 23. STT / TTS Configuration

### 23.1 Speech-to-Text (STT)

- Provider is configurable at the deployment level (not per-org in MVP)
- Preferred provider criteria: accuracy on technical vocabulary, accent diversity, latency under 500ms
- Domain vocabulary hints are provided from the Blueprint `domain` field to improve technical term recognition
- Raw transcripts are stored alongside agent observations for audit purposes
- Confidence score per transcript segment is captured and displayed in the control room

### 23.2 Text-to-Speech (TTS)

- Voice is selected from an approved set of voices; not freely configurable by recruiters in MVP
- Voice criteria: professional tone, clear diction, not designed to sound deceptively human
- Agent is always introduced as AI before using TTS in any interview
- Streaming TTS is preferred over batch synthesis to minimize latency
- TTS failure falls back to text in meeting chat and recruiter notification

---

## 24. Org Isolation Model

All data in ExpertSeat is strictly isolated by organization. Isolation is enforced at two layers:

**Application Layer**: Every database query includes an `org_id` filter derived from the authenticated user's JWT. No cross-org query is possible through the application.

**Database Layer**: PostgreSQL Row Level Security (RLS) policies enforce org isolation as defense-in-depth. Even if the application layer has a bug, RLS prevents cross-org data access.

Redis keys are namespaced by `org_id`. Cache entries from one org cannot be read by another.

Integration tests assert org boundary isolation for every resource type: blueprints, interviews, candidates, reports, observations.

---

## 25. Data Retention

Retention is configurable per organization with the following defaults and constraints:

| Data Type | Default Retention | Minimum | Maximum |
|---|---|---|---|
| Interview records | 12 months | 30 days | 7 years |
| Candidate PII | 12 months | 30 days | 7 years |
| Transcripts | 12 months | 30 days | 7 years |
| Audit logs | 36 months | 12 months | Indefinite |
| Consent records | 36 months | 12 months | Indefinite |

On expiry, candidate PII is hard-deleted (not soft-deleted). Non-PII interview metadata (timing, blueprint version used, dimension IDs) may be retained in anonymized form for platform analytics only if the org opts in.

Deletion events are recorded in the audit log.

---

## 26. Audit Log

The audit log captures the following event types (append-only, immutable):

- Interview created / scheduled / started / completed
- Consent sent / completed / withdrawn
- Agent activated / deactivated / muted / unmuted
- Observation created / approved / flagged / rejected / modified
- Report finalized / re-opened / exported
- Blueprint created / version activated
- User authentication events
- Org admin actions
- Data retention deletion events

Audit log entries include: event type, timestamp (UTC), user ID (or "system"), resource type and ID, and a diff for modification events.

---

## 27. API Design Principles

- All API responses use explicit Pydantic response schemas; no full ORM model passthrough
- All endpoints require authentication except the candidate consent endpoint (which uses a signed token)
- All mutation endpoints are idempotent where possible
- Pagination is required for all list endpoints (cursor-based)
- API versioning via URL prefix (`/api/v1/`)
- Rate limiting on all endpoints; stricter limits on authentication endpoints
- All timestamps in UTC ISO 8601

---

## 28. Security Principles

- Secrets managed via environment variables; never committed to source control
- JWT access tokens in memory only (not localStorage); refresh tokens in httpOnly cookies
- CSP headers on all frontend responses
- All database queries parameterized; no string interpolation in SQL
- PII scrubbing middleware on all log outputs
- Blueprint content treated as recruiter instruction but cannot override system-layer constraints
- Candidate input treated as untrusted user data at all times

---

## 29. Principles

### Disclosure First
No AI agent participates without explicit candidate disclosure and consent. This is non-negotiable.

### Human in the Loop
AI agents produce reports. Humans make decisions. ExpertSeat does not automate hiring. Recruiters control everything.

### Evidence-Bounded
Role Agents operate only on provided evidence. They do not hallucinate domain facts, invent candidate history, or speculate beyond what is in the interview record. **"No evidence, no score"** is a hard system rule. **"Insufficient evidence"** is the correct output when evidence is absent, not a zero score.

### Org Isolation
All data is strictly isolated by organization. One org cannot access another's blueprints, candidates, or reports.

### Honest Limitations
ExpertSeat does not claim to eliminate bias, improve diversity outcomes, or produce fair evaluations. These are hard problems that AI does not solve. We commit to monitoring, transparency, and continuous improvement.

### Minimal Data
We collect only what is needed for the interview record. We do not sell candidate data. Retention policies are configurable per organization.

---

## 30. Recruiter Workflow

1. **Create a Blueprint**: Define the role, upload reference material, configure evaluation criteria and rubrics.
2. **Schedule an Interview**: Associate a Blueprint (specific version) with a candidate and a time slot.
3. **Candidate Consent**: Candidate receives a pre-interview disclosure explaining that an AI panelist will participate. Consent is required to proceed. Interview is blocked until consent is confirmed.
4. **Live Interview**: The Role Agent joins as a disclosed panelist. Human panelists may also be present. The agent asks questions, probes responses within follow-up limits, and generates evidence-backed observations. The recruiter monitors and controls the agent at all times.
5. **Report Generation**: After the interview, the Role Agent produces a structured draft report: questions asked, candidate responses (transcript), scored observations per evaluation dimension, and evidence citations for every score. Dimensions with insufficient evidence are flagged as "Insufficient evidence", never scored zero.
6. **Human Review**: A human recruiter or hiring manager reviews the draft report. They may approve, flag, or reject any observation. No observation is final until reviewed. The final hiring decision is always made by a human outside the ExpertSeat platform.
7. **Report Finalization**: All observations reviewed. Report is locked. Available for export and candidate comparison.
8. **Comparison** (optional, M9): Compare multiple candidate reports against the same Blueprint rubric.

---

## 31. Open Questions

There are no open questions about Blueprint versioning (resolved in Section 12).

The following questions remain open as of the date of this specification:

1. Should candidates have access to their interview reports, and if so under what conditions? (planned for post-pilot candidate portal)
2. How should we handle interview recordings when the meeting connector supports them beyond the consent workflow already defined? (details deferred to M5)
3. What is the right abuse model for Verified Blueprints — who can flag and what happens? (post-pilot)
4. Should organizations be able to create private Blueprint libraries with granular access controls within the org? (post-pilot)
5. What is the right data retention default for edge cases where org has not configured a policy? (to be resolved before M5 launch)
