# Church SharePoint Archive Project

## Specification v3

---

## 0. Revision Notes (v2 → v3)

This revision reflects a fundamental reframing: **the archive has no existing users.** The corpus was pulled from a single OneDrive previously accessible only to the operator's spouse. No other staff, clergy, board members, or congregants have ever accessed it. This project is therefore a **launch**, not a migration.

Several v2 sections existed to manage disruption to existing users. Those sections are simplified or removed. Other sections gain weight because the project is now establishing institutional precedent rather than modifying existing practice.

Changes by section:

- **§1 Problem** — updated to reflect launch context
- **§6 Technical Architecture** — SharePoint sandbox test demoted from project-gate to operational sanity check; Architecture B (side-by-side library) removed entirely
- **§7 Extraction Schema** — added fields for contradiction detection (`effective_date`, `superseded_by`, `topic_canonical` on policy_statements) and commitment closure (`status`, `closed_by_document`, `assigned_to`, `due_date` on decisions and obligations)
- **§8 Conventions** — folder-depth contradiction resolved: strict 3-level cap, with a named and scoped exception for time-series categories (Bulletins, Minutes) that may use a fourth level for year-split only, triggered at 300 items
- **§11 Autonomous Approval** — removed the broad "files routed to already-approved folders" rule
- **§12 Backup Strategy** — formerly "Rollback"; simplified because no external references, share links, or permissions inheritance exist to preserve
- **§13 Launch Plan** — formerly "Change Management"; rewritten from disruption management to first-impression and precedent-setting
- **§14 Deliverables** — office hours replaced with digital feedback form; launch communications replace migration communications
- **§17 Prayer Concerns Policy** — new section; elevates prayer-concerns handling from open decision to draft policy for pastoral review
- **§10 Acceptance Criteria** — recalibrated; contradiction-detection and commitment-closure criteria now rest on schema fields that actually exist; review-time estimate revised to 4–8 hours

Content changes are substantial. Architecture simplifies; governance sharpens.

---

## 1. Problem

