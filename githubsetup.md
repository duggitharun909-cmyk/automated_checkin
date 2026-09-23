# GitHub + cron-jobs.org Setup Guide

Goal: run `checkin.py` automatically every weekday, at a random time between **09:30 and 09:45**, without your laptop needing to be on.

## How it works

```
cron-jobs.org  --(HTTPS POST, ~09:25)-->  GitHub Actions API
                                                  |
                                                  v
                                    workflow_dispatch triggers checkin.yml
                                                  |
                                                  v
                              checkin.py --random-window runs in the cloud,
                              internally waits until a random second between
                              09:30-09:45, then performs the check-in
```

cron-jobs.org only needs to fire once a day, a few minutes before the window opens. The randomization inside `checkin.py` (the `--random-window` flag, using `CHECKIN_WINDOW_START` / `CHECKIN_WINDOW_END`) is what actually picks the random check-in second each day. This is more reliable than trying to schedule cron-jobs.org itself at a random time, and it reuses code you already have.

GitHub Actions runs Linux/Chromium in the cloud, so headless mode works there without any browser-download issues.

---

## 0. Security - do this first

Your repo `duggitharun909-cmyk/automated_checkin` is currently **public**, and until this session your real portal password was hardcoded in `checkin.py` and `README.md` in the initial commit.

1. **Rotate your Office Tracker password now**, if you haven't already. The old one is public in the git history regardless of any later edit.
2. Make the repository **private**: repo page -> **Settings** -> scroll to **Danger Zone** -> **Change visibility** -> **Make private**.
3. (Optional but recommended) Purge the old password from git history with the [`git filter-repo`](https://github.com/newren/git-filter-repo) tool or GitHub's "Remove sensitive data" guide, since a private repo you later make public again (or any collaborator you add) would still see it in old commits. Skip this if the repo will always stay private and only you have access.

The code fix (removing the hardcoded fallback credentials, moving the window to 09:30-09:45) has already been applied locally in this session - see step 2 below to commit and push it.

---

## 1. Files added/changed in this repo

- `.github/workflows/checkin.yml` - the GitHub Actions workflow that runs `checkin.py` in the cloud.
- `checkin.py` - no more hardcoded email/password fallback; now fails fast with a clear error if credentials aren't set.
- `.env`, `.env.example`, `README.md` - window updated to `09:30`-`09:45`, example credentials replaced with placeholders.

Review the diff before pushing:

```bash
cd /Users/macbook/Desktop/TechGy/automated_checkin
git status
git diff -- checkin.py README.md .env.example
```

(`.env` itself is gitignored and will not be pushed - that's correct, it should never leave your machine.)

---

## 2. Commit and push

```bash
git add checkin.py README.md .env.example .github/workflows/checkin.yml
git commit -m "Remove hardcoded credentials, add GitHub Actions check-in workflow"
git push origin main
```

---

## 3. Add repository secrets

GitHub repo -> **Settings** -> **Secrets and variables** -> **Actions** -> **New repository secret**. Add each of these (values come from your local `.env` file):

| Secret name | Example value |
|---|---|
| `PORTAL_URL` | `https://office-tracker-1.vercel.app/login` |
| `OFFICE_EMAIL` | your login email |
| `OFFICE_PASSWORD` | your (rotated) password |
| `OFFICE_LATITUDE` | `17.4835258` |
| `OFFICE_LONGITUDE` | `78.3808618` |
| `CHECKIN_WINDOW_START` | `09:30` |
| `CHECKIN_WINDOW_END` | `09:45` |

Secrets are encrypted, never shown again after saving, and are not visible in logs.

---

## 4. Test the workflow manually

Before wiring up cron-jobs.org, confirm it works on its own:

1. Repo page -> **Actions** tab -> **Office Check-In** workflow -> **Run workflow** -> **Run workflow** (green button).
2. Watch the run. It should log in, wait a few seconds/minutes (random window), and check in - or report "Already Checked In" if you already are.
3. Open the run -> **checkin-screenshot** artifact to download the screenshot and confirm visually.

If it fails, click into the failed step and read the error - almost always a missing/incorrect secret.

---

## 5. Create a GitHub Personal Access Token (for cron-jobs.org to call)

cron-jobs.org will call the GitHub API to trigger the workflow, which requires an auth token.

1. GitHub -> profile photo -> **Settings** -> **Developer settings** -> **Personal access tokens** -> **Fine-grained tokens** -> **Generate new token**.
2. **Repository access**: "Only select repositories" -> pick `automated_checkin` (don't give it access to all your repos).
3. **Permissions** -> **Repository permissions** -> **Actions**: set to **Read and write**.
4. Set an expiration (e.g. 1 year - fine-grained tokens can't be set to "no expiration"; put a reminder to renew it).
5. Generate, then **copy the token immediately** (starts with `github_pat_...`) - GitHub won't show it again.

Store it somewhere safe (password manager). Treat it like a password.

---

## 6. Set up cron-jobs.org

1. Sign up / log in at cron-jobs.org.
2. **Create cronjob**.
3. **Title**: `Office check-in trigger`.
4. **URL**:
   ```
   https://api.github.com/repos/duggitharun909-cmyk/automated_checkin/actions/workflows/checkin.yml/dispatches
   ```
5. **Request method**: `POST`.
6. **Request headers** (add each as a name/value pair):
   ```
   Accept: application/vnd.github+json
   Authorization: Bearer YOUR_GITHUB_TOKEN_HERE
   Content-Type: application/json
   ```
7. **Request body** (raw JSON):
   ```json
   {"ref":"main"}
   ```
8. **Schedule**: every weekday (Mon-Fri), once daily at **09:25** in your local timezone - set the timezone explicitly in cron-jobs.org's settings (e.g. `Asia/Kolkata`) so it doesn't default to UTC. 09:25 gives a 5-minute buffer before the 09:30 window opens, covering cron-jobs.org's own scheduling jitter.
9. Save and enable the job.

A successful trigger returns HTTP `204 No Content` with an empty body - that's correct, not an error. cron-jobs.org's execution history will show the response code for each run so you can confirm it's firing.

---

## 7. End-to-end verification

1. Manually trigger the cron-jobs.org job once (most dashboards have a "Run now" / "Test run" button) and confirm:
   - cron-jobs.org shows a `204` response.
   - GitHub **Actions** tab shows a new run starting.
   - The run completes and checks in (or reports already-checked-in).
2. Let it run on its own the next weekday morning and check the Actions tab afterward.

---

## Notes

- **Weekends are already handled** - `checkin.py` skips Saturday/Sunday on its own, so it's safe to just leave the cron-jobs.org schedule running Mon-Fri (or even 7 days a week as a backup - the weekend guard will just skip and exit cleanly).
- **Already-checked-in is safe** - the script detects an existing "Working" status and won't double check-in or accidentally check you out.
- **Token expiry** - fine-grained PATs expire; when yours does, the cron-jobs.org job will start getting `401 Unauthorized` responses. Generate a new token and update the `Authorization` header in the cron-jobs.org job.
- **`scheduler.py`** (the local daemon) and this GitHub Actions setup do the same job in two different places. Once the cloud version is verified working, you can stop running `scheduler.py` locally to avoid double check-ins.
