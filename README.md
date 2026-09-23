# Office Tracker — Automated Check-In & Check-Out

Python Playwright automation script for **TechGy Innovations Office Tracker** (`https://office-tracker-1.vercel.app/login`).

---

## 🚀 Key Features

1. **Weekend Skip**:
   - Automatically excludes **Saturdays and Sundays** from check-in.
   - Runs exclusively on workdays (Monday through Friday).
   - Use `--force` to test or override on weekends if needed.

2. **Randomized Daily Check-In Window (09:30 AM – 09:45 AM)**:
   - Eliminates predictable patterns. Every single day a random time is chosen (e.g. 09:23:41 AM, 09:37:12 AM, 09:28:05 AM).
   - No two days will have the exact same check-in timestamp.

3. **Office Location Emulation (Geofencing)**:
   - The portal enforces a 2000m radius check around the office (`Lat 17.4835258`, `Lng 78.3808618`).
   - Automatically injects office coordinates and grants geolocation permissions in Playwright so check-in passes reliably anywhere.

4. **Safety & Duplicate Protection**:
   - Detects if you are already checked in (`Working` status).
   - Will **not** accidentally check you out if you trigger the check-in script while already working.

5. **Screenshots & Reporting**:
   - Takes timestamped screenshots of every execution into `screenshots/`.

---

## 🛠️ Project Structure

```
Automating_Checkin/
├── .env                # Credentials & office coordinates (keep secret)
├── .env.example        # Configuration template
├── .gitignore          # Excludes .env, virtual environments & logs
├── requirements.txt    # Dependencies (playwright, python-dotenv)
├── checkin.py          # Core Playwright automation script
├── scheduler.py        # Background daily scheduler daemon
└── screenshots/        # Auto-saved verification screenshots
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

### 2. Configure `.env`

Copy `.env.example` to `.env` and fill in your own values (never commit this file):
```env
PORTAL_URL=https://office-tracker-1.vercel.app/login
OFFICE_EMAIL=your_email@example.com
OFFICE_PASSWORD=your_password_here

OFFICE_LATITUDE=17.4835258
OFFICE_LONGITUDE=78.3808618

CHECKIN_WINDOW_START=09:30
CHECKIN_WINDOW_END=09:45
```

---

## 💻 Usage Commands

### 1. Run Check-In Directly

```bash
.venv/bin/python checkin.py --action check-in
```
> Skips Saturday/Sunday automatically. If already checked in, alerts safely.

### 2. Run with Randomized 09:30 – 09:45 AM Window Wait

```bash
.venv/bin/python checkin.py --action check-in --random-window
```
> If started before the window, calculates today's random time and waits before checking in.

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
