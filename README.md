## 1. What this bot does

1. While running, it detects a human member joining the configured community.
2. If enabled, it assigns Pending, then creates a private `test-USER_ID` text channel.
3. The candidate types `!start`. The bot loads the current question/configuration files and starts the timer.
4. Multiple-choice answers are graded automatically. Open-ended and picture responses go to moderator review.
5. When finished or expired, results are posted to the configured private results channel. The candidate receives their automatic score and manual-review count.
6. An authorized reviewer types `!approve USER_ID` in the results channel. The bot grants Verified and removes Pending if configured.

Completing a test does not grant Verified automatically. Test channels are not deleted automatically. Channel permissions, rather than the Pending role alone, control access to the rest of the community.

## 2. Files

| File | Purpose |
| --- | --- |
| `bot.py` | Main bot script|
| `questions.json` | The test |
| `config.json` | Test duration |
| `princessmario.jpg` and any other referenced images | Add your sample images here |
| `README.md` | This guide |

## 3. Create a bot application on your instance

Open your self-hosted instance’s web client and sign in with an account that can create applications and manage the target community. If using a desktop client, first confirm it is connected to the self-hosted instance. Create and authorize the application there, rather than on public Fluxer.

Instance-level administrator access and community ownership are distinct. If the Applications page is unavailable, ask the instance operator to check the feature/access configuration for that installed version.

1. Open User Settings → Developer → Applications (labels may differ by instance version).
2. Create an application, for example `Entry Examiner`.
3. Leave “Require OAuth2 code grant” off for a simple bot installation. No redirect URI is needed for this bot-only flow.
4. Keep Public bot off if the application is only for your own community.
5. Copy the bot token when created, or regenerate the bot token if it is no longer available. The client secret is not the bot token.
6. In the OAuth2 URL builder, select only the `bot` scope and authorize the application into the intended community.

Grant these bot permissions:

- View Channels
- Send Messages
- Read Message History
- Attach Files
- Manage Channels
- Manage Roles / Manage Permissions, as applicable in the UI

The bot must be able to create private channels and set permission overwrites, assign Verified/Pending, and post images. Administrator permission is not required. Verify that it retains access in channels where @everyone is denied.

## 4. Create roles and configure permissions

Create `Pending`, `Verified`, and a moderator role if needed. Put the bot's role above Pending and Verified in the role hierarchy. Give the bot Manage Roles. Do not give Pending or Verified administrator/moderation powers.

### Main channels and voice channels

Configure every main channel, or a category inherited by those channels:

| Principal | View Channel | Send Messages / Connect |
| --- | --- | --- |
| @everyone | Deny | As appropriate; invisible channels are inaccessible |
| Verified | Allow | Allow normal member actions |
| Pending | Neutral / inherit | Neutral / inherit |
| Moderator | Allow | Allow actions needed for moderation |

Review other roles and member-specific overrides: an unrelated allow can grant access despite the intended gate. New users must not receive Verified from another auto-role mechanism.

### Welcome channel

Create `#welcome`. Allow @everyone to view it and read history; deny ordinary members sending messages if you want it read-only. Allow the bot to view, send, and read history. Post instructions telling new members to open their private `test-USER_ID` channel and type `!start`.

No welcome-channel ID is needed by the bot. It does not automatically post candidate-specific links in #welcome.

### Results channel

Create `#test-results`:

- @everyone: deny View Channel.
- Pending and Verified: no explicit access grant.
- Bot: allow View Channel, Send Messages, Read Message History, Attach Files.
- Authorized moderator roles: allow View Channel, Send Messages, Read Message History.

Keep this channel private. Candidates do not need access to it to be approved. They may not appear in its mention autocomplete; use their numeric Member ID from the results summary.

### Private test channels

The bot creates these outside a category, with @everyone denied viewing and direct member access for the candidate, configured owner, and bot. Do not sync or move them into a category in a way that overwrites these permissions.

Ordinary moderators do not automatically receive access to each private test channel. They review the copied answers/images in #test-results. Administrators can have broader access by virtue of their permissions.

## 5. Collect instance-specific IDs

Enable Developer mode if required and use Copy ID in the relevant menus.

