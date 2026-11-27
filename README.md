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

## 9. Run a foreground smoke test

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

## 11. Test the complete candidate flow

Use an ordinary account, not an administrator.

1. Invite it while the bot is running. Confirm Pending appears and its private test channel is created.
2. Confirm it sees #welcome and its own test channel, but not main channels, #test-results, or other candidates' channels.
3. Type !start and confirm the configured time limit appears.
4. Submit multiple-choice letters and open-ended responses. Verify picture delivery.
5. Confirm automatic score excludes manual-review questions and the results contain the candidate's numeric Member ID.
6. In #test-results, as the owner or an authorized moderator, send `!approve USER_ID` using that numeric ID.
7. Confirm Verified is assigned, Pending removed, and normal channels become visible. The private test channel remains.
8. Verify an unauthorized account cannot approve. A moderator needs both results-channel posting access and an authorized role ID.
9. Test expiry using a temporary short duration with a fresh attempt. Restore the intended duration afterwards.
10. Test a service restart during an attempt: the stored deadline must remain unchanged.

The approval command accepts completed or expired attempts; it does not enforce a minimum score. Review open-ended answers and decide before issuing it. Plain `approve` without the ! prefix/user ID is not a command.

## 12. Routine operation

| Task | Action |
| --- | --- |
| Approve | `!approve USER_ID` in #test-results |
| Re-display current question | Candidate types `!question` in their own test channel |
| Change duration/questions | Edit JSON files; applies to new attempts |
| Change IDs/token/moderators | Edit .env, then restart the service |
| Restart | `sudo systemctl restart fluxer-examiner` |
| Stop | `sudo systemctl stop fluxer-examiner` |
| Disable automatic startup | `sudo systemctl disable fluxer-examiner` |

To update code, stop the service, back up files/database, replace bot.py, preserve your local .env/JSON/images/database, and restart. The supplied questions are examples; review their suitability and replace them before launch.

### Back up the database

The bot stores answers, questions, deadlines, and status in exam.db beside bot.py. Back it up privately along with configuration and images. A simple consistent backup can be made while the service is stopped:

```bash
sudo systemctl stop fluxer-examiner
sudo install -d -m 700 /var/backups/fluxer-examiner
sudo cp /opt/fluxer-examiner/exam.db /var/backups/fluxer-examiner/exam.db
sudo chmod 600 /var/backups/fluxer-examiner/exam.db
sudo systemctl start fluxer-examiner
```

This example overwrites that backup filename. Use your normal versioned/off-host backup system for ongoing retention. Treat answer data and credentials as private; do not include them in a shareable code ZIP.

### Reset one attempt for testing

This permanently deletes that user's current saved attempt, not their Fluxer messages or roles. Back up first. Stop the service, run the script below, and enter the numeric candidate ID when prompted:

```bash
sudo systemctl stop fluxer-examiner
sudo -u fluxer-examiner /opt/fluxer-examiner/.venv/bin/python -c 'import sqlite3; uid=input("Candidate user ID: ").strip(); assert uid.isdigit(), "Use a numeric ID"; c=sqlite3.connect("/opt/fluxer-examiner/exam.db"); r=c.execute("DELETE FROM exams WHERE user_id = ?", (uid,)); c.commit(); print("Attempts reset:",r.rowcount); c.close()'
sudo systemctl start fluxer-examiner
```

Have the candidate type !start in their existing private test channel. If testing the gate again, remove Verified separately. Do not delete the whole database to reset one person.

## 13. Troubleshooting and current limits

| Symptom | Check |
| --- | --- |
| Bot connects to public Fluxer | FLUXER_API_URL is missing/wrong; use your instance's discovered public API base plus /v1 |
| HTTP 401 / authentication failure | Token belongs to this instance; use bot token rather than client secret; regenerate only if needed |
| HTTP 403 on role/channel operations | Bot permission grants, channel overrides, role hierarchy, and instance MFA requirements |
| Bot cannot send a picture | Attach Files permission, image filename/case/path, instance upload limits, and API/library compatibility |
| “Already started” | Saved attempt exists; reset only that user's attempt if a retake is intended |
| Candidate absent from mention suggestions | Use numeric Member ID in !approve; do not expose results channel |
| “Not authorized” for moderator | Configure their role ID in MODERATOR_ROLE_IDS, restart, and check results-channel access |
| No automatic Pending | PENDING_ROLE_ID is blank or invalid; check startup log and role permissions |
| Approved but Pending remains | Check cleanup warning and bot role permissions; remove Pending manually if necessary |
| Verified but main channels remain hidden | Verified View Channel/Connect/Send permissions and inherited overrides |
| Service cannot write database | Directory ownership, service account permissions, and persistent writable storage |
| JSON error | Double quotes, commas, supported schema, image existence; startup error identifies invalid configuration |
| TLS/certificate error | VPS clock, instance certificate chain, host CA trust; never disable verification |
| Unknown gateway/model errors | Compare installed fluxer.py and instance versions; successful public Fluxer tests do not guarantee your self-hosted instance compatibility |

Known behavior and limits of this version:

- No catch-up scan for members who joined while offline. Create a channel manually with the expected name and matching private overwrites for those users, or arrange a controlled rejoin after restoring the bot. Do not assume an offline join is handled automatically later.
- Deadlines continue while offline. Replies sent during downtime may not be processed; do not rely on gateway replay to recover them. Expired tests are processed on restart.
- New Pending assignment and automatic cleanup on manual Verified changes require the bot to receive events while running. If approval happened offline, remove Pending manually.
- Answers are persisted before results delivery, but failed results posts are not queued for automatic redelivery. Recover from the database if necessary.
- Question-send failures can interrupt the flow. After fixing the underlying issue, !question re-displays the current unanswered question without resetting its deadline.
- Private test channels and old result messages remain until manually removed. Deleting a channel can prevent or complicate continued testing.
- The bot copies text answers and image prompts to results. It does not grade open-ended responses or provide a separate manual-grading UI.
- Role assignment alone does not enforce the gate. Check permissions with a real ordinary-member account before admitting users.

## 14. Self-hosted deployment acceptance checklist

Do not consider the installation complete until all of these are confirmed:

- [ ] Application/token created on your self-hosted instance, not public Fluxer.
- [ ] FLUXER_API_URL matches your instance's discovered public API base plus /v1.
- [ ] All community, account, channel, and role IDs belong to your self-hosted instance.
- [ ] Bot connects and responds to !ping in the intended community.
- [ ] New-member event creates a private channel and assigns Pending.
- [ ] An ordinary member cannot see other test channels or moderator results.
- [ ] Multiple-choice, open-ended, picture delivery, timeout, and results work.
- [ ] Owner/authorized moderator can approve by numeric ID; unauthorized users cannot.
- [ ] Bot remains available after SSH disconnect and starts after a planned reboot.
- [ ] exam.db survives service restart; existing deadlines are preserved.

The existing public-service tests establish the custom bot's intended workflow, not compatibility with an unseen self-hosted deployment. If HTTP works but gateway events or model parsing fail, inspect the installed Fluxer and fluxer.py versions before changing permissions or tokens repeatedly.
