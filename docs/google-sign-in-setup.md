# Google sign-in: setting up the credentials

The application asks Google to confirm who a user is. Google will only do that
for an application it knows about, so the project has to be registered once in
the Google Cloud Console. This is a five-minute task and produces two values
that go into `.env`.

Nothing here is secret to Google: the client ID is public. The client secret is
not, which is why `.env` is never committed.

## 1. Create the project

1. Open <https://console.cloud.google.com/>.
2. Click the project selector at the top of the page, then **New project**.
3. Name it `TB Screening System`. Leave the organisation as-is. Click **Create**.
4. Wait for the notification, then make sure the selector shows the new project.

## 2. Configure the consent screen

Google shows this screen to the user when they sign in, so it has to be filled
in before a client can be created.

1. In the left menu choose **APIs & Services > OAuth consent screen**.
2. Choose **External**, then **Create**.
3. Fill in:
   - **App name:** `TB Screening System`
   - **User support email:** your own address
   - **Developer contact information:** your own address
4. **Save and continue** through Scopes without adding any. The application
   asks for the default profile and email scopes only, which need no review.
5. On **Test users**, click **Add users** and enter every address that will sign
   in during the demonstration, including your own and your supervisor's. While
   the app is unpublished Google admits test users only.
6. **Save and continue**, then **Back to dashboard**.

## 3. Create the client

1. **APIs & Services > Credentials**.
2. **Create credentials > OAuth client ID**.
3. **Application type:** `Web application`.
4. **Name:** `TB Screening local`.
5. Under **Authorised redirect URIs**, click **Add URI** and paste exactly:

   ```
   http://localhost:8000/accounts/google/login/callback/
   ```

   The trailing slash matters. A mismatch here is the single most common cause
   of `redirect_uri_mismatch` when signing in.
6. **Create**. Google shows the client ID and client secret. Copy both.

## 4. Put them in .env

Add these four keys to `.env` (they are already listed in `.env.example`):

```
GOOGLE_OAUTH_CLIENT_ID=<the client ID>
GOOGLE_OAUTH_CLIENT_SECRET=<the client secret>
SIGN_IN_ALLOWED_EMAILS=your.address@gmail.com,supervisor@strathmore.edu
SIGN_IN_ALLOWED_DOMAINS=
```

`SIGN_IN_ALLOWED_EMAILS` and `SIGN_IN_ALLOWED_DOMAINS` decide who is admitted
once Google has confirmed them. Leaving both empty admits any Google account,
which is fine on a laptop and wrong anywhere else.

Restart the server. The sign-in page should now report **Ready** rather than
**Unconfigured** and offer the Google button.

## If something goes wrong

**`redirect_uri_mismatch`** — the URI in the console is not character for
character the one above. Check the scheme (`http`, not `https`), the port, and
the trailing slash.

**`access_blocked` or "has not completed the verification process"** — the
address is not on the test-user list from step 2.5.

**"That Google account is not authorised for this system"** — Google confirmed
the user, but `SIGN_IN_ALLOWED_EMAILS` does not list them. This message comes
from this application, not from Google.

**The page says Unconfigured after editing .env** — the server reads `.env` at
startup. Stop it and start it again.

## Deploying elsewhere

A deployed copy needs its own redirect URI added in the console, its own
`DJANGO_SITE_DOMAIN`, and `https` rather than `http`. Keep the local URI in
place so development continues to work.