| Setting | Value needed |
| --- | --- |
| `GUILD_ID` | Community/server ID, not the instance domain |
| `OWNER_ID` | your self-hosted instance account ID of the owner/reviewer |
| `RESULTS_CHANNEL_ID` | Private #test-results channel ID |
| `PENDING_ROLE_ID` | Pending role ID; optional, blank disables auto-Pending |
| `VERIFIED_ROLE_ID` | Verified role ID; required for !approve and for auto-Pending cleanup |
| `MODERATOR_ROLE_IDS` | Comma-separated role IDs authorized to approve; optional |

Use role IDs for MODERATOR_ROLE_IDS, not individual moderator user IDs. The configured OWNER_ID is authorized independently. Merely naming a role “Moderator” or giving someone a server permission does not authorize the command: its ID must be configured.

## 6. Install on the VPS

Connect to the rented VPS using your normal SSH account. The commands below run on the VPS, not on a Windows desktop. Keep Fluxer running as usual while installing the separate bot service.

### If Fluxer itself uses Docker Compose or Kubernetes

The bot can still run directly on the Linux host using the systemd instructions below. There is no requirement to put it inside Fluxer's containers, attach it to the Fluxer database, or modify the existing Compose/Kubernetes deployment.

Use API and gateway addresses reachable from the environment running the bot. `localhost` inside a container refers to that container, not the VPS or another container. The supplied deployment route runs the bot on the host and uses the discovered HTTPS API address.

If you instead containerize the bot, you must separately provide its dependencies, .env, questions, configuration, images, a writable persistent exam.db location, networking, and restart behavior. A bot Dockerfile/Compose configuration is not included here; the commands below are for host-based systemd deployment.

