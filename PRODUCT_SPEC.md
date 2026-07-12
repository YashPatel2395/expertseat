# ExpertSeat — Product Specification

**Version**: 0.1 (Foundation)
**Status**: Draft — subject to change before Milestone 1
**Date**: 2026-07-12

---

## 1. Mission

ExpertSeat enables recruiting teams to add AI domain experts to interview panels when no qualified human panelist is available. Every AI panelist is disclosed to candidates, operates within recruiter-defined constraints, and produces evidence-backed output for human review.

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

Blueprints are created and owned by organizations. They are versioned.

### 3.2 Role Agent

A **Role Agent** is an instantiation of a Blueprint for a specific interview. It:
- Operates within the constraints defined by its Blueprint
- Asks questions in sequence or adaptively based on candidate responses
- References only permitted evidence sources
- Does not make hiring recommendations — it produces scored observations

A Role Agent is not a general-purpose AI assistant. Its scope is strictly limited to the interview context.

### 3.3 Custom vs. Verified Blueprints

**Custom Blueprints** are created by the recruiter's organization. They are unaudited and may reflect the organization's own biases or gaps. Organizations bear responsibility for their content.

**Verified Blueprints** (planned, Milestone 4+) are reviewed by ExpertSeat against a quality rubric before publication to a shared library. Verification does not guarantee fairness or correctness — it confirms that the blueprint meets structural and quality standards.

### 3.4 Evidence

Every Role Agent question and scoring observation must be grounded in **evidence**:
- The job description provided at blueprint creation
- Domain reference material explicitly uploaded by the recruiter
- The candidate's own submission (resume, portfolio, code samples)
- The candidate's responses during the interview

Role Agents may not introduce factual claims that cannot be traced to one of the above sources.

---

## 4. Recruiter Workflow

1. **Create a Blueprint**: Define the role, upload reference material, configure evaluation criteria.
2. **Schedule an Interview**: Associate a Blueprint with a candidate and a time slot.
3. **Candidate Consent**: Candidate receives a pre-interview disclosure explaining that an AI panelist will participate. Consent is required to proceed.
4. **Live Interview**: The Role Agent joins as a disclosed panelist. Human panelists may also be present. The agent asks questions, probes responses, and notes observations.
5. **Report Generation**: After the interview, the Role Agent produces a structured report: questions asked, candidate responses (summarized), scored observations per evaluation dimension, and a list of evidence citations.
6. **Human Review**: A human recruiter or hiring manager reviews the report. They may accept, modify, or discard any observation. The final hiring decision is always made by a human.
7. **Comparison** (optional): Compare multiple candidate reports against the same Blueprint rubric.

---

## 5. Candidate Consent

ExpertSeat requires explicit candidate consent before any AI agent participates in an interview. The consent disclosure must:
- Identify that an AI system will participate as a panelist
- Name the system (ExpertSeat Role Agent)
- Describe what the agent will do (ask questions, observe responses, produce a report)
- Describe what the agent will not do (make hiring decisions, access data outside the interview)
- Provide a mechanism to decline without penalty

Consent records are stored with timestamps and the exact disclosure text shown.

---

## 6. Human Review Requirements

No ExpertSeat output flows to a hiring decision without human review. Specifically:
- Reports are not auto-forwarded to ATS or decision systems
- Scored observations are presented as observations, not verdicts
- Human reviewers can override any score or remove any observation
- Audit logs record which observations were accepted, modified, or rejected

---

## 7. MVP Scope (Milestone 3)

The MVP includes:
- Organization and user accounts (recruiter role only)
- Blueprint creation and versioning
- Candidate record management
- Interview scheduling with consent flow
- Role Agent interview participation via web (text-based, no live video in MVP)
- Structured report generation
- Human review workflow with observation acceptance/rejection
- Basic audit logging

### 7.1 MVP Exclusions

The following are explicitly out of scope for MVP:
- Live video/audio integration (Milestone 5)
- Verified Blueprint library (Milestone 4)
- Multi-panelist collaborative scoring (Milestone 6)
- Candidate portal / self-service (Milestone 7)
- ATS integrations (Milestone 8)
- Mobile clients (post-MVP)
- Real-time transcription (Milestone 5)
- AI voice synthesis (not planned — considered high risk)

---

## 8. Principles

### Disclosure First
No AI agent participates without explicit candidate disclosure and consent. This is non-negotiable.

### Human in the Loop
AI agents produce reports. Humans make decisions. ExpertSeat does not automate hiring.

### Evidence-Bounded
Role Agents operate only on provided evidence. They do not hallucinate domain facts, invent candidate history, or speculate beyond what is in the interview record.

### Org Isolation
All data is strictly isolated by organization. One org cannot access another's blueprints, candidates, or reports.

### Honest Limitations
ExpertSeat does not claim to eliminate bias, improve diversity outcomes, or produce fair evaluations. These are hard problems that AI does not solve. We commit to monitoring, transparency, and continuous improvement.

### Minimal Data
We collect only what is needed for the interview record. We do not sell candidate data. Retention policies are configurable per organization.

---

## 9. Non-Goals

These are things ExpertSeat explicitly does not try to do:
- Replace human judgment in hiring
- Claim scientific validity of AI interview scores
- Provide a candidate-facing self-assessment product
- Operate as a general-purpose AI assistant
- Record interviews without explicit consent from all parties
- Train AI models on candidate interview data without explicit consent

---

## 10. Open Questions

These questions are unresolved as of Milestone 0:

1. What is the right model for Blueprint versioning — immutable versions or diffs?
2. Should candidates have access to their interview reports?
3. How should we handle interview recordings when the meeting connector supports them?
4. What is the right abuse model for Verified Blueprints — who can flag and what happens?
5. How do we handle candidates who consent initially but withdraw mid-interview?
6. What is the right data retention default?
7. Should organizations be able to create private Blueprint libraries with access controls?
