# Usability study: protocol and recording sheet

Sprint III asks for "completed testing and evaluation, including relevant
usability and failure scenarios, saved evidence, correction and retesting of
important defects". The automated suite covers whether functions work. It says
nothing about whether a person can use them, and the notes are explicit that
"a working function and a usable workflow are separate things to verify".

This is the instrument. Everything here is ready to run; what it needs is
participants and about ninety minutes.

> **Before recruiting anyone, ask Mrs Kirui whether Strathmore requires ethics
> clearance for this.** It involves human participants, and clearance takes
> weeks. Asking late is the one mistake that cannot be corrected later.

---

## What is being measured

Not opinions. Whether a person who has never seen the system can complete the
tasks it exists for, and where they hesitate.

| Measure | How |
|---|---|
| Task success | Completed unaided / completed with a hint / abandoned |
| Time on task | Stopwatch, started when the task is read out |
| Errors | Any action the participant undoes or that produces an error state |
| Points of confusion | Noted verbatim, in their words, not paraphrased |
| Perceived usability | System Usability Scale, ten items, at the end |

The System Usability Scale is used because it is short, standard and gives a
number comparable to published work. Ten questions, five-point agreement
scale, scored 0–100. It is a rough instrument and a small sample makes it
rougher, so it is reported with the sample size beside it and never alone.

---

## Participants

**Aim for five.** Five is the point at which additional participants mostly
repeat problems already found. Fewer than four is not worth writing up.

Who, in order of preference:

1. A radiographer or clinical officer. The intended user.
2. A medical student who has read chest films.
3. A final-year computing student who has not seen this project.

Record for each: role, years of experience, whether they have used any
AI-assisted tool before. Do not record names in the results.

**Do not use yourself, your supervisor, or anyone who has seen the system.**
They cannot be surprised by it, which is the whole point.

---

## Setup

- The deployed URL, signed out, on a laptop the participant controls.
- An account on the allowlist with the **radiographer** role.
- A second account with the **clinician** role, for task 5.
- Four radiographs on the desktop in a folder called `films`:
  - two clearly normal, two with visible abnormality, from the test split
  - one deliberately blurred, made with `--blur` below
  - one file that is not a radiograph at all, for task 6

Generate the blurred one:

```bash
.venv/Scripts/python.exe -c "import cv2, sys; i=cv2.imread(sys.argv[1]); cv2.imwrite('films/blurred.png', cv2.GaussianBlur(i,(31,31),0))" data/raw/montgomery/MontgomerySet/CXR_png/MCUCXR_0001_0.png
```

---

## What to say, and what not to

Read this out, once:

> "This is a prototype that helps screen chest X-rays for tuberculosis. I am
> testing the system, not you. If something is confusing, that is useful to me.
> Please say out loud what you are thinking as you go. I will not be able to
> help you until a task is finished, and that is not me being unhelpful."

Then, during the session:

- **Do not** explain what a button does, point at anything, or say "almost".
- **Do** say "what would you expect to happen?" when they pause.
- If they are stuck for **two minutes**, record it as a failed task, give the
  smallest possible hint, and continue.
- Silence is data. Let it run.

---

## Tasks

Read each aloud and start the stopwatch. Do not read the task name.

| # | Task | Read this out | Success means |
|---|---|---|---|
| 1 | Sign in | "Get into the system using this Google account." | Reaches the screening page |
| 2 | Screen one film | "A patient has had a chest X-ray. Find out whether this system thinks it suggests TB." | A result page with a score and triage level |
| 3 | Interpret | "What does this result tell you? What would you do next for this patient?" | Describes the triage level and that it needs clinical confirmation |
| 4 | Screen a batch | "Four more patients came in this morning. Screen them together." | All four submitted in one go |
| 5 | Review a case | "You disagree with one of these results. Record that." | Finds the review form, or correctly reports being unable to as a radiographer |
| 6 | Bad input | "Screen this file." *(hand them the non-radiograph)* | Understands it was refused and why |
| 7 | Find a case again | "Find the first patient you screened and tell me the score." | Locates it from the case list |

Task 5 is the role check. A radiographer **should** be refused. Record whether
they understand *why*, or whether they think the system is broken.

---

## Recording sheet

One per participant. Copy this table into `docs/usability-results.md`.

| # | Task | Outcome | Time | Errors | What they said |
|---|---|---|---|---|---|
| 1 | Sign in | ☐ unaided ☐ hinted ☐ failed | | | |
| 2 | Screen one film | ☐ unaided ☐ hinted ☐ failed | | | |
| 3 | Interpret | ☐ unaided ☐ hinted ☐ failed | | | |
| 4 | Screen a batch | ☐ unaided ☐ hinted ☐ failed | | | |
| 5 | Review a case | ☐ unaided ☐ hinted ☐ failed | | | |
| 6 | Bad input | ☐ unaided ☐ hinted ☐ failed | | | |
| 7 | Find a case again | ☐ unaided ☐ hinted ☐ failed | | | |

**Three questions at the end, before the scale:**

1. What did you expect the score to mean?
2. Was there anything you did not trust?
3. What would stop you using this in a real clinic?

Question 1 matters most. If participants read the model score as a probability,
that is a finding: the score is **not** calibrated, measured at ECE 0.1018, and
the interface has to make that clearer.

---

## System Usability Scale

Five-point scale, 1 strongly disagree to 5 strongly agree.

1. I think that I would like to use this system frequently.
2. I found the system unnecessarily complex.
3. I thought the system was easy to use.
4. I think that I would need the support of a technical person to be able to use this system.
5. I found the various functions in this system were well integrated.
6. I thought there was too much inconsistency in this system.
7. I would imagine that most people would learn to use this system very quickly.
8. I found the system very cumbersome to use.
9. I felt very confident using the system.
10. I needed to learn a lot of things before I could get going with this system.

**Scoring.** Odd items: score minus 1. Even items: 5 minus score. Sum, multiply
by 2.5. Result is 0–100 and is **not** a percentage. Around 68 is average;
below 50 indicates serious problems.

```bash
.venv/Scripts/python.exe -c "
r=[int(x) for x in input('ten answers, space separated: ').split()]
print('SUS', sum((v-1) if i%2==0 else (5-v) for i,v in enumerate(r))*2.5)"
```

---

## Afterwards

The notes are explicit that this is not finished at the point of measuring:
"Correct the important issues and retest."

1. List every problem observed, with how many of the five hit it.
2. Fix the ones two or more participants hit.
3. **Re-run the affected task** with at least one new participant.
4. Record the before and after in `docs/usability-results.md`.
5. Add any defect found to `docs/traceability.md` with its correction.

A study that finds problems and fixes none is weaker than no study at all,
because it documents that you knew.

## Reporting it

In Chapter 5, give: how many participants and who they were, task success per
task, median time, the problems found, what was changed, and the SUS score with
the sample size next to it. State plainly that five participants in a
non-clinical setting cannot establish usability in a real clinic — that is a
limitation, not a flaw, and the notes ask for exactly this kind of honesty
about "actual sample sizes, conditions and limitations".
