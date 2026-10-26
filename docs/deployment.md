# Deploying to a Hugging Face Space

Sprint III asks for "a working operational release, accessible through HTTPS
where applicable, with the actual backend, database, model or devices
connected". This is how that release is produced.

The route is Example 3 from the Build Phase notes: Hugging Face. A Docker Space
runs the whole application — Django, the trained model and the screening
pipeline — behind HTTPS that Hugging Face terminates. The database is hosted
separately, because a Space has no durable disk.

Everything in this repository is already done. What remains is three accounts
and about twenty minutes of clicking, none of which can be done on your behalf
because each step signs in as you.

---

## What is already in the repository

| File | What it does |
|---|---|
| `Dockerfile` | Two-stage build. Installs TensorFlow in the first stage and copies the result into a clean runtime image, so the compilers never ship. Runs as an unprivileged user on port 7860. |
| `deploy/entrypoint.sh` | Applies migrations, then starts gunicorn with one worker and four threads. |
| `deploy/space-header.md` | The YAML header a Space needs at the top of its README. Prepended during deployment so the project README stays clean. |
| `.github/workflows/deploy-space.yml` | Pushes to the Space after the test suite passes on `main`, then polls `/health/` until the Space answers. |
| `.dockerignore` | Keeps the datasets, checkpoints, notebooks and `.env` out of the image. |
| `screening/views.py:health` | `GET /health/` reports 200 only when the database answers **and** the model has loaded. 503 otherwise. |

The container carries the trained model. The deployment guidance is explicit
that a prediction must not fetch an unspecified latest model, so the weights are
fixed at build time and the image is the release.

---

## Step 1 — A database that outlives the container

A Space has no persistent disk. Anything written inside it is gone when it
restarts, so the database has to live elsewhere.

**Neon** has a free Postgres tier that suits this.

1. Open <https://neon.tech> and sign up.
2. Create a project. Name it `tb-screening`. Pick the region closest to you.
3. Copy the connection string it shows. It looks like:

   ```
   postgresql://user:password@ep-something.eu-central-1.aws.neon.tech/neondb?sslmode=require
   ```

4. Keep it. It is a password; treat it as one.

`config/settings.py` reads `DATABASE_URL` when it is set and falls back to the
five separate `DB_*` variables otherwise, so your local setup is unaffected.

---

## Step 1b — Somewhere to send the sign-in codes

Registration is open: anyone enters an address and receives a six-digit code.
Without a mail provider nothing is delivered, so **no one but you can create an
account**. In development the code appears on the confirmation page instead,
which is enough to work with and is switched off the moment either `DEBUG` is
off or `EMAIL_HOST` is set.

Pick one. Both are free at this volume.

### Gmail, about three minutes

Only works if your Google account has 2-Step Verification on; Google stopped
accepting account passwords for SMTP.

1. <https://myaccount.google.com/security> → turn on **2-Step Verification** if
   it is off.
2. <https://myaccount.google.com/apppasswords> → create one named
   `TB Screening`. Google shows sixteen characters. Copy them.
3. Set these:

   ```
   EMAIL_HOST=smtp.gmail.com
   EMAIL_PORT=587
   EMAIL_HOST_USER=derrick.kim46@gmail.com
   EMAIL_HOST_PASSWORD=the sixteen characters, spaces removed
   EMAIL_USE_TLS=True
   DEFAULT_FROM_EMAIL=TB Screening <derrick.kim46@gmail.com>
   ```

An app password is not your Google password and can be revoked on its own. It
still grants access to send as you, so it belongs in `.env` and in the Space's
secrets, never in the repository.

Gmail allows roughly 500 messages a day, which is far more than this needs.
Messages may land in spam, because they come from a personal address with no
sending reputation.

### Brevo or Resend, about five minutes

Better if you want mail that is less likely to be filtered, and it does not
attach your personal Google account to the project.

1. Sign up at <https://www.brevo.com> or <https://resend.com>.
2. Create an SMTP key.
3. Use the host, port and credentials they give you, with the same five
   variables above.

### Checking it works

```bash
.venv/Scripts/python.exe manage.py shell -c "from django.core.mail import send_mail; send_mail('TB Screening test', 'If you are reading this, mail works.', None, ['your.address@example.com']); print('sent')"
```

If that arrives, the sign-in codes will too. If it raises, the error names the
problem: authentication failures mean the app password is wrong, timeouts mean
the port or TLS setting is.

---

## Step 2 — Create the Space

1. Open <https://huggingface.co> and sign up, or sign in.
2. **Before anything else, ask Mrs Kirui about `SU-students-ai-321`.** The Build
   Phase notes name a Strathmore organisation on Hugging Face and say membership
   needs your supervisor's and the administrator's agreement. A Space in the
   organisation stays reachable after your personal account stops being the
   point of contact, which is what the notes mean about continuity. If the
   answer is slow, create it under your own account and move it later rather
   than waiting.
3. **New** → **Space**.
   - **Owner**: the organisation if you have it, otherwise your username.
   - **Space name**: `tb-screening-system`
   - **License**: MIT
   - **SDK**: **Docker** → **Blank**
   - **Hardware**: CPU basic, the free option.
   - **Visibility**: Public, unless the supervisor asks otherwise.
4. **Create Space**. It will be empty. The workflow fills it.

Note the full name, `owner/tb-screening-system`. You need it twice below.

---

## Step 3 — Give GitHub permission to push

1. Hugging Face → your avatar → **Settings** → **Access Tokens** → **Create new
   token**. Type **Write**. Name it `github-deploy`. Copy it.
2. GitHub → your repository → **Settings** → **Secrets and variables** →
   **Actions**.
