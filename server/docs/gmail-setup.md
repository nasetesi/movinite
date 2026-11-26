# Send invites from your Gmail (Movinite 1.9)

Movinite can email invites **from your own Gmail address**, so the person you invite sees your name and your
address, and replies come straight back to you. The easy way is a Gmail **app password**: about 2 minutes, once.

If you skip this, invites still work: Movinite gives you a link and a QR code to share yourself.

## Gmail with an app password (recommended)

### 1. Turn on 2-Step Verification

App passwords only exist when 2-Step Verification is on.

1. Open <https://myaccount.google.com/security> signed in as the Gmail account invites should come from.
2. Under **How you sign in to Google**, open **2-Step Verification** and turn it on (a phone prompt or an
   authenticator app is fine).

### 2. Create an app password

1. Open <https://myaccount.google.com/apppasswords>.
2. Type a name such as `Movinite` and press **Create**.
3. Google shows a **16-letter password** in four groups (like `abcd efgh ijkl mnop`). Copy it. You'll only see it
   once; if you lose it, delete it and make a new one.

Don't paste it into chat or email. It only goes into Movinite.

> No "App passwords" page? It's hidden when 2-Step Verification is off, for some Google Workspace accounts where
> the admin turned it off, and for accounts using Advanced Protection. Use the advanced Connect Gmail option below,
> or another email provider.

### 3. Enter it in Movinite

1. Movinite > **Settings > Email** > **Send invites from your email**.
2. **Send with:** Gmail (app password).
3. **Gmail address:** your full address, for example `you@gmail.com`.
4. **App password:** the 16 letters (spaces are fine).
5. **From name:** how you appear in the recipient's inbox. Use the name on your Google account so people know it's
   you. It's prefilled with the name Movinite knows for you.
6. Press **Save**, then **Send test email to myself**. A sample invite arrives in your own inbox within a minute
   (check Spam the first time). The status changes to **Working**.

Movinite sends through `smtp.gmail.com` port 587 with STARTTLS. The From address is always your Gmail address and
replies go to it. The app password is stored encrypted on the server (`data/secrets/smtp.sealed`, readable only by
the Movinite service) and is never shown again or written to logs.

### Send an invite

Settings > Users > **Invite by email**: their address, a role, the libraries, an optional note, and when the link
expires. Press **Send invite**. It's also in your Gmail **Sent** folder.

## Other email providers (SMTP)

**Send with:** Other email (SMTP server), then fill in what your provider documents:

| Field | Typical value |
|---|---|
| SMTP server | `smtp.example.com` (Outlook.com: `smtp-mail.outlook.com`; iCloud: `smtp.mail.me.com`; Fastmail: `smtp.fastmail.com`) |
| Port / Security | `587` + STARTTLS, or `465` + SSL/TLS |
| Username | usually your full email address |
| Password | your provider's app password where it has them |
| From address | the address invites come from (most providers require it to be your own address) |

A relay on your own network that doesn't need a sign-in can leave Username empty and use Security **None**.

## Limits

- Movinite sends at most **20 invites an hour** and **100 a day** through the account (change in Settings > Email).
  Test emails count too. Past the limit the invite is still created and you get the link to share yourself.
- Gmail's own limit is about 500 messages a day for @gmail.com.

## Turning it off

- Settings > Email > **Remove** deletes the saved address and password from the server.
- To stop the password working everywhere, delete it at <https://myaccount.google.com/apppasswords>.
  Changing your Google password also revokes all app passwords.

## Troubleshooting

| Message | Fix |
|---|---|
| "Gmail didn't accept the address and app password (535)" | Check the address; make a new app password and save it again. Your normal Gmail password doesn't work here. |
| "Gmail needs an app password" (534) | 2-Step Verification is off or a normal password was used. Turn it on and create an app password. |
| "temporarily refusing sign-ins" / "asked to try later" (421, 454) | Too many tries or a burst of mail. Wait a few minutes. |
| "daily sending limit was reached" (550 5.4.5) | Gmail's daily limit. Share links until tomorrow. |
| "Couldn't connect to smtp.gmail.com:587" | The server can't reach the internet on port 587 (some ISPs and firewalls block mail ports). Try another network, or SSL/TLS on 465 under Other email. |
| "missing the Python 'cryptography' package" | Re-run `update.sh`; it installs it. |

---

## Advanced: Connect Gmail with Google sign-in (OAuth)

Instead of an app password, Movinite can use Google sign-in with permission to **send only** (`gmail.send`); it
can't read your mail and never sees your Google password. It takes about 10 minutes, once, in your own Google
Cloud project. In Settings > Email open **Advanced: Connect Gmail** and choose **Connect Gmail** as the method.
The From name is the name on your Google account.

### 1. Create a Google Cloud project

1. Open <https://console.cloud.google.com/> and sign in with the Google account you want invites to come from.
2. Top bar > project picker > **New project**. Name it `Movinite` and press **Create**. Make sure it's selected.