The archive corpus has passed through multiple storage systems over the years — external disk, `C:\`, OneDrive — and currently sits in a SharePoint location with zero active users. Prior access was limited to one individual (the operator's spouse). The church as an institution has never had working access to its own historical digital records.

This is not a reorganization of content anyone currently uses. It is an **institutional launch**: the first time the church's accumulated digital records will be accessible to the people responsible for running it.

The core questions remain:

1. What do we have?
2. What do we need?
3. Where is it now? *(trivially answered: in a single unused SharePoint location)*
4. Where should it be instead?

But a new question is implicit in the launch framing:

5. **What precedent does this establish for how the church handles its records going forward?**

The answer to #5 shapes decisions across the project. Filename conventions, folder taxonomy, sensitivity rules, and retention policies chosen here will become the de facto institutional standard for the foreseeable future, because there is no competing standard in place.

## 2. Purpose

Launch an institutional archive of the church's digital records that is:

- **Navigable** — any board member or staff member can find what they need by clicking through SharePoint folders
- **Comprehensible** — filenames describe what files actually are
- **Queryable** — cross-cutting questions can be answered programmatically via the SQLite database
- **Durable** — the output survives the departure of the current operator and remains readable in 30 years
- **Safe** — sensitive content is identified and governed; nothing is destroyed
- **Auditable** — every decision (including exclusions) is recorded for board review
- **Precedent-setting** — the conventions used become the church's working standard for filing new records going forward

## 3. Scope

### In Scope

- All files in the current SharePoint location (~1,500 files, estimated; pending pre-flight census)
- Text documents, PDFs (including scanned), Word documents, PowerPoints, images
- Years of bulletins from multiple legacy storage systems
- Reorganization into a flat, navigable folder structure
- Production of a SQLite knowledge base alongside the reorganized files
- **Establishment of institutional conventions** (filename format, taxonomy, sensitivity policy) as the church's default going forward

### Out of Scope

- Web UI or congregant-facing interface
- Chatbot or conversational access to the archive
- Continuous synchronization with new file uploads
- Multi-user access controls (SharePoint's native tools handle permissions)
- Integration with other church systems
- Ongoing AI expenses after initial launch (new files are a small, separate recurring cost)
- Inference of content that was never documented (see §10)

### Exclusion Policy

Certain categories of content must not be sent to any external API under any circumstances, regardless of operational benefit. These are excluded at the pre-flight stage, before any batch submission. Excluded categories:

- **Active pastoral care records** — counseling notes, spiritual direction logs, confidential clergy-member correspondence
- **Individual giving records** — per-member contribution histories, pledge cards, donor-identifying capital campaign material
- **Medical or health-related records** of individual members
- **Personnel files** with performance evaluations, disciplinary records, or named-individual compensation details
- **Records involving minors** in any context that names them individually (baptism/confirmation certificates excepted where publicly announced; counseling/disciplinary records not excepted)
- **Active legal correspondence** — ongoing matters, attorney-client material, pending insurance claims
- **Records subject to denominational confidentiality obligations**

The operator identifies these folders or files before the read pass, marks them for exclusion, and records the exclusion in the **Formal Exclusion Log** (§16). The content itself remains in place; only its exposure to the API is controlled.

Closed matters (resolved legal cases, historical pastoral correspondence of deceased members, personnel files of long-departed staff) may be handled differently, with explicit board authorization documented in the log. When in doubt, exclude.

## 4. Approach

One deep reading pass with selective model routing produces a structured extraction of every in-scope file. That extraction drives both a reorganized SharePoint (the primary deliverable for church use) and a SQLite database (for cross-cutting queries).

The sequence:

1. **Pre-flight** — local Python, no API cost. File hashing, deduplication, text extraction where possible, legibility assessment for scans, file-health check, exclusion-policy sweep. Produces a clean manifest, a quarantine list, and an exclusion list.
2. **Haiku pre-classification** — cheap per-file pass that assigns a preliminary document type and identifies decorative graphics, system junk, and obvious duplicates not caught by hashing.
3. **Model routing** — based on Haiku classification, each file is assigned to Opus, Sonnet, or Haiku for deep read. Routing defined in §6.
4. **Deep read pass** — batched API calls per model tier. Each file extracted against the Core schema (mandatory) and Enriched schema (best-effort).
5. **Haiku clustering** — extraction summaries grouped into thematic buckets to produce an input that fits Opus's context window for the taxonomy pass.
6. **Taxonomy proposal pass** — one Opus call operating on bucket summaries rather than raw extractions. Proposes a flat folder structure based on what the corpus actually contains. Operator review and adjustment before commit.
7. **Destination assignment pass** — each file matched to a destination folder and given a clean filename, based on finalized taxonomy. Batched, per model tier.
8. **Human review** — operator reviews proposed destinations. Category-based autonomous-approval rules (§11) bulk-approve narrow classes; everything outside those classes is reviewed individually.
9. **Execute moves** — confirmed moves applied to SharePoint via the Microsoft Graph API. File-level backup zip created beforehand.
10. **Launch** — the archive is introduced to the board and staff as a new institutional resource (§13).

## 5. Outputs

### Primary: Launched Archive in SharePoint

Three-level folder depth (with a named exception for time-series categories; see §8). Plain-English folder names. All filenames following `YYYYMMDD Description - Distinguishing detail.ext` where dates apply, descriptive-only for evergreen material.

Example structure (illustrative — actual taxonomy emerges from the read pass):

```
/Governance/
  /Bylaws/
  /Board Minutes/2019/
  /Board Minutes/2020/
  /Policies/
/Worship/
  /Bulletins/2019/
  /Bulletins/2020/
  /Sermons/
/Finance/
  /Annual Reports/
  /Budgets/
  /Audits/
/Property/
  /Contracts/
  /Capital Projects/
  /Maintenance Records/
