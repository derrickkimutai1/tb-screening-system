# Deploying to Azure Container Apps

Sprint III asks for "a working operational release, accessible through HTTPS
where applicable, with the actual backend, database, model or devices
connected". This is how that release is produced.

## Why not Hugging Face

The Build Phase notes give Hugging Face as Example 3, and this repository was
built for it: a Dockerfile, a Space header and a sync workflow all exist and
still work. On 2 November 2026 Hugging Face's pricing page listed "Host
ZeroGPU, Gradio & Docker Spaces" as a PRO benefit at $9 per month. A free
account may create a Static Space only, which serves files and cannot run
Django or load a model.

The notes anticipate this on page 22: "Membership alone does not establish free
PRO access or unlimited GPUs. Ask its administrator or university IT to confirm
the actual plan, quota, billing and permitted use before provisioning a Space."
The Strathmore organisation `SU-students-ai-321` was checked on the same date:
one member, no models, no datasets, no Spaces, and no paid-plan badge.

The notes also name the alternative: "The Student Developer Pack includes
selected cloud offers, such as Azure credit, which may support an alternative
deployment agreed with your supervisor." That is the route taken here. The
container is unchanged; only the host differs. `docs/deployment.md` is kept
because it remains correct if the organisation later has a plan.

## What it costs

Azure for Students gives $100 of credit on a school email with no credit card.
Azure Container Apps bills by the second, and its published free grant is the
first 180,000 vCPU-seconds, 360,000 GiB-seconds and 2 million requests per
subscription per month, with no charge at all while an app is scaled to zero.

At the size this app runs (1 vCPU, 2 GiB) that grant is about fifty hours of
real traffic a month. A demonstration and a marking session use minutes of it.

Scaling to zero is what keeps it free, and it is also why the first visit after
a quiet period is slow. Keeping one replica running permanently would cost
roughly $70 a month and would exhaust the credit in about five weeks, so it is
done for a demonstration and undone afterwards. Both commands are printed by
the setup script.

## What is already in the repository

| File | What it does |
|---|---|
| `Dockerfile` | Two-stage build; the trained model is inside the image, so a prediction never fetches a model at run time. Listens on `$PORT`, defaulting to 7860. |
| `deploy/entrypoint.sh` | Applies migrations, then starts gunicorn with one worker and four threads. |
| `deploy/azure-setup.sh` | Creates the resource group, environment and application in one run, from Azure Cloud Shell. |
| `.github/workflows/publish-image.yml` | Builds the image after the tests pass on `main` and publishes it to GitHub's registry, tagged with the commit. |
| `screening/views.py:health` | `GET /health/` answers 200 only when the database responds **and** the model has loaded. |

---

## Step 1 - The database

A container has no durable disk, so the database lives elsewhere.

1. Open <https://neon.tech> and sign up.
2. Create a project named `tb-screening`, region Frankfurt.
3. Copy the connection string. It is a password; treat it as one.

## Step 2 - Email for the sign-in codes

Without a mail provider, nobody but you can create an account, because the
six-digit code is never delivered.

1. <https://myaccount.google.com/security> - turn on 2-Step Verification.
2. <https://myaccount.google.com/apppasswords> - create one named `TB Screening`.
3. Copy the sixteen characters and remove the spaces.

## Step 3 - Publish the image

1. GitHub, **Actions**, **publish image**, **Run workflow** on `main`.
2. Wait for it. The first build installs TensorFlow and is slow; later ones
   reuse the cache.
3. GitHub, the repository front page, **Packages**, the new package,
   **Package settings**, **Change visibility**, **Public**.

A public image can be pulled without credentials, which is what keeps the
hosting free of a container registry bill and of a second secret to manage.

Note the full image name the workflow prints, for example
`ghcr.io/derrickkimutai/tb-screening-system:8a4c1f2b9d33`.

## Step 4 - Create the hosting

1. <https://azure.microsoft.com/en-us/free/students>, **Start free**, sign up
   with the university address. No card is asked for.
2. <https://portal.azure.com>, the terminal button in the top bar opens Cloud
   Shell. Choose **Bash** if it asks.
3. Upload `deploy/azure-setup.sh` with the upload button in the Cloud Shell
   toolbar, or paste its contents into a new file.
4. Generate a secret key for the deployment, on the laptop, and keep it ready:

   ```bash
   .venv/Scripts/python.exe -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
   ```

   It must not be the key in the local `.env`.

5. Run it:

   ```bash
   bash azure-setup.sh
   ```

   It asks for the image name, the Neon string, the secret key, the Google
   client id and secret, the sending address and the app password. Nothing is
   created until every answer is given, and the secrets are typed blind rather
   than echoed.