### 2. Turn on the Gmail API

1. Go to **APIs & Services > Library** (<https://console.cloud.google.com/apis/library/gmail.googleapis.com>).
2. Open **Gmail API** and press **Enable**.

### 3. Set up the consent screen (Google Auth Platform)

1. Go to **APIs & Services > OAuth consent screen** (newer consoles call it **Google Auth Platform > Branding**).
   Press **Get started** if asked.
2. App name: `Movinite`. User support email: your address.
3. Audience:
   - **Internal** if you use Google Workspace and only people in your organisation will connect. No review needed.
   - **External** for a normal @gmail.com account.
4. Contact email: your address. Accept the policy and press **Create**.
5. **Data access** (or **Scopes**) > **Add or remove scopes**. Add these four:
   - `openid`
   - `.../auth/userinfo.email` (email)
   - `.../auth/userinfo.profile` (profile, used for the From name)
   - `https://www.googleapis.com/auth/gmail.send`
   Save.
6. External only, **Audience** page: either
   - add yourself (and any other admin who will connect) under **Test users**, or
   - press **Publish app** so its status is **In production**.

   > Why publish? While an External app is in **Testing**, Google expires its sign-ins after **7 days** and
   > Movinite will ask you to reconnect every week. **In production** keeps the connection until you remove it.
   > Because Movinite asks for a sensitive scope, Google shows an "unverified app" warning for a personal project;
   > it's your own app, so choose **Advanced > Go to Movinite (unsafe)**. You don't need Google's verification
   > for personal use (fewer than 100 users).

### 4. Create the OAuth client

1. **APIs & Services > Credentials > Create credentials > OAuth client ID** (or **Google Auth Platform > Clients > Create client**).
2. Application type: **Web application**. Name: `Movinite`.
3. **Authorized redirect URIs**: add the exact addresses Movinite shows in **Settings > Email**. Usually:
   - `https://movies.example.com/api/gmail/callback` — your public https address followed by `/api/gmail/callback`.
     Add one line for each public address you use (for example both `media.` and `movies.` names).
   - `http://localhost/movinite-gmail-callback` — the **paste** address, for servers that only have a LAN or http
     address (Google only accepts https or localhost). Adding it is harmless even if you have an https address.
4. Leave **Authorized JavaScript origins** empty. Press **Create**.
5. Google shows the **Client ID** (ends in `.apps.googleusercontent.com`) and **Client secret** (starts with `GOCSPX-`).
   Keep this window open, or download the JSON. Treat the secret like a password: don't email it or put it in chat.

### 5. Paste them into Movinite

1. Movinite > **Settings > Email**.
2. (Optional) **Public address**: your https address, for example `https://movies.example.com`. Invite links and the
   redirect address use it.
3. **Client ID** and **Client secret**: paste them and press **Save**. The secret is stored encrypted on the server
   (`data/secrets/gmail.sealed`, readable only by the Movinite service) and is never shown again.

### 6. Connect

- **Server with an https address:** press **Connect Gmail**. Google's page opens; pick your account, leave
  **Send email on your behalf** ticked, and press **Continue**. You land back on Settings > Email showing
  "Connected as Your Name <you@gmail.com>".
- **LAN / http server (paste mode):** press **Connect Gmail (paste mode)**. After you approve on Google's page, the
  browser goes to `http://localhost/movinite-gmail-callback?...` and probably says **This site can't be reached**.
  That's expected. Copy the **whole address** from the address bar, paste it into the box in Settings > Email,
  and press **Finish**. The code inside it works once and only for a few minutes.

Press **Send test email** to send a sample invite to yourself (no real invite is created).

### Limits

- Movinite sends at most **20 invites an hour** and **100 a day** per connected account (change in Settings > Email).
  Past the limit the invite is still created and you get the link to share yourself.
- Gmail's own limits apply too (about 500 messages a day for @gmail.com).

### Disconnecting

- Settings > Email > **Disconnect** revokes Movinite's access at Google and deletes the stored token.
- You can also remove it from Google: <https://myaccount.google.com/connections> > Movinite > **Delete all connections**.
  Movinite then shows "Reconnect Gmail" and falls back to links.
- Changing the client ID or secret disconnects every admin's Gmail (their sign-ins belong to the old client).

### Troubleshooting

| Message | Fix |
|---|---|
| `redirect_uri_mismatch` (Google error page) | The redirect URI in Google Cloud must match the one in Settings > Email exactly: `https`, host, no trailing slash. Changes in Google Cloud can take a few minutes. |
| "Access blocked: Movinite has not completed the Google verification process" | External app in Testing and your account isn't a test user. Add it under Audience > Test users, or publish the app. |
| "Google didn't return a long-lived sign-in" | Remove Movinite at <https://myaccount.google.com/connections> and connect again. |
| Reconnect every 7 days | The app is still in Testing. Publish it (In production). |
| "missing the Python 'cryptography' package" | Re-run `update.sh`; it installs it. |
