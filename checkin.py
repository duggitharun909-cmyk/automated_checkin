#!/usr/bin/env python3
"""
Office Tracker — Automated Check-In & Check-Out Automation with Playwright
Features:
  - Multiple users, checked in concurrently (see users.json.example)
  - Weekday only (skips Saturday and Sunday)
  - Each user gets their own random, unique check-in second inside the window
    (default 09:32-09:48); every user's thread waits for its own time, then acts
  - Automatic Office Geolocation spoofing (matches TechGy office premises)
  - Safe check-in (prevents duplicate checkout if already working)
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Load configuration from .env file
load_dotenv()

DEFAULT_URL = os.getenv("PORTAL_URL", "https://office-tracker-1.vercel.app/login")

# TechGy Office premises coordinates (reverse engineered from portal geofence)
DEFAULT_LATITUDE = float(os.getenv("OFFICE_LATITUDE", "17.4835258"))
DEFAULT_LONGITUDE = float(os.getenv("OFFICE_LONGITUDE", "78.3808618"))

# Window start and end
WINDOW_START_STR = os.getenv("CHECKIN_WINDOW_START", "09:32")
WINDOW_END_STR = os.getenv("CHECKIN_WINDOW_END", "09:48")


class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[32m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    MAGENTA = "\033[35m"


def log_info(msg: str):
    print(f"{Style.CYAN}[INFO]{Style.RESET} {msg}")

def log_success(msg: str):
    print(f"{Style.GREEN}{Style.BOLD}[SUCCESS]{Style.RESET} {msg}")

def log_warn(msg: str):
    print(f"{Style.YELLOW}[WARNING]{Style.RESET} {msg}")

def log_error(msg: str):
    print(f"{Style.RED}{Style.BOLD}[ERROR]{Style.RESET} {msg}")

def log_schedule(msg: str):
    print(f"{Style.MAGENTA}{Style.BOLD}[SCHEDULE]{Style.RESET} {msg}")


class Logger:
    """Per-user logger: prefixes every line with the user's label so parallel output stays readable."""

    def __init__(self, label: str):
        self.prefix = f"{Style.BOLD}[{label}]{Style.RESET} "

    def info(self, msg): print(f"{self.prefix}{Style.CYAN}[INFO]{Style.RESET} {msg}")
    def success(self, msg): print(f"{self.prefix}{Style.GREEN}{Style.BOLD}[SUCCESS]{Style.RESET} {msg}")
    def warn(self, msg): print(f"{self.prefix}{Style.YELLOW}[WARNING]{Style.RESET} {msg}")
    def error(self, msg): print(f"{self.prefix}{Style.RED}{Style.BOLD}[ERROR]{Style.RESET} {msg}")


def load_users() -> list:
    """
    Loads the accounts to check in, as a list of {"name", "email", "password"} dicts.
    Source priority:
      1. OFFICE_USERS env var - a JSON array (used for the GitHub Actions secret).
      2. users.json file (or OFFICE_USERS_FILE path) - convenient for local runs.
    See users.json.example for the expected format.
    """
    raw_json = os.getenv("OFFICE_USERS")
    source = "OFFICE_USERS environment variable"

    if not raw_json:
        users_file = Path(os.getenv("OFFICE_USERS_FILE", "users.json"))
        source = str(users_file)
        if not users_file.exists():
            return []
        raw_json = users_file.read_text()

    try:
        users = json.loads(raw_json)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Could not parse user list from {source}: {e}")

    for u in users:
        if not u.get("email") or not u.get("password"):
            raise SystemExit(f"Each user entry needs a non-empty 'email' and 'password'. Bad entry: {u}")
        u.setdefault("name", u["email"])

    return users


def is_weekend(check_date: datetime = None) -> bool:
    """Returns True if given date is Saturday (5) or Sunday (6)."""
    if check_date is None:
        check_date = datetime.now()
    return check_date.weekday() in (5, 6)


