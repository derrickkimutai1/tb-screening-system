# GitHub sign-in

A third way in, offered on the same terms as Google and Microsoft: registered
only when its credentials are present, absent from the sign-in page when they
are not.

## Why it is here

A GitHub account says nothing about whether somebody works at a clinic, so it
is not an identity a real deployment should accept. `SIGN_IN_ALLOWED_DOMAINS`
closes it as firmly as any other route, and a deployment holding real records
should use it.

What GitHub is good for is that registering the callback takes **one form with
one box**, and no project to select first. Google's console asks you to pick
the right project, then the right OAuth client of possibly several, then the
right field among three that all accept URLs. Every one of those is a chance to
edit something that is not connected to your application, which is how an
afternoon went into a `redirect_uri_mismatch` that was never in the code.

So this is the quickest way to demonstrate that the social sign-in path works
when another provider's console is in the way.

## Registering it

1. <https://github.com/settings/developers>, **OAuth Apps**, **New OAuth App**.
2. Fill in four boxes:

   | Field | Value |
   |---|---|
   | Application name | `TB Screening` |
   | Homepage URL | the address of your deployment, or `http://localhost:8000` |
   | Application description | optional |
   | Authorization callback URL | see below |

3. The callback URL is the address with `/accounts/github/login/callback/` on
   the end. For the deployment:

   ```
   https://tb-screening.happybay-20a0549c.southafricanorth.azurecontainerapps.io/accounts/github/login/callback/
   ```

   For local development:

   ```
   http://localhost:8000/accounts/github/login/callback/
   ```

   A GitHub OAuth App takes **one** callback URL, so register two apps if you
   want both, and keep their credentials apart.

4. **Register application**. GitHub shows a Client ID. Click **Generate a new
   client secret** and copy it now; it is not shown again.

5. Put both in `.env` for local use:

   ```
   GITHUB_OAUTH_CLIENT_ID=the client id
   GITHUB_OAUTH_CLIENT_SECRET=the secret
   ```

   or on the deployment:

   ```bash
   az containerapp update --name tb-screening --resource-group tb-screening \
       --set-env-vars GITHUB_OAUTH_CLIENT_ID=... GITHUB_OAUTH_CLIENT_SECRET=...
   ```

   On the deployment the secret belongs in a secret rather than a plain
   variable, the way the others are set in `deploy/azure-setup.sh`.

6. Reload the sign-in page. **Continue with GitHub** appears.

## Scopes

`read:user` and `user:email`. The second matters: a GitHub account may keep
every address private, and without that scope such an account arrives with no
address at all. This system attributes every screening and review to a person,
and the address is how a clinic reaches them, so an account it cannot read an
address from is an account it cannot place.

GitHub asks the person to approve these on first sign-in and names them.
Neither grants any write access to their repositories.

## What happens on a first sign-in

The same as Google and Microsoft: GitHub supplies an identity, and the sign-up
form then asks for a name and a facility, because no provider can say which
clinic somebody works at. The role stays at the model's default and is never
self-chosen, so a new account cannot grant itself the right to record a
clinical review.
