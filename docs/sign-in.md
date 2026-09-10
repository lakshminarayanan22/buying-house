# Signing in to Ecolink

Only people with an **@ecolinksolutions.in Google Workspace account** can get in, and only after
an admin has let them in once.

## How it works

```
 Sign in with Google ──► genuine Google token? ──no──► refused (401)
                               │ yes
                               ▼
                 @ecolinksolutions.in, verified,
                 in the ecolinksolutions.in Workspace? ──no──► refused (403), nothing stored
                               │ yes
                               ▼
         first time? ──yes──► account created as PENDING ──► every admin is emailed
                               │                               │
                               │                     admin opens Team, approves
                               │                     (as Member or Admin) ──► person is emailed
                               ▼
                    ACTIVE ──► straight in, every time from now on
```

| Status     | What the person sees                    | How they get there                |
|------------|-----------------------------------------|-----------------------------------|
| `PENDING`  | "Waiting for approval"                  | First Google sign-in              |
| `ACTIVE`   | The app                                 | An admin approved them            |
| `REJECTED` | "Request declined"                      | An admin declined the request     |
| `DISABLED` | "Access switched off"                   | An admin switched them off        |

Nothing is ever deleted. Declined and switched-off people stay on the Team page, and an admin can
let them back in with one click.

### The three Google checks

A token has to pass all of these, on the server, whatever the browser claims:

1. **Genuine** — signed by Google, issued for *our* client id, not expired (the `google-auth`
   library).
2. **`email_verified`** — Google has confirmed the person controls the address.
3. **Address ends in `@ecolinksolutions.in` *and* `hd` is `ecolinksolutions.in`.** `hd` is set by
   Google from the Workspace the account belongs to. It is what stops a *personal* Google account
   that happens to use a company address as its login.

### Passwords

Optional, and only for people who are already approved: from **Your account** (top-right avatar →
Your account) anyone can add a password as a second way in, for when Google is unavailable. Nobody
can create an account with a password — Google is the only way an account comes into existence.

> **When someone leaves:** switch them off on the **Team** page. Suspending them in Google
> Workspace blocks their Google sign-in but **not** an Ecolink password they may have added.
> Switching off in Ecolink closes both and signs them out everywhere, immediately.

### Guards

- An admin can't switch off or change the role of their own account.
- The last active admin can never be removed or demoted.
- If Workspace gives a former employee's address to someone new, the new person does **not**
  inherit access — the account is tied to Google's permanent account id, not the address.

## Setting it up

### 1. Create the Google OAuth client (about 5 minutes)

Sign in to <https://console.cloud.google.com> with an @ecolinksolutions.in account.

1. Create a project, e.g. **Ecolink**.
2. **APIs & Services → OAuth consent screen**. Choose **Internal**. This is a second lock at
   Google's end — with Internal, Google itself will only let accounts from your Workspace sign in.
   App name *Ecolink*, support email yours.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**.
   - Type: **Web application**
   - **Authorised JavaScript origins**: `http://localhost:3000`, plus the real address once the app
     is hosted (e.g. `https://ecolink.ecolinksolutions.in`)
   - Redirect URIs: none needed — sign-in uses Google's popup.
4. Copy the **Client ID** (ends in `.apps.googleusercontent.com`). There is a client secret too;
   Ecolink doesn't use it.

### 2. Configure the backend (`backend/.env`)

```
GOOGLE_AUTH_BACKEND=google
GOOGLE_CLIENT_ID=<the client id>
ALLOWED_EMAIL_DOMAIN=ecolinksolutions.in
BOOTSTRAP_ADMIN_EMAILS=you@ecolinksolutions.in
```

`BOOTSTRAP_ADMIN_EMAILS` is how the very first request gets approved: those addresses become
Admin automatically on their first Google sign-in. After that, admins approve everyone else from
the Team page.

### 3. Email (optional, recommended)

Without it, requests still appear on the Team page with a count in the header — you just won't
get an email. With Workspace:

1. Pick the mailbox that sends, e.g. `no-reply@ecolinksolutions.in`. It needs 2-Step Verification.
2. <https://myaccount.google.com/apppasswords> → create an app password for *Ecolink*.
   (If the option is missing, your Workspace admin has disabled app passwords; use
   `SMTP_HOST=smtp-relay.gmail.com` with the relay configured in the Admin console instead.)
3. In `backend/.env`:

```
EMAIL_BACKEND=smtp
EMAIL_FROM=Ecolink <no-reply@ecolinksolutions.in>
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=no-reply@ecolinksolutions.in
SMTP_PASSWORD=<the 16-character app password>
```

A failed send is logged and never blocks a sign-in or an approval.

### 4. Before it's reachable by anyone else

Set `ENVIRONMENT=production` and a real `JWT_SECRET`. The server **refuses to start** if, outside
local, it's still on the stub sign-in or the development JWT secret.

## Development without Google

With `GOOGLE_AUTH_BACKEND=stub` (the default) the login screen shows a form instead of the Google
button: type the address Google would have vouched for. The domain rule and the approval queue
behave exactly as they will for real — typing a gmail.com address is refused. The stub only works
when `ENVIRONMENT` is local.
