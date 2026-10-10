# Product backlog and sprint tasks

Tasks are grouped under the specific objectives they serve, from Chapter 1 of the
proposal. Status is one of done, in progress, or to do.

Objectives, in short:

1. Analyse the current TB screening process from chest X-rays in resource-constrained settings
2. Study existing computer-aided detection systems and identify their strengths and limitations
3. Identify gaps in explainability, image quality handling, triage support and record keeping
4. Develop a web-based system that screens chest X-rays and shows the confidence score, triage level, Grad-CAM heatmap, image quality warning and clinician notes
5. Test and evaluate the system using model performance metrics and system testing

---

## Sprint 1 — Data preparation and development environment

| Task | Objective | Status |
|---|---|---|
| Configure the development environment and pin dependencies | 4 | Done |
| Set up PostgreSQL and the database schema | 4 | Done |
| Establish Git version control with meaningful commits | 4 | Done |
| Acquire and verify the Montgomery and Shenzhen datasets | 5 | Done |
| Inspect images for corruption and duplicates | 5 | Done |
| Produce a stratified train, validation and test split | 5 | Done |
| Automate checks on commit and on push | 4 | Done |
| Revise proposal content into project documentation | 1, 2, 3 | **To do** |

## Sprint 2 — Core functionality, integration and initial testing

| Task | Objective | Status |
|---|---|---|
| Shared preprocessing module used by training and the application | 4 | Done |
| Train a baseline MobileNetV2 classifier | 4 | Done |
| Compare training variants and record the experiments | 5 | Done |
| Choose decision and triage thresholds from validation evidence | 4 | Done |
| Evaluate once on the held-out test split with confidence intervals | 5 | Done |
| Implement Grad-CAM and overlay it on the radiograph | 4 | Done |
| Implement image quality checking with OpenCV | 4 | Done |
| Implement triage levels with written justifications | 4 | Done |
| Integrate the model into the Django upload workflow | 4 | Done |
| Store predictions, heatmaps and quality data in PostgreSQL | 4 | Done |
| Test the implemented functionality and record the results | 5 | Done |
| Update Chapter 5 and the Chapter 4 diagrams | 1, 2, 3 | **To do** |
| Produce wireframes, proposal section 3.6.2 | 4 | **To do** |

## Sprint 3 — Completion and deployment

| Task | Objective | Status |
|---|---|---|
| Improve specificity; it is 50.8 per cent against a 70 per cent target | 4, 5 | To do |
| Measure Grad-CAM activation inside the lungs using Montgomery's masks | 3, 5 | To do |
| Cross-dataset evaluation: train on Shenzhen, test on Montgomery | 5 | To do |
| Error analysis of false positives and false negatives | 5 | To do |
| Usability evaluation with participants | 5 | To do |
| Identify hosting requirements and deploy | 4 | To do |
| Package a downloadable desktop build | 4 | To do |

---

## Issues affecting delivery

**Specificity is the main technical risk.** At 50.8 per cent the system refers about half
of healthy patients for confirmatory testing. The sensitivity target is met, but this
balance would be impractical in a real clinic. Improving it is the first priority of
Sprint 3.

**The dataset is small and not Kenyan.** 800 images from the United States and China
limit both achievable performance and generalisability to the target population. This is
stated as a limitation rather than treated as solvable within the project.

**Documentation is behind the code.** Chapters 4 and 5 have not been updated to match
what has been implemented. This is the largest outstanding item and does not depend on
further development.