### Install prerequisites and create a dedicated service account

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ca-certificates curl
python3 --version
sudo useradd --system --create-home --home-dir /opt/fluxer-examiner --shell /usr/sbin/nologin fluxer-examiner
```

Use Python 3.10 or newer. If the service account already exists, skip useradd. Use a supported distribution/Python version if the installed Python is too old.

Upload the supplied files with SFTP/SCP into `/opt/fluxer-examiner` (using a staging directory if your SSH account cannot write there). Preserve relative image directories. No GitHub account is necessary.

Create `/opt/fluxer-examiner/requirements.txt` with:

```text
fluxer.py
aiohttp
python-dotenv
truststore
```

Then:

```bash
sudo chown -R fluxer-examiner:fluxer-examiner /opt/fluxer-examiner
sudo chmod 750 /opt/fluxer-examiner
sudo -u fluxer-examiner python3 -m venv /opt/fluxer-examiner/.venv
sudo -u fluxer-examiner /opt/fluxer-examiner/.venv/bin/python -m pip install -r /opt/fluxer-examiner/requirements.txt
```

Dependencies are not version-pinned in this example. After successful testing, record the working versions for reproducible deployment:

```bash
sudo -u fluxer-examiner /opt/fluxer-examiner/.venv/bin/python -m pip freeze | sudo tee /opt/fluxer-examiner/requirements.lock.txt >/dev/null
```

## 7. Create your .env

```bash
sudo -u fluxer-examiner nano /opt/fluxer-examiner/.env
```

Enter the following, replacing every placeholder with your instance's real value:

```dotenv
FLUXER_BOT_TOKEN=YOUR_INSTANCE_BOT_TOKEN
FLUXER_API_URL=https://YOUR_ACTUAL_API_BASE/v1
GUILD_ID=YOUR_COMMUNITY_ID
OWNER_ID=YOUR_ACCOUNT_ID
RESULTS_CHANNEL_ID=YOUR_RESULTS_CHANNEL_ID
PENDING_ROLE_ID=YOUR_PENDING_ROLE_ID
VERIFIED_ROLE_ID=YOUR_VERIFIED_ROLE_ID
MODERATOR_ROLE_IDS=YOUR_MODERATOR_ROLE_ID
```

For multiple moderator roles, use `MODERATOR_ROLE_IDS=ID1,ID2`. To authorize only the owner, use `MODERATOR_ROLE_IDS=`. To disable the optional Pending feature, use `PENDING_ROLE_ID=`. Keep Verified configured if using !approve.

Protect the token file:

```bash
sudo chmod 600 /opt/fluxer-examiner/.env
```

Do not publish the file or put the token in shell commands, screenshots, or support messages. The bot reads `.env` beside bot.py. Environment variables already set in the process can take precedence over python-dotenv values; avoid stale conflicting service environment settings.

## 8. Configure questions and duration

### Duration: config.json

```json
{
  "test_duration_minutes": 15
}
```

The duration must be a positive integer. This version accepts only that setting in config.json; environment IDs/token belong in .env.

### Questions: questions.json

The file is a non-empty JSON array. Example:

```json
[
  {
    "type": "multiple_choice",
    "text": "Capital of Uzbekistan:",
    "options": {
      "A": "Jizzax",
      "B": "Qarshi",
      "C": "Nukus",
      "D": "Tashkent"
    },
    "correct": "D"
  },
  {
    "type": "open_ended",
    "text": "Why would you like to join this community?"
  },
  {
    "type": "open_ended",
    "text": "Tell me what is silly or impossible about this picture:",
    "image": "princessmario.jpg"
  }
]
```

- Multiple-choice questions require at least two options, uppercase single-letter keys, and a matching correct letter.
- Candidates may submit lowercase or uppercase letters. Option text is not accepted in place of a letter.
- Open-ended questions omit options and correct. Candidates submit one text message; edits do not replace a submitted answer.
- Either type may include image, using a local filename/path inside the bot folder. Remote image URLs are not supported by this implementation.
- Keep the question/options text within 1,500 characters. Use double quotes, no comments, and no trailing commas.
- Do not begin an open-ended answer with `!`: command-prefixed messages are ignored as answers.

Save changes atomically where practical (edit a temporary file, validate it, then replace the real file) to avoid a new attempt reading a half-written JSON file. config.json and questions.json are reloaded at each new !start; no restart is needed. .env and bot.py changes require a restart.

Active attempts retain their stored question snapshot and deadline. Their local image file contents are not snapshotted: keep old images available and use new filenames for changed pictures until old attempts are over. Missing images cause startup/configuration checks or question delivery to fail.

## 9. Run test

Before running, confirm that FLUXER_API_URL is explicitly set to the self-hosted instance, and that the token and GUILD_ID were created there. The bot is a client of your existing Fluxer API; starting it will not start or repair the Fluxer instance.

```bash
sudo -u fluxer-examiner /opt/fluxer-examiner/.venv/bin/python /opt/fluxer-examiner/bot.py
```

Wait for “Connected as …” and, if configured, “Pending auto-role: enabled”.

In #test-results send `!ping`. The bot should reply. The configured owner may send `!setup_test` there to create/reuse their own private test channel. That command sets up only the owner's channel.

Stop the foreground process with Ctrl+C before starting the service below. Run only one copy of the bot against this community/database.

## 10. Keep it running with systemd

Create `/etc/systemd/system/fluxer-examiner.service`:

```bash
sudo nano /etc/systemd/system/fluxer-examiner.service
```

Paste:

```ini
[Unit]
Description=Fluxer entry examiner bot
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=fluxer-examiner
Group=fluxer-examiner
WorkingDirectory=/opt/fluxer-examiner
ExecStart=/opt/fluxer-examiner/.venv/bin/python -u /opt/fluxer-examiner/bot.py
Environment=PYTHONDONTWRITEBYTECODE=1
Restart=always
RestartSec=10
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/fluxer-examiner

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now fluxer-examiner
sudo systemctl status fluxer-examiner --no-pager
```

View logs:

```bash
sudo journalctl -u fluxer-examiner -n 100 --no-pager
sudo journalctl -u fluxer-examiner -f
```

Ctrl+C exits the log viewer, not the service. You may close SSH or switch off your personal computer; the service stays on the VPS. Restart=always restarts an exited process, but it cannot detect every hung/stalled connection; monitor availability and test reconnection behavior on your deployment.

The bot needs outbound access to the instance API/gateway and upload destinations. It does not run a public HTTP server, so do not open an inbound port just for this bot.