It prints the address when it finishes, and waits until `/health/` answers
before saying so.

## Step 5 - Tell Google the new address

Sign-in fails with `redirect_uri_mismatch` until this is done.

1. <https://console.cloud.google.com/apis/credentials>, the OAuth client.
2. **Authorised redirect URIs**, **Add URI**, the address the script printed
   followed by `/accounts/google/login/callback/`.
3. Keep the `localhost` one, or local development breaks.
4. **Save**, and add Mrs Kirui to the consent screen's test users.

## Step 6 - Verify, and record the evidence

```bash
curl https://THE-ADDRESS/health/
```

Expect `{"status": "ready", "checks": {"database": "ok", "model": "tb_mobilenetv2_v1"}}`.

Then confirm each of these in a browser and keep a screenshot:

- [ ] The sign-in page loads over HTTPS.
- [ ] Google sign-in completes and lands on the screening page.
- [ ] A new address registers and receives its code **by email**.
- [ ] The development code banner is absent.
- [ ] A radiograph uploads, scores and stores a record.
- [ ] A batch of several images reports per-image outcomes.
- [ ] An unusable image is refused with a specific reason.
- [ ] The explanation panel says it is building, then shows the heatmap.
- [ ] Opening the case again does not rebuild it.
- [ ] A radiographer cannot record a review; a clinician can.
- [ ] The model page shows the architecture comparison.
- [ ] Signing out makes the pages unreachable again.

Record the address, the deployed commit, the model version and the date. The
Build Phase notes ask for exactly those four.

## Releasing a change

Push to `main`. When the tests pass the image is rebuilt and published under
the new commit's tag, and if automatic deployment is set up below, the running
application is pointed at it without anything else being typed.

By hand, which is also how a rollback is done:

```bash
az containerapp update --name tb-screening --resource-group tb-screening --image ghcr.io/OWNER/REPO:NEWTAG
```

Keeping the previous tag is what makes that rollback possible: the same command
with the old tag puts it back.

## Deploying automatically

Off until switched on. The `deploy` job in `publish-image.yml` is gated on a
repository variable, so before this is done it is skipped rather than failing,
and a fork of this repository does not collect a red cross on every push for a
subscription it has no business reaching.

Publishing and deploying stay separate jobs on purpose. An image that exists is
useful on its own: it can be deployed by hand, rolled back to, or pulled by
somebody else, and none of that should depend on this repository holding
credentials for one subscription.

**1. Make a credential that can change this one application.** In Cloud Shell,
with your own subscription id:

```bash
az ad sp create-for-rbac --name tb-screening-deploy --role contributor \
    --scopes /subscriptions/SUBSCRIPTION_ID/resourceGroups/tb-screening --sdk-auth
```

Scoped to the resource group and no wider, so a leaked credential can change
this deployment and nothing else in the subscription. It prints a block of
JSON. That JSON is a password.

If the command is refused, the university tenant does not allow creating
service principals. Deploy by hand in that case; nothing else here depends on
it.

**2. Give it to GitHub.** Repository **Settings**, **Secrets and variables**,
**Actions**:

| Tab | Name | Value |
|---|---|---|
| Secrets | `AZURE_CREDENTIALS` | the whole JSON block, braces included |
| Variables | `AZURE_DEPLOY` | `true` |
| Variables | `AZURE_HEALTH_URL` | `https://THE-ADDRESS/health/` |

`AZURE_APP_NAME` and `AZURE_RESOURCE_GROUP` are variables too, and default to
`tb-screening` if absent.

**3. Push something.** The workflow builds, deploys, and then polls `/health/`
until the application answers 200, because a deployment command returning
successfully is not evidence that anything works: the first revision of this
application answered HTTP 400 to every request while reporting itself Running.
If the health check never passes, the job fails and says so rather than leaving
a broken release looking green.

## Known limitations of this deployment

**Uploads do not survive a restart.** The database is external and durable; the
radiographs and heatmaps are written inside the container, which keeps nothing
across a restart or a scale to zero. A record outlives its image, and the case
page says so rather than failing. Fixing this needs object storage, which the
Build Phase notes also say: "container-local storage is not the project's
permanent record."

**The first request after a quiet period is slow.** The app scales to zero to
stay inside the free grant, so a cold visit waits for the image to start and
TensorFlow to load. Warm it before a demonstration with the command the setup
script prints.

**One replica.** The model is held per process and is most of the memory, so a
second replica would double the footprint for no gain. Concurrent uploads
queue.

**Credit and lifetime.** Azure for Students is $100 for twelve months and is
renewed while you remain a student. Record the expiry and keep the deployment
reachable for as long as assessment requires.