def assign_unique_checkin_times(count: int, base_date: datetime = None) -> list:
    """
    Picks `count` distinct random seconds inside CHECKIN_WINDOW_START-CHECKIN_WINDOW_END
    (e.g., 09:32:00-09:48:00) and returns them as datetimes for base_date's day - one per
    user, so no two users land on the exact same second.
    """
    if base_date is None:
        base_date = datetime.now()

    sh, sm = map(int, WINDOW_START_STR.split(":"))
    eh, em = map(int, WINDOW_END_STR.split(":"))

    start_seconds = sh * 3600 + sm * 60
    end_seconds = eh * 3600 + em * 60
    window_size = end_seconds - start_seconds + 1

    if count > window_size:
        raise SystemExit(
            f"Check-in window ({WINDOW_START_STR}-{WINDOW_END_STR}) only has {window_size} "
            f"distinct seconds, not enough to assign {count} unique user times. "
            "Widen CHECKIN_WINDOW_START/CHECKIN_WINDOW_END."
        )

    chosen_seconds = random.sample(range(start_seconds, end_seconds + 1), count)
    return [
        base_date.replace(hour=s // 3600, minute=(s % 3600) // 60, second=s % 60, microsecond=0)
        for s in chosen_seconds
    ]


def perform_action(
    action: str,
    url: str,
    email: str,
    password: str,
    latitude: float,
    longitude: float,
    headless: bool,
    slow_mo: int,
    screenshot_dir: str,
    label: str,
    wait_until: datetime = None,
) -> dict:
    """
    Runs one browser session: login + check-in / check-out / status, for a single user.
    Safe to run concurrently with other calls to this function (each gets its own browser).
    If `wait_until` is set, sleeps until that exact moment before doing anything else -
    each thread waits for its own target time independently.
    """
    logger = Logger(label)
    safe_label = re.sub(r"[^A-Za-z0-9_.-]", "_", label)

    if wait_until:
        now = datetime.now()
        if now < wait_until:
            wait_seconds = (wait_until - now).total_seconds()
            logger.info(f"Assigned check-in time: {Style.BOLD}{wait_until.strftime('%I:%M:%S %p')}{Style.RESET} (waiting {int(wait_seconds // 60)}m {int(wait_seconds % 60)}s)...")
            time.sleep(wait_seconds)
        logger.info(f"Target time reached ({datetime.now().strftime('%I:%M:%S %p')}). Proceeding...")

    screenshots_path = Path(screenshot_dir)
    screenshots_path.mkdir(parents=True, exist_ok=True)

    logger.info(f"Target URL: {url}")
    logger.info(f"User Email: {email}")
    logger.info(f"Action: {action.upper()}")
    logger.info(f"Office Location Spoof: Lat={latitude}, Lng={longitude}")
    logger.info(f"Headless Mode: {headless}")

    result = {
        "success": False,
        "label": label,
        "email": email,
        "action": action,
        "status": "Unknown",
        "message": "",
        "screenshot": ""
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=slow_mo)

        # Configure context with Office premises geolocation and granted permissions
        context = browser.new_context(
            permissions=["geolocation"],
            geolocation={"latitude": latitude, "longitude": longitude},
            viewport={"width": 1280, "height": 850},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            # 1. Open Portal Login Page
            logger.info("Opening portal...")
            page.goto(url, wait_until="networkidle", timeout=30000)

            # 2. Select Employee Portal
            logger.info("Selecting 'Employee Portal'...")
            portal_card = page.locator(".portal-card", has_text="Employee Portal").first
            portal_card.wait_for(state="visible", timeout=10000)
            portal_card.click()

            # 3. Enter Credentials
            logger.info("Entering credentials...")
            email_field = page.locator("input[type='email']")
            email_field.wait_for(state="visible", timeout=5000)
            email_field.fill(email)

            password_field = page.locator("input[type='password']")
            password_field.wait_for(state="visible", timeout=5000)
            password_field.fill(password)

            # 4. Click Sign In
            logger.info("Signing in...")
            sign_in_btn = page.locator("button", has_text="Sign In").first
            sign_in_btn.click()

            # 5. Wait for Employee Dashboard
            logger.info("Waiting for dashboard to load...")
            page.wait_for_url("**/employee**", timeout=15000)
            page.wait_for_load_state("networkidle", timeout=10000)
            time.sleep(1)

            # 6. Extract Employee & Attendance Information
            employee_name = "Employee"
            try:
                emp_card = page.locator("div:has-text('Developer')").first
                card_text = emp_card.inner_text()
                lines = [line.strip() for line in card_text.split("\n") if line.strip()]
                if lines:
                    employee_name = lines[0]
            except Exception:
                pass

            logger.info(f"Logged in as: {Style.BOLD}{employee_name}{Style.RESET}")

            # 7. Locate Action Button & Status
            check_regex = re.compile(r"Check\s*(In|Out)", re.IGNORECASE)
            action_btn = page.locator("button:visible").filter(has_text=check_regex).first
            btn_text = ""
            if action_btn.count() > 0:
                btn_text = action_btn.inner_text().strip()

            status_badge = "Unknown"
            status_badge_loc = page.locator("button:visible:has-text('Working'), button:visible:has-text('Break')").first
            if status_badge_loc.count() > 0:
                status_badge = status_badge_loc.inner_text().strip()

            logger.info(f"Current UI Button: [{btn_text}] | Current Status: [{status_badge}]")

            # Execute desired action
            if action == "status":
                screenshot_file = screenshots_path / f"status_{safe_label}.png"
                page.screenshot(path=str(screenshot_file))
                logger.success(f"Status Checked: Button is '{btn_text}', Status is '{status_badge}'")
                result.update({
                    "success": True,
                    "status": status_badge,
                    "button": btn_text,
                    "message": f"Status: {status_badge}, Button: {btn_text}",
                    "screenshot": str(screenshot_file)
                })

            elif action == "check-in":
                if "Check In" in btn_text:
                    logger.info("Clicking 'Check In' button with office location...")
                    action_btn.click()
                    page.wait_for_timeout(1000)

                    # Check if the in-page "Location Access Required" modal appears
                    allow_modal_btn = page.locator("button:visible", has_text="Allow Now").first
                    if allow_modal_btn.count() > 0:
                        logger.info("Detected 'Location Access Required' modal. Clicking 'Allow Now'...")
                        allow_modal_btn.click()
                        page.wait_for_timeout(3000)

                    # Also wait for any network responses or toast
                    page.wait_for_timeout(2000)

                    new_btn_text = ""
                    if action_btn.count() > 0:
                        new_btn_text = action_btn.inner_text().strip()

                    screenshot_file = screenshots_path / f"checkin_success_{safe_label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                    page.screenshot(path=str(screenshot_file))
                    logger.success(f"Check-In completed successfully! New button state: '{new_btn_text}'")
                    result.update({
                        "success": True,
                        "status": "Checked In",
                        "button": new_btn_text,
                        "message": "Successfully checked in with verified office location!",
                        "screenshot": str(screenshot_file)
                    })
                elif "Check Out" in btn_text:
                    screenshot_file = screenshots_path / f"already_checked_in_{safe_label}.png"
                    page.screenshot(path=str(screenshot_file))
                    logger.warn(f"Already Checked In! (Button currently shows '{btn_text}', Status: '{status_badge}')")
                    result.update({
                        "success": True,
                        "status": "Already Checked In",
                        "button": btn_text,
                        "message": "User is already checked in. No action needed.",
                        "screenshot": str(screenshot_file)
                    })
                else:
                    logger.error(f"Could not locate Check In button. Button text found: '{btn_text}'")
                    screenshot_file = screenshots_path / f"checkin_error_{safe_label}.png"
                    page.screenshot(path=str(screenshot_file))
                    result.update({
                        "success": False,
                        "message": f"Check In button not found. Current button: '{btn_text}'",
                        "screenshot": str(screenshot_file)
                    })

            elif action == "check-out":
                if "Check Out" in btn_text:
                    logger.info("Clicking 'Check Out' button...")
                    action_btn.click()
                    page.wait_for_timeout(2000)

                    confirm_btn = page.locator("button:visible:has-text('Confirm'), button:visible:has-text('Yes')").first
                    if confirm_btn.count() > 0:
                        logger.info("Confirming checkout modal...")
                        confirm_btn.click()
                        page.wait_for_timeout(1000)

                    screenshot_file = screenshots_path / f"checkout_success_{safe_label}.png"
                    page.screenshot(path=str(screenshot_file))
                    logger.success("Check-Out completed successfully!")
                    result.update({
                        "success": True,
                        "status": "Checked Out",
                        "message": "Successfully checked out!",
                        "screenshot": str(screenshot_file)
                    })
                elif "Check In" in btn_text:
                    screenshot_file = screenshots_path / f"already_checked_out_{safe_label}.png"
                    page.screenshot(path=str(screenshot_file))
                    logger.warn(f"Already Checked Out! (Button currently shows '{btn_text}')")
                    result.update({
                        "success": True,
                        "status": "Already Checked Out",
                        "button": btn_text,
                        "message": "User is already checked out.",
                        "screenshot": str(screenshot_file)
                    })

        except PlaywrightTimeoutError as te:
            logger.error(f"Playwright operation timed out: {te}")
            err_screenshot = screenshots_path / f"timeout_error_{safe_label}.png"
            try:
                page.screenshot(path=str(err_screenshot))
                result["screenshot"] = str(err_screenshot)
            except Exception:
                pass
            result["message"] = str(te)

        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}")
            err_screenshot = screenshots_path / f"general_error_{safe_label}.png"
            try:
                page.screenshot(path=str(err_screenshot))
                result["screenshot"] = str(err_screenshot)
            except Exception:
                pass
            result["message"] = str(e)

        finally:
            browser.close()

    return result


def run_attendance(
    users: list,
    action: str = "check-in",
    url: str = DEFAULT_URL,
    latitude: float = DEFAULT_LATITUDE,
    longitude: float = DEFAULT_LONGITUDE,
    headless: bool = True,
    slow_mo: int = 0,
    force: bool = False,
    random_window: bool = False,
    screenshot_dir: str = "screenshots",
    max_workers: int = None,
) -> dict:
    """
    Runs the given action for every user in `users`, in parallel (one browser per user).
    When `random_window` is set, each user is assigned their own random, unique second
    inside the check-in window, and their thread waits independently for it - so everyone
    still checks in around the same window, but not at an identical, easily-flagged instant.
    """
    if not users:
        raise SystemExit(
            "No users configured. Set the OFFICE_USERS environment variable (JSON array) "
            "or create users.json from users.json.example before running this script."
        )

    now = datetime.now()
    day_name = now.strftime("%A")

    # 1. Weekend Guard (checked once for the whole group)
    if action == "check-in" and is_weekend(now) and not force:
        log_warn(f"Today is {day_name} (Weekend). Check-in skipped as configured.")
        log_info("Tip: Use --force flag if you want to bypass weekend skip during testing.")
        return {
            "success": True,
            "status": f"Skipped ({day_name})",
            "message": f"Check-in skipped on weekend ({day_name}).",
            "results": [],
        }

    # 2. Assign each user their own unique random target time in the window
    if action == "check-in" and random_window and not force:
        targets = assign_unique_checkin_times(len(users), now)
        log_schedule(f"Assigned unique check-in times within {WINDOW_START_STR}-{WINDOW_END_STR}:")
        for u, t in zip(users, targets):
            log_schedule(f"  {u['name']}: {Style.BOLD}{t.strftime('%I:%M:%S %p')}{Style.RESET}")
    else:
        targets = [None] * len(users)

    log_info(f"Running '{action}' for {len(users)} user(s) in parallel...")

    results = []
    with ThreadPoolExecutor(max_workers=max_workers or len(users)) as executor:
        future_to_user = {
            executor.submit(
                perform_action,
                action=action,
                url=url,
                email=u["email"],
                password=u["password"],
                latitude=latitude,
                longitude=longitude,
                headless=headless,
                slow_mo=slow_mo,
                screenshot_dir=screenshot_dir,
                label=u["name"],
                wait_until=t,
            ): u
            for u, t in zip(users, targets)
        }
        for future in as_completed(future_to_user):
            u = future_to_user[future]
            try:
                results.append(future.result())
            except Exception as e:
                log_error(f"[{u['name']}] Unhandled error: {e}")
                results.append({
                    "success": False,
                    "label": u["name"],
                    "email": u["email"],
                    "action": action,
                    "status": "Error",
                    "message": str(e),
                    "screenshot": "",
                })

    succeeded = sum(1 for r in results if r["success"])
    return {
        "success": all(r["success"] for r in results),
        "status": "Completed",
        "message": f"{succeeded}/{len(results)} succeeded",
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Office Tracker Automated Check-In & Check-Out Automation (multi-user)"
    )
    parser.add_argument(
        "--action",
        choices=["check-in", "check-out", "status"],
        default="check-in",
        help="Action to perform (default: check-in)"
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="Portal URL"
    )
    parser.add_argument(
        "--latitude",
        type=float,
        default=DEFAULT_LATITUDE,
        help="Office latitude (default: 17.4835258)"
    )
    parser.add_argument(
        "--longitude",
        type=float,
        default=DEFAULT_LONGITUDE,
        help="Office longitude (default: 78.3808618)"
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run browsers in visible mode (default: headless)"
    )
    parser.add_argument(
        "--slow-mo",
        type=int,
        default=0,
        help="Slow down Playwright actions by milliseconds"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force execution even on Saturday/Sunday or outside time window"
    )
    parser.add_argument(
        "--random-window",
        action="store_true",
        help="Assign each user their own unique random time between 09:32 AM and 09:48 AM and wait for it before checking them in"
    )
    parser.add_argument(
        "--screenshot-dir",
        default="screenshots",
        help="Directory to save execution screenshots"
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="Max browsers to run at once (default: one per user, fully parallel)"
    )

    args = parser.parse_args()

    users = load_users()

    result = run_attendance(
        users=users,
        action=args.action,
        url=args.url,
        latitude=args.latitude,
        longitude=args.longitude,
        headless=not args.headed,
        slow_mo=args.slow_mo,
        force=args.force,
        random_window=args.random_window,
        screenshot_dir=args.screenshot_dir,
        max_workers=args.max_workers,
    )

    print("\n" + "=" * 60)
    print("Execution Summary:")
    print(f"  • Status:  {result.get('status')}")
    print(f"  • Message: {result.get('message')}")
    for r in result.get("results", []):
        marker = "OK  " if r.get("success") else "FAIL"
        print(f"  [{marker}] {r.get('label')}: {r.get('status')} - {r.get('message')}")
        if r.get("screenshot"):
            print(f"           screenshot: {r.get('screenshot')}")
    print("=" * 60)

    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
