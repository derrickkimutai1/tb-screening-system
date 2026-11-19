# Security policy

The posture this system was built to, control by control, with the file that
implements each one named so a reader can check rather than take it on trust.

It also states what the system does **not** do. A policy that lists only the
controls present is a sales document; the gaps at the end are the part worth
reading before anyone deploys this near a patient.

---

## 1. What is being protected, and under what law

The system holds chest radiographs, a patient reference chosen by the clinic,
a model score and a clinical decision. Under the **Data Protection Act 2019**
(Kenya) a radiograph tied to a patient reference is personal data, and health
data is sensitive personal data under section 2. A system holding it is
therefore a data processor acting for the facility that operates it, and the
facility is the data controller.

Two classifications apply at once and pull in different directions:

- **PII / sensitive personal data** — minimise, restrict, delete when no longer
  needed.
- **Critical information infrastructure** — a tuberculosis screening service a
  facility depends on is availability-critical, which argues for redundancy and
  retention.

Where they conflict this system favours minimisation, except for the audit
trail, which is retained deliberately (section 5).

---

## 2. Trust zones

Stated honestly: this is **application-layer segmentation, not network-layer
micro-segmentation.** The boundaries below are enforced in code and in the
platform, not by firewalls between subnets.

| Zone | Contents | Boundary into it |
|---|---|---|
| Public | Sign-in pages, health endpoint | Anonymous. Serves no clinical data |
| Session | Every clinical view | `@login_required`, session cookie, 30-minute idle expiry |
| Clinic | One facility's caseload | `visible_to()` scopes every query by facility |
| Decision | Recording a clinical review | Role check on the POST, not on the template |
| Administration | Accounts, roles, facilities | Administrator role; Django staff flag for the framework admin |
| Stored images | Radiographs and heatmaps | `protected_media`, never served from the document root |
| Secrets | Database credentials, signing key, OAuth secrets | Process environment; never in the source tree |

**Least privilege is the organising rule.** A radiographer can screen and read
but not decide. A clinician can decide. An administrator can manage people but
**cannot alter a model result or edit the audit log** — `AccessEventAdmin`
hard-codes `has_add_permission` and `has_change_permission` to `False`, and
`PredictionRecordAdmin` marks twenty-one output fields read-only. The most
privileged account in the installation cannot falsify what the system recorded.

**Deny by default.** A user with no facility set sees only records that also
have none, so an account that appears from nowhere sees an empty system rather
than a clinic's caseload (`PredictionRecordQuerySet.visible_to`).

---

## 3. Identity and access

**No password exists anywhere in the system.** There is nothing to phish,
reuse, leak in a dump, or store badly. Three routes in, all through
django-allauth:

- a six-digit code emailed to the address, valid 5 minutes, 3 attempts
  (`ACCOUNT_LOGIN_BY_CODE_*`)
- Google
- GitHub

Accounts created by an administrator are given an unusable password
explicitly, so the absence is a property of the system rather than an
oversight.

Where a user signs in with Google or GitHub, **whatever multi-factor
authentication they hold on that account applies here.** The system does not
implement TOTP itself (section 9).

**Roles are never self-awarded.** `SELECTABLE_ROLES` is derived by excluding
administrator from the model's choices rather than by listing the two clinical
roles, so a role added later is offered without this being remembered and the
one exclusion stays exact. The administrator role is granted from a single
address in `ADMINISTRATOR_EMAIL`, or by an existing administrator.

**The role is re-chosen at every sign-in**, because one person covers both
clinical jobs on different days, and a screening should carry the role its
author actually held. The choice is written to the access trail.

**Sessions** expire after 30 minutes of inactivity and do not survive the
browser closing, chosen against the ONC and CMS automatic log-off criteria.

---

## 4. Data protection and minimisation

**EXIF and GPS metadata are stripped from every upload before storage**
(`screening/services/sanitise.py`). A phone-photographed radiograph can carry
the coordinates of the room it was taken in; a screening system has no need of
them. The image is re-encoded rather than edited, so a file that merely looks
like an image does not survive the process.

**Stored files carry no patient identifier.** An upload is written to
`uploads/<year>/<month>/<case-uuid>.<ext>`. Not the original filename, which
could contain a name; not the patient reference, which would put an identifier
in the filesystem; not a serial number, which would be enumerable and would
leak case volume. The name is a random UUID and reveals nothing.

**Images are not reachable by URL.** `protected_media` resolves the path,
refuses anything climbing out of the media root, derives the case from the
filename and applies the same visibility rule as the case page. A file that
does not resolve to a visible record returns 404 rather than 403, because a
403 would confirm the case exists.

**Subject rights.** A machine-readable export of a user's own data
(`export_my_data`) and account closure (`delete_my_account`), both stating
their limits on the page: the export excludes the radiographs, and closing an
account does not delete clinical records or audit rows. A screening is a
record of a patient held by the clinic, not the operator's to erase.

**Deletion preserves attribution.** Every link from a record to a person is
`SET_NULL` with the name retained as text, so removing an account breaks the
link without erasing who did the work. Deactivation is preferred to deletion
for exactly this reason.

**Cross-border transfer.** The hosted deployment runs in Azure South Africa
North, outside Kenya. Section 48 of the Act conditions transfers abroad. The
position taken here: **the hosted instance carries no patient data.** It is a
demonstration of the running system. Where real clinical data is involved the
packaged Windows build is the intended deployment — it runs with no network
connection at all, keeping radiographs inside the facility, and binds to
`127.0.0.1` only so the application is not reachable from the network.