3. **Secrets** tab → **New repository secret**:
   - Name `HF_TOKEN`, value the token from step 1.
4. **Variables** tab → **New repository variable**:
   - Name `HF_SPACE`, value `owner/tb-screening-system`.

A secret is hidden after saving; a variable is not. The token is a secret and
the Space name is not, which is why they go in different places.

---

## Step 4 — Configure the Space

Hugging Face → your Space → **Settings** → **Variables and secrets**.

Add these as **secrets**:

| Name | Value |
|---|---|
| `DJANGO_SECRET_KEY` | A fresh random key. **Not** the one in your local `.env`. Generate one with the command below. |
| `DATABASE_URL` | The Neon connection string from step 1. |
| `GOOGLE_OAUTH_CLIENT_ID` | From your Google Cloud console. |
| `GOOGLE_OAUTH_CLIENT_SECRET` | From your Google Cloud console. |
| `EMAIL_HOST_PASSWORD` | The app password or SMTP key from step 1b. |

Add these as **variables**, substituting your Space's host:

| Name | Value |
|---|---|
| `DJANGO_ALLOWED_HOSTS` | `owner-tb-screening-system.hf.space` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://owner-tb-screening-system.hf.space` |
| `DJANGO_SITE_DOMAIN` | `owner-tb-screening-system.hf.space` |
| `SIGN_IN_ALLOWED_EMAILS` | leave empty to admit anyone |
| `SIGN_IN_OPEN_REGISTRATION` | `True` to let visitors register, `False` to admit only known addresses |
| `EMAIL_HOST` | `smtp.gmail.com`, or your provider's |
| `EMAIL_PORT` | `587` |
| `EMAIL_HOST_USER` | the sending address |
| `DEFAULT_FROM_EMAIL` | `TB Screening <your.address@example.com>` |

The host is the Space name with the slash turned into a hyphen and everything
lowercased. `derrickkimutai1/tb-screening-system` becomes
`derrickkimutai1-tb-screening-system.hf.space`.

Generate the secret key:

```bash
.venv/Scripts/python.exe -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

A deployed site must not share a key with a development machine. If the local
key leaks from a laptop, the deployment should be unaffected.

---

## Step 5 — Tell Google about the new address

Sign-in will fail with `redirect_uri_mismatch` until this is done.

1. <https://console.cloud.google.com/apis/credentials> → your OAuth client.
2. Under **Authorised redirect URIs**, **Add URI**:

   ```
   https://owner-tb-screening-system.hf.space/accounts/google/login/callback/
   ```

3. **Keep the localhost one.** Removing it breaks local development.
4. **Save.** Google can take a few minutes to apply the change.
5. Add any address that needs to sign in to the consent screen's **test users**,
   including your supervisor's.

---

## Step 6 — Deploy

Push to `main`, or run it by hand: GitHub → **Actions** → **deploy to hugging
face** → **Run workflow**.

The workflow waits for the test suite to pass, pushes the tree to the Space,
then polls `/health/` for up to twenty minutes. The first build installs
TensorFlow and is slow; later builds reuse cached layers.

Watch the build at `https://huggingface.co/spaces/owner/tb-screening-system`
under **Logs** → **Build**, then **Container**.

---

## Step 7 — Verify, and record the evidence

Sprint III asks for a release that has been checked, not merely one that exists.

```bash
curl https://owner-tb-screening-system.hf.space/health/
```

Expect `{"status": "ready", "checks": {"database": "ok", "model": "tb_mobilenetv2_v1"}}`.

Then, in a browser, confirm each of these and keep a screenshot:

- [ ] The sign-in page loads over HTTPS and reports **Ready**.
- [ ] Google sign-in completes and lands on the screening page.
- [ ] A new address can register, receives a code **by email**, and gets in.
- [ ] The development code banner is **absent**, because DEBUG is off there.
- [ ] An address outside the allowlist is refused with the system's own message.
- [ ] A radiograph uploads, previews, scores, and stores a record.
- [ ] A batch of several images screens and reports per-image outcomes.
- [ ] A deliberately unusable image is rejected with a specific reason.
- [ ] The explanation panel on a case nobody has opened says it is building, then shows
      a heatmap within a few seconds without reloading the page.
- [ ] Opening that case a second time shows the map immediately and does not rebuild it.
- [ ] A radiographer cannot record a review; a clinician can.
- [ ] The dashboard counts match the case list.
- [ ] Signing out returns to the gate and the pages are no longer reachable.

Record the Space URL, the deployed commit, the model version and the date. The
Build Phase notes ask for exactly that, and it is what connects the live site to
the evidence in this repository.

---

## Known limitations of this deployment

Stated here rather than discovered during marking.

**Uploads do not survive a restart.** The database is external and durable; the
uploaded radiographs and generated heatmaps are written to the container's own
filesystem, which a free Space does not keep. A record will outlive its image.
Fixing this needs object storage, which the Build Phase notes also say:
"container-local storage is not the project's permanent record."

**The Space sleeps.** A free Space stops after a period without traffic and the
next visitor waits for it to start. Open it a few minutes before a
demonstration, and keep a recorded backup as the notes advise.

**The first prediction after a start is slow.** TensorFlow and the weights load
on first use, which takes several seconds; afterwards it is about 120 ms. The
health check has a three-minute start period for this reason.

**One worker.** The model is held per process and is most of the memory
footprint, so a second worker would double it for no gain on a single CPU.
Concurrent uploads queue.

**Cost and lifetime.** The free tiers used here have no charge, but Neon
suspends an idle project and Hugging Face may change its allowances. Record the
expiry and keep the deployment reachable for as long as assessment requires.
