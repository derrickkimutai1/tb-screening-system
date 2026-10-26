# Using the system

For the people who will actually use it: radiographers who screen films and
clinicians who review the results. It assumes no knowledge of the software.

The deployment and setup instructions are in `deployment.md` and the README.
This document is about using the system once it is running.

---

## What this system does, and what it does not

It reads a chest radiograph and produces a **score between 0 and 1**, a
**result** of likely or unlikely TB, and a **triage level** of low, medium or
high suspicion. It stores every screening so it can be reviewed later.

It is a **screening aid**. It is not a diagnosis, it is not a medical device,
and it has not been clinically validated. Every result needs a clinician to
read the film and confirmatory testing before anything is decided about a
patient. The system says so on every result page, and that notice is not
decoration.

Two limits worth knowing before you rely on it:

- **It misses cases.** On the test set it found 54 of 59 TB radiographs. Five
  were missed. A low score is not a clearance.
- **It over-refers.** It flags about a third of healthy patients as suspicious.
  That is a deliberate trade: at the threshold the system runs at, catching TB
  matters more than avoiding a second look at someone healthy.

---

## Signing in

There are no passwords anywhere in this system, so there is none to forget or
leak.

1. Open the address your installation uses.
2. Either **Continue with Google**, or type your email address and choose
   **Continue with email**.
3. If you used email, a **six-digit code** arrives in your inbox. Enter it.

The first time you sign in you are asked for your name and your clinic. Your
**role** is not something you choose — an administrator sets it, because the
role decides who may record a clinical review.

| Role | Can screen | Can review |
|---|---|---|
| Radiographer | Yes | No |
| Clinician | Yes | Yes |
| Administrator | Yes | Yes |

You are signed out automatically after 30 minutes of inactivity, and when you
close the browser. On a shared machine, sign out when you step away.

---

## Screening a radiograph

**Screen** in the top navigation.

1. Enter a **case reference**. Use something that does not identify the
   patient, such as `DEMO-001` or a local accession number. Do not type a name.
2. Choose the radiograph. PNG, JPG or JPEG, up to 20 MB, and at least
   224 × 224 pixels.
3. Press **Analyse radiograph**. It takes a few seconds. The button disables
   itself so a second press cannot screen the same film twice.

**To screen several at once**, select more than one file — hold Ctrl or Shift
while choosing, up to 20. Each becomes its own case, with the reference you
typed and a number appended. If one image in a batch fails, the others still
go through and the page tells you which did not.

### If an image is refused

The system explains why rather than failing silently:

| What it says | What to do |
|---|---|
| Not a readable image | The file is corrupt or not really an image. Export it again. |
| Smaller than 224 × 224 | A thumbnail cannot be screened. Use the full radiograph. |
| Too large | Over 20 MB. Export at a lower resolution. |
| Appears blurred, darker or brighter than expected | This is a **warning, not a refusal**. The screening still runs, and the result carries the caution. Treat it with more care. |

---

## Reading a result

The result page shows the score as a gauge, the triage level with its
justification, and the thresholds the result was judged against.

**The score is not a probability.** It is the model's output. It is measurably
over-confident at the low end and under-confident at the high end, which is why
the interface calls it a *model score* and never a *confidence*. A score of
0.90 does not mean a 90% chance of TB.

| Triage | Meaning |
|---|---|
| High suspicion | Prioritise for clinical review and confirmatory testing |
| Medium suspicion | Review in the normal course |
| Low suspicion | Still a screening result, not a clearance |

### The explanation

Below the radiograph you will see a heatmap. It is built the first time
somebody opens the case, so on a new case the panel says it is building and
fills in after a few seconds.

**Bright areas are the regions the score depended on** — covering one of them
is what made the score fall. That is a statement about the model, not about
the patient. It is not a claim that disease is present there, and it should
never be shown to a patient as though it marks a lesion.

It localises weakly. On radiographs with hand-drawn lung masks it concentrates
on the lungs about 1.6 times more than chance. Better than nothing, and far
from a radiologist pointing at a shadow.

---

## The worklist

**Worklist** shows only what is still awaiting a decision, which is the
question somebody arriving for a shift actually has. The case list is an
archive; this is the queue.

Cases are ordered by urgency first and, within each level, by how long they
have waited. A case waiting a week or more has its waiting time marked. The
three counts across the top show the shape of the queue before any row does.

## Recording a review

Open a case and use the **Review** panel. Choose a status and write a note.

| Status | Use it when |
|---|---|
| Pending review | Nobody has decided yet |
| Reviewed | You have read it and no follow-up is needed |
| Follow-up required | The patient needs confirmatory testing or referral |

Your name and the time are recorded automatically. Notes are **append-only** —
a note cannot be edited or deleted once saved, because a clinical record that
can be quietly changed is not a record. Correct a mistake by adding another
note.

If you are a radiographer the form is not shown, and the system refuses a
review even if the request is sent directly. That is deliberate: confirming or
dismissing a case is a clinical judgement.

---

## Finding and exporting cases

**Cases** lists everything screened at your clinic, newest first. Filter by
case reference or triage level.

**Export CSV** downloads what you are currently looking at, filters included —
not the whole database. Every export is recorded in the access trail, because
a bulk download of clinical records is worth knowing about.

**Print report** on any case produces a one-page document for a patient file or
a referral. Your browser's print dialogue will also save it as a PDF; nothing
else needs installing. It carries the result, the clinical boundary, both
images, any prior screenings of the same reference, the review notes, and who
printed it and when.

## Earlier screenings of the same patient

A case shows prior screenings that share its reference, so on a repeat film you
can see whether the score has moved. Matching ignores capitals, so `DEMO-001`
and `demo-001` are the same patient. It does **not** cross clinics: the same
reference at another clinic is a different patient.

---

## What other people can see

Records belong to a **clinic**, not to the person who uploaded them, because a
radiographer screens and a clinician reviews. Everyone at your clinic sees the
same caseload. Nobody outside it sees anything — a case at another clinic is
reported as not found rather than refused, so the system does not confirm it
exists. The radiographs and heatmaps themselves are protected the same way;
having the address is not enough.

If your account has no clinic set, you see nothing rather than everything. Ask
an administrator to set it.

### The access trail

Every view, list, review, refusal and export is recorded with who, what, when,
and from where. Each entry is sealed against the one before it, so an altered
or deleted entry breaks the chain and can be detected. An administrator can
check it with `manage.py verifyaudit`.

---

## Privacy

Use a non-identifying case reference, and **do not upload images with patient
identifiers burned into them**. The system strips camera metadata — including
GPS coordinates, which a photographed film can carry — before storing anything,
but it cannot remove a name printed into the pixels.

The system stores your name and email address and nothing else about you. It
never receives a password.

---

## When something goes wrong

| What you see | What it means |
|---|---|
| The explanation says it could not be produced | The screening is still valid. The map failed; the score did not. |
| The explanation panel sits on "building" | Reload the page. If it had already finished, the image appears. |
| "Your role does not permit recording a review" | You are a radiographer. A clinician has to make the decision. |
| A case you expected is not there | It belongs to another clinic, or your account has no clinic set. |
| Signed out unexpectedly | Thirty minutes of inactivity, or the browser was closed. |

If a result looks wrong, record a review note saying so. That note is part of
the permanent record and is the right place for it.