---

## 5. Audit and accountability

Every view, list, screening, review, refusal, export and account change is
recorded with the actor, the action, the facility, the case, the IP address and
the user agent.

**The log is hash-chained.** Each row hashes its own contents together with the
hash of the row before it, joined on an ASCII unit separator so no field can
contain the delimiter. Altering a row or removing one from the middle breaks
every hash after it. Verified from a button in the interface and from
`manage.py verifyaudit`, which exits non-zero so it can be scheduled rather
than read.

**The chain is what makes this evidence rather than a list**, and the interface
says plainly that it detects alteration rather than preventing it.

Refused attempts are recorded, not only successful ones. A clinician POSTing
an account-management endpoint receives a 403 **and** leaves a row behind.

Audit rows are retained when an account closes, deliberately: a log that a
departing member of staff could empty would answer nothing.

---

## 6. Application and transport hardening

Enabled whenever `DEBUG` is off, so the development machine is not the thing
being described:

| Control | Setting |
|---|---|
| HTTPS enforced | `SECURE_SSL_REDIRECT`, health endpoint exempt for probes |
| HSTS | `SECURE_HSTS_SECONDS`. `includeSubDomains` and `preload` are **refused on purpose**: the application runs on a shared platform domain, where the first would speak for every sibling on it and the second is close to irreversible. Both deployment-check warnings are silenced with that reasoning written beside them, rather than left to be scrolled past |
| Secure cookies | `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` |
| Session cookie not readable by script | `SESSION_COOKIE_HTTPONLY` |
| No MIME sniffing | `SECURE_CONTENT_TYPE_NOSNIFF` |
| No framing | `X_FRAME_OPTIONS = "DENY"` |
| Referrer limited | `SECURE_REFERRER_POLICY = "same-origin"` |
| Host header checked | `ALLOWED_HOSTS` from the environment |
| CSRF on every form | `CsrfViewMiddleware` |

**Upload validation** runs before anything else touches the file: the
extension and a size ceiling (`MAX_UPLOAD_BYTES`) in the form, then a decode
through Pillow and a 224-pixel minimum edge in the quality checker
(`MINIMUM_EDGE`). Content hashing in the browser and again on the server stops
the same film being screened twice under two names.

**CSV export escapes formula leaders** (`=`, `+`, `-`, `@`, tab, carriage
return), so an exported field cannot execute when the file is opened in a
spreadsheet.

---

## 7. Secrets

`SECRET_KEY` is read from the environment with no fallback — `os.environ[...]`
rather than `.get()`, so a deployment missing it fails to start instead of
running on a default. Database credentials, the mail password and both OAuth
client secrets are environment variables. `.env` is in `.gitignore` and has
never been committed, and `detect-private-key` runs as a pre-commit hook on
every commit.

---

## 8. Deployment modes

| Mode | Boundary | Clinical data |
|---|---|---|
| **Hosted** (Azure Container Apps) | HTTPS, managed PostgreSQL, secrets in platform configuration | Demonstration only |
| **Packaged** (Windows, offline) | Binds `127.0.0.1`; no network required; data under `LOCALAPPDATA` | Intended mode for real use |

In the packaged build a local operator is signed in automatically by
`PackagedOperatorMiddleware`, so **the security boundary is the machine, not
the application.** That is a deliberate trade for a single-workstation clinic
with no network, and it is stated here rather than discovered later. Anyone
deploying it must treat physical access to that workstation as full access to
the caseload.

---

## 9. What this policy does not claim

The honest half.

- **No network-layer micro-segmentation.** The hosted deployment is one
  container application and one managed database. There are no separate
  subnets, no service mesh, no per-zone firewall rules. The segmentation in
  section 2 is enforced in application code and would not survive an attacker
  who reached the database directly.
- **No multi-factor authentication of the system's own.** Possession of an
  email inbox is a single factor. Users signing in through Google or GitHub
  inherit whatever MFA they hold there, which is not the same as the system
  requiring it.
- **No automated retention.** Nothing deletes old radiographs on a schedule.
  `manage.py prunemedia` removes files no record points at, which is a
  different problem. A retention rule is outstanding work.
- **The audit trail detects alteration; it does not prevent it.** Someone with
  database access can rewrite rows and recompute the chain. Tamper-evident is
  not tamper-proof, and the interface says so.
- **Open registration is enabled in the demonstration deployment.** Any address
  can register. A clinical deployment sets `SIGN_IN_OPEN_REGISTRATION=False`
  together with `SIGN_IN_ALLOWED_EMAILS` or `SIGN_IN_ALLOWED_DOMAINS`, both of
  which the system supports and tests.
- **No penetration test, no formal threat model, no data protection impact
  assessment.** The controls here were derived from the requirements and the
  course guidance, not from an adversarial review.
- **No encryption at rest beyond what the platform provides.** Azure encrypts
  managed storage; the packaged build writes to an ordinary folder on the
  operator's disk.

---

## 10. Before a real deployment

In order:

1. Close registration and set an allowlist.
2. Agree a retention period with the facility and implement it.
3. Run the system against a Kenyan population before trusting any of its
   numbers — see the cross-dataset result in `docs/what-measuring-found.md`.
4. Commission an independent review. Nothing here substitutes for one.
