# Office Tracker — Automated Check-In & Check-Out

Python Playwright automation script for **TechGy Innovations Office Tracker** (`https://office-tracker-1.vercel.app/login`).

---

## 🚀 Key Features

1. **Multiple Users, Checked In Together**:
   - Configure any number of accounts in `users.json` (see `users.json.example`).
   - All of them are checked in **in parallel** (one browser per user), so nobody's check-in lags behind because they were later in a list.

2. **Weekend Skip**:
   - Automatically excludes **Saturdays and Sundays** from check-in.
   - Runs exclusively on workdays (Monday through Friday).
   - Use `--force` to test or override on weekends if needed.

3. **Randomized Daily Check-In Window (09:32 AM – 09:48 AM)**:
   - Eliminates predictable patterns. Every user gets their own random, unique second inside the window (e.g. alice at 09:34:52 AM, bob at 09:43:46 AM) - never the same instant twice, and never the same as another user.
   - Each user's thread waits independently for its own assigned time before checking in, so the group still runs in parallel (see `--random-window` below).

4. **Office Location Emulation (Geofencing)**:
   - The portal enforces a 2000m radius check around the office (`Lat 17.4835258`, `Lng 78.3808618`).
   - Automatically injects office coordinates and grants geolocation permissions in Playwright so check-in passes reliably anywhere.

5. **Safety & Duplicate Protection**:
   - Detects if a user is already checked in (`Working` status).
   - Will **not** accidentally check anyone out if the check-in script is triggered while they're already working.

6. **Screenshots & Reporting**:
   - Takes a timestamped screenshot per user, per execution, into `screenshots/`.

---

## 🛠️ Project Structure

```
Automating_Checkin/
├── .env                # Shared settings: portal URL, office coordinates, window (keep secret)
├── .env.example         # Configuration template
├── users.json           # Per-user logins - name/email/password list (keep secret, gitignored)
├── users.json.example   # users.json template
├── .gitignore           # Excludes .env, users.json, virtual environments & logs
├── requirements.txt     # Dependencies (playwright, python-dotenv)
├── checkin.py           # Core Playwright automation script (multi-user, parallel)
├── scheduler.py         # Background daily scheduler daemon
└── screenshots/         # Auto-saved verification screenshots, one per user per run
```

---

## 📦 Setup & Installation

### 1. Create Virtual Environment & Install Dependencies

```bash
# Using uv (fastest)
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
playwright install chromium

# Or standard Python
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure `.env` (shared settings)

Copy `.env.example` to `.env` and fill in your own values (never commit this file):
```env
PORTAL_URL=https://office-tracker-1.vercel.app/login

OFFICE_LATITUDE=17.4835258
OFFICE_LONGITUDE=78.3808618

CHECKIN_WINDOW_START=09:32
CHECKIN_WINDOW_END=09:48
```

### 3. Configure `users.json` (one entry per person)

Copy `users.json.example` to `users.json` and fill in real accounts (never commit this file):
```json
[
  { "name": "alice", "email": "alice@example.com", "password": "her_password" },
  { "name": "bob", "email": "bob@example.com", "password": "his_password" }
]
```
Every user in this file is checked in **in parallel** whenever `checkin.py` runs. `name` is just a label used in logs/screenshots (defaults to the email if omitted).

In CI (GitHub Actions), skip the file and set an `OFFICE_USERS` secret containing the same JSON as a single line instead - see `githubsetup.md`.

---

## 💻 Usage Commands

### 1. Run Check-In Directly

```bash
.venv/bin/python checkin.py --action check-in
```
> Skips Saturday/Sunday automatically. If already checked in, alerts safely.

### 2. Run with Randomized 09:32 – 09:48 AM Window Wait

```bash
.venv/bin/python checkin.py --action check-in --random-window
```
> Assigns each user in `users.json` their own unique random time in the window, then waits (per user, in parallel) before checking them in.

### 3. Check Current Attendance Status

```bash
.venv/bin/python checkin.py --action status
```

### 4. Check Out

```bash
.venv/bin/python checkin.py --action check-out
```

### 5. Preview Upcoming Randomized Schedule (Next 7 Days)

```bash
.venv/bin/python scheduler.py --preview
```

### 6. Run Continuous Daily Scheduler (Daemon Mode)

```bash
.venv/bin/python scheduler.py
```
> Keeps running in the background. Handles daily randomized timing and weekend skipping automatically.

---

## 🖥️ Headed Mode (Watch Browser Live)

Add `--headed` and optional `--slow-mo` to observe the browser perform the login and check-in:
```bash
.venv/bin/python checkin.py --action check-in --headed --slow-mo 500 --force
```