/Pastoral/
/Personnel/
/History/
/Communications/
/Outreach/
/_Superseded/
/_Quarantine/
```

### Secondary: SQLite Database

A single `archive.sqlite` file. Tables:

- `files` — one row per physical file, with original path, hash, size, pre-flight flags
- `documents` — logical documents with Core + Enriched schema fields
- `references` — edge table linking documents that cite one another
- `entities` — normalized people, committees, organizations, properties
- `moves_log` — original path, destination path, move timestamp, approval record
- `exclusion_log` — mirror of §16 for programmatic access
- `model_routing_log` — which model read which file, cost per read

Queryable via any SQLite tool. Backed up by simple file copy.

### Supporting Deliverables

- `_Archive Notes.txt` at SharePoint root — brief description of what the archive contains, how to navigate it, and who to contact with questions
- `pre-launch-backup.zip` — file-level backup of the pre-launch corpus (complete rollback mechanism; see §12)
- **Launch plan artifacts** (§14)

## 6. Technical Architecture

### Application

Single Windows executable, Python + Tkinter GUI packaged via PyInstaller. Source Python preserved alongside the executable for future maintenance.

### User Interface

- First-run dialog for Anthropic API key entry with "Test Key" verification via a cheap Haiku call
- First-run dialog for SharePoint tenant configuration
- Single-window main interface: Survey, Review, Execute, Export
- Progress bar and status line during long operations
- Modal success/failure popups
- Review window presents one file at a time, sorted by category and priority, Enter-key driven
- Configuration stored in `%APPDATA%\ChurchArchivist\`
- No command-line interaction at any point

### SharePoint Integration

**Library:** `Office365-REST-Python-Client` (primary) with Microsoft Graph API fallback.

**Authentication:** Azure App Registration in the church's tenant with delegated permissions:

- `Sites.ReadWrite.All`
- `Files.ReadWrite.All`
- `Sites.Manage.All` (if new folder creation requires it)

**Authentication flow:** First-run wizard captures tenant URL, client ID, and client secret. Credentials encrypted at rest via Windows DPAPI.

**Sandbox sanity check (operational, not gating):** Before the production run, the operator performs a 5-file upload-move-rename cycle against a test folder to confirm the library functions as expected in the church's specific tenant configuration. This is a routine operational check, not a project-gate. Unlike a migration scenario where metadata preservation is critical, this archive is being populated for the first time — there is no prior state to preserve.

### Backend Pipeline

- Python 3.11+ with standard libraries for file walking, hashing, SQLite
- `pypdf`, `python-docx`, `mammoth` for text extraction
- `OpenCV` (headless) for legibility pre-check — contrast ratio, estimated DPI, bleed-through detection
- `tesseract` (via `pytesseract`) **optional** — generates searchable text layers for scanned PDFs as a supplementary deliverable; not required for feeding content to Claude (vision handles that natively)
- Anthropic Python SDK for Claude API calls
- Anthropic **Batch API** for all bulk work (50% cost reduction; 24-hour turnaround acceptable)

### Model Routing

Per-file assignment made after Haiku pre-classification:

| Document Class | Model | Rationale |
|---|---|---|
| Bulletins, newsletters, routine correspondence, formulaic announcements | **Sonnet 4.6** | Formulaic structure; Sonnet extracts the bulletin schema reliably at ~40% of Opus cost |
| Board minutes, policies, contracts, legal material, financial statements, historical documents | **Opus 4.7** | Require reasoning, reference tracking, nuanced sensitivity flagging |
| Decorative graphics, system junk, scan artifacts, low-information files | **Haiku 4.5** | Classify-and-quarantine; no deep extraction needed |
| Ambiguous or uncategorized | **Opus 4.7** | Uncertainty escalates to the most capable model |

Routing is recorded in `model_routing_log` with per-call cost. If the 50-file sample reveals routing errors (e.g., a "bulletin" containing substantive board content), affected files are re-run at the higher tier.

### Vision Configuration

- Default resolution: **1024px**, applied via local downsampling before transmission
- Escalation to **2048px** or (rarely) **2576px** for files flagged by the legibility pre-check
- Flagging criteria: Michelson contrast below 0.35, estimated effective DPI below 200, or significant bleed-through
- Legibility pre-check is local compute, zero API cost, prevents paying for failed reads on illegible scans

### Safety and Reliability

- All pipeline stages idempotent and resumable
- No destructive operations without explicit human confirmation
- Pre-launch backup zip created before any moves
- Failed files logged separately and reported
- Crash log with traceback on unhandled exceptions
- Kill-switch halts processing if cost exceeds threshold

## 7. Extraction Schema

Split into **Core** (mandatory for every file) and **Enriched** (best-effort).

### Core — Required for Every File

- `document_type` — enum (board_minutes, bulletin, policy, contract, correspondence, photo, personnel_file, financial_document, pastoral_record, bylaws, newsletter, annual_report, scanned_image, graphic, other)
- `title`
- `summary_one_sentence`
- `date_primary` and `date_primary_precision` (day / month / year / decade / undateable)
- `sensitive_flags[]` with category and severity
- `condition` (readable / partial / scanned_clean / scanned_messy / corrupted)
- `proposed_folder`
- `proposed_filename`
- `confidence_identity` and `confidence_destination`
- `evidence_quotes[]` — at least one direct quote supporting the identity classification

Core extraction failure on any field flags the file for human review. The pass does not silently defer Core fields.

### Enriched — Best-Effort

- `summary_full`
- `date_primary_source` (document_header / signature / EXIF / filesystem / inferred)
- `date_references[]`
- `participants[]` (subject to entity normalization)
- `entities[]` (committees, organizations, properties)
- `subjects[]`
- `authenticity_markers` (draft / final / signed / stamped / superseded)
- `audience_restriction_recommended` (public / members / board / clergy / confidential)
- `flags_for_human_review[]`
- `belongs_in_archive` (boolean with rationale for false)

### Decisions and Obligations (Enriched)

Each entry in `decisions[]` and `obligations[]` carries:

- `content` — the decision or commitment itself
- `assigned_to` — person or committee responsible (may be "unassigned")
- `due_date` — if stated
- `status` — enum (open / closed / superseded / unknown); default `unknown` when the document does not indicate
- `closed_by_document` — reference to another document that records the closure, if the extractor identifies one
- `evidence_quote` — supporting text

These fields support the acceptance criterion "what commitments have been recorded and not closed" (§10).

### Policy Statements (Enriched)

Each entry in `policy_statements[]` carries:

- `content` — the normative claim
- `effective_date` — when the policy takes effect (from document text or date_primary)
- `superseded_by` — reference to a later document that explicitly replaces this statement, if identified
- `topic_canonical` — a normalized topic key produced by the entity normalization pass (allows grouping related claims across documents)
- `evidence_quote`

These fields support the acceptance criterion "where does the archive contradict itself" (§10) via a SQL query that groups statements by `topic_canonical`, filters for overlapping valid periods (based on `effective_date` and `superseded_by` resolution), and flags groups with non-identical `content`.

### Bulletin-Specific (Enriched)

For files classified as bulletins:

- `service_date`, `liturgical_occasion`, `presider`, `preacher`
- `sermon_title`, `sermon_text` (scripture references)
- `hymns[]`, `music[]`, `participants_liturgical[]`
- `prayer_concerns[]` — governed by §17 Prayer Concerns Policy
- `announcements`, `milestones[]`, `offering_designation`, `attendance`

## 8. Conventions

### Filename Format

- `YYYYMMDD Description - Distinguishing detail.ext` where dates apply
- Partial dates: `YYYYMM`, `YYYY`, `YYYYs` (decade); truncate from the right as precision decreases
- Single space between date block and description
- Single space-dash-space between primary description and disambiguator
- No underscores, no CamelCase, no version suffixes (`_v2`, `_final`)
- **No prefix for evergreen reference material** — sorts to top of folder, which is the desired behavior

Examples:

```
20240617 Board Minutes - Regular Meeting.pdf
20240617 Board Minutes - Executive Session.pdf
20190421 Bulletin - Easter Sunday.pdf
20160812 HVAC Contract - Johnson Controls.pdf
Bylaws.pdf
Constitution.pdf
```

**Institutional standard going forward:** This convention becomes the church's default for filing new records. Documented in `_Archive Notes.txt` and in the launch materials so that new files added post-launch follow the same pattern.

### Folder Structure

- **Three levels maximum, strict cap, with one named exception.**
- **Named exception for time-series categories** (`Bulletins`, `Board Minutes`, `Newsletters`, similar): these may use a fourth level for year-split, triggered when the third-level folder exceeds 300 items. No other category uses a fourth level.
- **Minimum 15 items per folder.** Thinner folders collapse into parent with date-prefixed filenames.
- **Hard cap 300 items per folder.** Mobile-view and web-pagination considerations make larger flat folders genuinely painful. Year-split is the escape valve for time-series content; for non-time-series content hitting the cap, the fix is splitting the category itself, not deepening the hierarchy.

Filename convention remains the primary navigation mechanism. Folder structure is an aid, not the mechanism. A well-named file is findable regardless of folder via SharePoint's native search and column-view sort.

## 9. Budget

### One-time costs (initial launch)

With model routing:

| Item | Estimate |
|---|---|
| Pre-flight (local compute) | $0 |
| Haiku pre-classification (1,500 files) | $2–5 |
| Deep read — Opus tier (~40% of files, batched, vision) | $30–50 |
| Deep read — Sonnet tier (~50% of files, batched) | $10–18 |
| Deep read — Haiku tier (~10% of files) | $1–3 |
| Haiku clustering + Opus taxonomy pass | $5–10 |
| Destination assignment pass (per-tier, batched) | $5–12 |
| Entity normalization (Haiku) | $3–8 |
| Contingency (oversized scans, schema iteration, re-runs) | $20–40 |
| **Total expected** | **$75–145** |
| **Acceptable ceiling** | **$200** |

### Ongoing costs (new files)

- ~$0.15–0.30 per new file added
- No subscription, hosting, or recurring API commitment

### Kill-switch

Halt if running cost exceeds **$225** without explicit operator re-authorization.

## 10. Acceptance Criteria

The launch is successful when:

1. **Every in-scope file has been read and extracted.** Core schema fields are populated for each. Files excluded per §3 are logged in §16; files that failed extraction are flagged for manual review.
2. **Board-member navigability test.** A board member unfamiliar with the archive, given 10 test questions ("find the most recent HVAC service contract," "find the 2019 annual report," etc.), can locate all 10 using only SharePoint's native interface in under 10 minutes.
3. **Filename accuracy validation.** On a 50-file random sample, an independent reviewer can describe each file's purpose from filename alone, with at least 45/50 (90%) matching the actual content.
4. **Extraction quality validation.** On the same 50-file random sample, the model's `document_type`, `date_primary`, and `summary_one_sentence` fields are correct on at least 45/50 files by human review.
5. **SQL-answerable cross-cutting queries:**
   - *"What documents are referenced but missing?"* — a join between `references` and `documents` returning unresolved targets
   - *"What commitments are open?"* — query against `decisions` and `obligations` filtered on `status = 'open'` or `status = 'unknown'` with overdue `due_date`
   - *"Where does the archive contradict itself?"* — group by `policy_statements.topic_canonical`, filter for overlapping effective periods with non-identical content
   - *"What sensitive content is placed inappropriately?"* — `documents.sensitive_flags` cross-referenced with current SharePoint folder permissions
6. **Backup integrity.** The pre-launch zip is validated as complete (file count matches manifest; hash sample verifies content).
7. **Application re-runs on new files** without regenerating the existing archive.
8. **Exclusion Log is complete** and reviewed by the board at launch.
9. **Launch materials delivered** and circulated (§14).

### Explicitly Out of Scope

- *"What institutional context is implied but undocumented?"* — An archive can only contain what was actually written down. A 2026 model's guesses about what the 2019 church implicitly believed are not durable archival data. Questions of this type are deferred to human archival analysis if ever pursued.

### Review-Time Estimate

Based on expected queue composition under the §11 rules — roughly 300 files requiring individual review out of 1,500 — the operator's manual review time is expected to be **4–8 hours**, calibrating slower in the first hour and accelerating as patterns become familiar.

## 11. Autonomous Approval Rules

Category-based, not confidence-threshold based. The operator's attention focuses on genuinely ambiguous cases.

### Auto-Approved (no individual review)

- **Exact hash duplicates** — retain one, quarantine the rest with reference to the retained copy
- **Bulletins with strong date evidence** — date extracted from document header AND liturgical occasion extracted AND filename date matches document date
- **Board minutes with strong date evidence** — meeting date in document header AND meeting type identified (regular, executive session, special) AND no sensitive flags raised

### Always Manually Reviewed

- Any file with any `sensitive_flags[]` populated
- Any file with `confidence_identity` below 0.80
- Any file with `confidence_destination` below 0.85
- Any file where the model populated `flags_for_human_review[]`
- Any file classified as `personnel_file`, `pastoral_record`, `financial_document` (individual-level), or `other`
- Any file being routed to `_Quarantine` or `_Superseded`
- The first 20 files of any auto-approved category, to sanity-check the category rule before bulk approval

### Review Interface

Files presented one at a time, sorted by priority. Keyboard-driven: Enter approves, F fixes, S skips for later. Progress counter visible. When the manual queue is empty, a final bulk-approval confirmation shows auto-approved counts per category with spot-check samples before moves execute.

## 12. Backup Strategy

Because the archive has no existing users, share links, external references, or permissions inheritance anyone depends on, the pre-launch backup zip is a **complete rollback mechanism**. If the launch needs to be reversed, the zip is restored to SharePoint and the state before this project is fully recoverable.

The zip contains:

- Every in-scope file under its pre-launch path
- A manifest listing all files with hashes for integrity verification
- The exclusion log current as of zip creation

The zip is retained indefinitely. It is the project's immutable baseline.

`moves_log` records every source→destination move with timestamps, allowing targeted reversals of individual files or small groups if specific cases need correction post-launch without full rollback.

## 13. Launch Plan

Because the archive has no existing users, this project is introducing a new institutional resource rather than modifying one people are already using. The launch plan is oriented toward **first impression, precedent-setting, and onboarding**, not toward disruption management.

### First-Impression Integrity

The first board member or staff member to open the archive forms a judgment that sticks. If their first click lands on a misfiled document, the archive is written off as "Bart's AI project didn't really work." If it lands on a correctly-filed, well-named file, the archive becomes trusted infrastructure. The §10.3 and §10.4 validation sample exists partly to protect the launch: errors discovered in the sample are fixed before any non-operator sees the archive.

### Precedent-Setting

The conventions adopted in this project — filename format, folder taxonomy, sensitivity flags, retention handling — become the church's working standard for digital records going forward, because there is no competing standard. This is stated explicitly in `_Archive Notes.txt` and in launch communications so that new files added by staff or board members follow the same pattern.

A one-page "How to file new documents" reference is produced as a launch artifact, explaining the filename convention and top-level folder destinations for common document types.

### Onboarding Mechanism

In place of transition office hours (which would invite real-time grief and scope creep), a **digital feedback form** is established for the first 90 days post-launch:

- "I expected to find X and couldn't"
- "This file is in the wrong place"
- "This file is misnamed"
- "I have a question about the archive"

Form submissions produce a searchable log of UX failures rather than a series of emotional conversations. The operator reviews submissions weekly and makes adjustments in batches. Batched adjustments are less disruptive to the archive's integrity than real-time edits.

### Launch Communications

- **Board announcement email** — what the archive is, why it exists, how to access it, what the filing standard is going forward, how to submit feedback
- **Staff-facing one-pager** — quick reference for the filename convention and top-level folder destinations
- **Congregation-facing short note** (optional, at board discretion) — brief mention in a newsletter or bulletin that the church has developed an institutional archive; generally does not require active congregant engagement

### Launch Timing

The board is briefed before access is granted. A one-week window between board briefing and general staff access allows the board to review, raise concerns, and request adjustments before broader exposure.

## 14. Deliverables

At project completion:

1. **Launched SharePoint archive** (primary, in place)
2. `archive.sqlite` — structured knowledge base
3. `pre-launch-backup.zip` — validated complete backup
4. `ChurchArchivist.exe` — application for future runs on new files
5. **Source Python** alongside the executable
6. `_Archive Notes.txt` at SharePoint root — archive description and navigation guide
7. **Formal Exclusion Log** (§16) — board-reviewed
8. **Sensitive-content audit report** — separate document, secure distribution
9. **Missing-documents report** — referenced-but-unlocated files for follow-up
10. **Extraction validation report** — §10.3 and §10.4 sample results
11. **Launch communication artifacts:**
    - Board announcement email
    - Staff-facing filing one-pager
    - Congregation-facing short note (if approved by board)
    - Digital feedback form (configured and active)
12. **Prayer Concerns Policy** (§17) — draft presented to pastor and board for adoption
13. **This specification** (v3 and any successors) — retained as project record

## 15. Open Decisions

Items requiring operator, pastoral, or board decision before execution:

1. **Top-level taxonomy categories** — approved after the model proposes them, informed by actual corpus contents. Operator adjusts based on what the proposal reveals.
2. **Sensitive-content taxonomy refinement** — starting categories from §3 and §7 are the working set; board review may add or modify.
3. **Prayer Concerns Policy** — draft in §17; requires pastoral review before adoption.
4. **Closed-matter exceptions to exclusion policy** — board identifies which categories of historical sensitive content (long-deceased members, resolved legal matters, long-departed staff) may be processed under explicit authorization.
5. **Evergreen documents to override date-prefix convention** — identified during review and overridden individually.
6. **Disposition of `_Quarantine` contents** — timeline and process for reviewing files flagged as "does not belong in church archive."
7. **Congregation-facing communication** — whether to include a short archive-existence note in the newsletter or bulletin; board discretion.

## 16. Formal Exclusion Log

Written record of every file and folder excluded from API processing, maintained as both a standalone document and a table in `archive.sqlite`.

### Per-Entry Fields

- `path` — SharePoint path of excluded file or folder
- `exclusion_reason` — enum (pastoral_care, individual_giving, medical, personnel, minor_involving, legal_active, denominational_confidential, corrupted, empty, system_junk, duplicate_of_retained, other)
- `exclusion_detail` — free-text explanation
- `excluded_by` — operator identifier
- `excluded_date` — timestamp
- `board_authorization` — reference to authorization if closed-matter exception applies
- `disposition` — enum (retained_in_place, moved_to_quarantine, deleted_with_board_approval)

### Review

The log is reviewed and signed off by the board at launch. Every exclusion is defensible by name and category. The log answers the future auditor's question ("why isn't the 1995 financial record in the archive") without requiring the operator to be present to explain.

Board review is of the aggregate log, not per-line approval. The operator exercises judgment within §3 and documents decisions; exceptions requiring explicit pre-action board authorization are limited to closed-matter handling of otherwise-excluded categories.

## 17. Prayer Concerns Policy (Draft)

Because prayer concerns appearing in bulletins contain named individuals with real health, family, or life circumstances — and because those individuals did not necessarily consent to having their situations preserved in a digital archive — the default handling of this data class is set explicitly rather than left to ad-hoc judgment.

This section is drafted as a proposed policy. It is presented to the pastor and board for review before the archive launches. The policy as written may be adjusted; what cannot be done is leaving the default undefined, because the extraction pass will produce these fields regardless and the first-launch governance posture will set precedent.

### Default Policy

**Retention:** Prayer concerns are retained in the archive as part of the institutional record of the church's care for its members.

**Audience restriction:** All prayer concerns regardless of age default to `audience_restriction_recommended = board`. This means the board and clergy can access them; general staff and congregants cannot.

**Age-based handling:**

- **Current liturgical year concerns** (same liturgical cycle as the launch date) are restricted to clergy-only access until the cycle closes, after which they move to standard board-level restriction. This protects actively live concerns from inadvertent exposure.
- **Concerns 10+ years old** are automatically summary-redacted in the extracted database: the *fact* that prayer was offered on a given date is preserved, but the identifying details are replaced with a generic descriptor ("prayers for a member's health," "prayers for a family loss"). The original bulletin files retain the original text; the database field is redacted. This allows historical liturgical research without exposing individual situations decades later.
- **Concerns 5–10 years old** are reviewed by the pastor on a sampling basis to determine whether individual cases warrant earlier summary-redaction (e.g., ongoing sensitive family situations).

**Deceased individuals:** The pastor may authorize retention of full-detail prayer concerns for named deceased individuals where the family has consented or where the individual is a matter of public church record (funeral, memorial service documentation).

**Opt-out:** Any individual or family may request that specific prayer concerns be summary-redacted regardless of age, via the pastor. The redaction is logged (with the request reference, not the concern content) in a separate confidential register.

### Rationale

The church's interest is institutional memory of its care for its members, not individual exposure. The archive should be able to answer "did we pray for people going through cancer in the 2010s" (yes, the pattern of care is preserved) without answering "who specifically was named in April 2014's bulletin" decades later. Summary redaction preserves the institutional record while respecting that people's circumstances change, families move, and consent from 2012 may not extend to a searchable 2026 archive.

### Questions for Pastoral Review

1. Is the 10-year automatic summary-redaction threshold appropriate, or should it be longer/shorter?
2. Is the clergy-only restriction on current-liturgical-year concerns appropriate, or does the current practice already assume broader access within the church staff?
3. Should the opt-out mechanism be announced to the congregation at launch, or introduced later (or at all)?
4. Are there categories of prayer concern (bereavement, specific illness, spiritual crisis) that warrant different handling than others?

### Adoption

Once the pastor and board have reviewed and adjusted this policy, the extraction pass is configured to apply it automatically. Adopted version is filed in `/Governance/Policies/` as `Prayer Concerns Archive Policy.pdf`.

## 18. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Core schema extraction quality is insufficient | 50-file sample run before full commit; schema tuning between sample and full run; extraction validation (§10.4) as hard gate |
| Model hallucinates document content or references | Evidence quotes required for Core claims; human review of low-confidence extractions and all sensitive-flag files; no destructive operations based on model output alone |
| First-impression failure at launch | Validation sample (§10.3 and §10.4) is 90% accuracy gate before archive is exposed to non-operator users; launch materials frame the archive as a new resource, setting expectations appropriately |
| Sensitive content accidentally sent to API | Formal Exclusion Policy (§3); Exclusion Log (§16); pre-flight manual sweep; pastoral review of Prayer Concerns Policy before extraction configures concern-handling |
| API costs overrun | Model routing; batch processing; pre-flight junk filtering; kill-switch threshold; per-batch progress monitoring |
| SharePoint operations behave unexpectedly | Sandbox sanity check before production run; complete pre-launch backup as rollback mechanism; moves_log as audit trail |
| Taxonomy pass exceeds context window | Haiku clustering sub-step produces bucket summaries; taxonomy operates on aggregate, not raw extractions |
| Vision downsampling fails on poor scans | Local legibility pre-check flags low-quality scans for high-res processing before Opus call |
| Successor cannot maintain the tool | Source Python preserved alongside executable; SQLite as primary data format; plain-text convention documentation; avoidance of trendy framework dependencies |
| Auto-approval category rules are wrong on first run | First 20 files of any auto-approved category manually spot-checked before bulk commit; errors reset the category to full manual review |
| Post-launch users file new documents using the old (nonexistent) conventions | One-page filing guide distributed at launch; `_Archive Notes.txt` at the root documents conventions; board announcement explicitly names the filing standard going forward |

---

## 19. Changelog

- **v1** — initial specification, drafted from conversational design
- **v2** — incorporated review feedback from three independent reviewers: SharePoint integration specified, exclusion policy formalized, schema tiered, model routing added, acceptance criteria made testable, rollback scoped honestly, communication plan added as deliverable
- **v3** — reframed as launch rather than migration after confirmation that the archive has no existing users. Architecture B removed; rollback simplified; change management rewritten as launch plan; schema fields added for contradiction and closure detection; folder-depth contradiction resolved; prayer-concerns handling elevated from open decision to draft policy for pastoral review; office hours replaced with digital feedback form

---

*v3 specification — ready for pastoral review (§17), board briefing, and implementation.*
