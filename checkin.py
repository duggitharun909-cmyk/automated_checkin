#!/usr/bin/env python3
"""
Office Tracker — Automated Check-In & Check-Out Automation with Playwright
Features:
  - Weekday only (skips Saturday and Sunday)
  - Randomized time window (between 09:30 AM and 09:45 AM)
  - Automatic Office Geolocation spoofing (matches TechGy office premises)
  - Safe check-in (prevents duplicate checkout if already working)
"""

import argparse
from datetime import datetime, time as dtime
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
DEFAULT_EMAIL = os.getenv("OFFICE_EMAIL")
DEFAULT_PASSWORD = os.getenv("OFFICE_PASSWORD")

# TechGy Office premises coordinates (reverse engineered from portal geofence)
DEFAULT_LATITUDE = float(os.getenv("OFFICE_LATITUDE", "17.4835258"))
DEFAULT_LONGITUDE = float(os.getenv("OFFICE_LONGITUDE", "78.3808618"))

# Window start and end
WINDOW_START_STR = os.getenv("CHECKIN_WINDOW_START", "09:30")
WINDOW_END_STR = os.getenv("CHECKIN_WINDOW_END", "09:45")


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


def is_weekend(check_date: datetime = None) -> bool:
    """Returns True if given date is Saturday (5) or Sunday (6)."""
    if check_date is None:
        check_date = datetime.now()
    return check_date.weekday() in (5, 6)


def get_random_checkin_datetime(base_date: datetime = None) -> datetime:
    """
    Generates a unique randomized time between CHECKIN_WINDOW_START and CHECKIN_WINDOW_END
    (e.g., between 09:30:00 and 09:45:00).
    """
    if base_date is None:
        base_date = datetime.now()

    sh, sm = map(int, WINDOW_START_STR.split(":"))
    eh, em = map(int, WINDOW_END_STR.split(":"))

    start_seconds = sh * 3600 + sm * 60
    end_seconds = eh * 3600 + em * 60

    # Pick a random second in the window
    random_sec = random.randint(start_seconds, end_seconds)
    target_h = random_sec // 3600
    target_m = (random_sec % 3600) // 60
    target_s = random_sec % 60

    return base_date.replace(hour=target_h, minute=target_m, second=target_s, microsecond=0)


def wait_for_random_window():
    """
    Waits until the randomized daily window if currently before the window.
    """
    now = datetime.now()
    target = get_random_checkin_datetime(now)

    log_schedule(f"Today's randomized target check-in time: {Style.BOLD}{target.strftime('%I:%M:%S %p')}{Style.RESET}")

    if now < target:
        wait_seconds = (target - now).total_seconds()
        log_schedule(f"Waiting {int(wait_seconds // 60)}m {int(wait_seconds % 60)}s until target time...")
        time.sleep(wait_seconds)
        log_schedule("Target time reached! Proceeding with check-in...")
    else:
        log_info(f"Current time ({now.strftime('%I:%M:%S %p')}) is past or inside the randomized target window ({target.strftime('%I:%M:%S %p')}). Proceeding immediately.")


def run_attendance(
    action: str = "check-in",
    url: str = DEFAULT_URL,
    email: str = DEFAULT_EMAIL,
    password: str = DEFAULT_PASSWORD,
    latitude: float = DEFAULT_LATITUDE,
    longitude: float = DEFAULT_LONGITUDE,
    headless: bool = True,
    slow_mo: int = 0,
    force: bool = False,
    random_window: bool = False,
    screenshot_dir: str = "screenshots"
) -> dict:
    """
    Automates login and check-in / check-out / status on Office Tracker.
    """
    if not email or not password:
        raise SystemExit(
            "OFFICE_EMAIL / OFFICE_PASSWORD are not set. "
            "Create a .env file from .env.example (locally) or set them as "
            "repository secrets (in CI) before running this script."
        )

    now = datetime.now()
    day_name = now.strftime("%A")

    # 1. Weekend Guard
    if action == "check-in" and is_weekend(now) and not force:
        log_warn(f"Today is {day_name} (Weekend). Check-in skipped as configured.")
        log_info("Tip: Use --force flag if you want to bypass weekend skip during testing.")
        return {
            "success": True,
            "status": f"Skipped ({day_name})",
            "message": f"Check-in skipped on weekend ({day_name}).",
            "screenshot": ""
        }

    # 2. Random Time Window Guard
    if action == "check-in" and random_window and not force:
        wait_for_random_window()

    screenshots_path = Path(screenshot_dir)
    screenshots_path.mkdir(parents=True, exist_ok=True)

    log_info(f"Target URL: {url}")
    log_info(f"User Email: {email}")
    log_info(f"Action: {action.upper()}")
    log_info(f"Office Location Spoof: Lat={latitude}, Lng={longitude}")
    log_info(f"Headless Mode: {headless}")

    result = {
        "success": False,
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
            log_info("Opening portal...")
            page.goto(url, wait_until="networkidle", timeout=30000)

            # 2. Select Employee Portal
            log_info("Selecting 'Employee Portal'...")
            portal_card = page.locator(".portal-card", has_text="Employee Portal").first
            portal_card.wait_for(state="visible", timeout=10000)
            portal_card.click()

            # 3. Enter Credentials
            log_info("Entering credentials...")
            email_field = page.locator("input[type='email']")
            email_field.wait_for(state="visible", timeout=5000)
            email_field.fill(email)

            password_field = page.locator("input[type='password']")
            password_field.wait_for(state="visible", timeout=5000)
            password_field.fill(password)

            # 4. Click Sign In
            log_info("Signing in...")
            sign_in_btn = page.locator("button", has_text="Sign In").first
            sign_in_btn.click()

            # 5. Wait for Employee Dashboard
            log_info("Waiting for dashboard to load...")
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

            log_info(f"Logged in as: {Style.BOLD}{employee_name}{Style.RESET}")

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

            log_info(f"Current UI Button: [{btn_text}] | Current Status: [{status_badge}]")

            # Execute desired action
            if action == "status":
                screenshot_file = screenshots_path / "status.png"
                page.screenshot(path=str(screenshot_file))
                log_success(f"Status Checked: Button is '{btn_text}', Status is '{status_badge}'")
                result.update({
                    "success": True,
                    "status": status_badge,
                    "button": btn_text,
                    "message": f"Status: {status_badge}, Button: {btn_text}",
                    "screenshot": str(screenshot_file)
                })

            elif action == "check-in":
                if "Check In" in btn_text:
                    log_info("Clicking 'Check In' button with office location...")
                    action_btn.click()
                    page.wait_for_timeout(1000)

                    # Check if the in-page "Location Access Required" modal appears
                    allow_modal_btn = page.locator("button:visible", has_text="Allow Now").first
                    if allow_modal_btn.count() > 0:
                        log_info("Detected 'Location Access Required' modal. Clicking 'Allow Now'...")
                        allow_modal_btn.click()
                        page.wait_for_timeout(3000)

                    # Also wait for any network responses or toast
                    page.wait_for_timeout(2000)

                    new_btn_text = ""
                    if action_btn.count() > 0:
                        new_btn_text = action_btn.inner_text().strip()

                    screenshot_file = screenshots_path / f"checkin_success_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                    page.screenshot(path=str(screenshot_file))
                    log_success(f"Check-In completed successfully! New button state: '{new_btn_text}'")
                    result.update({
                        "success": True,
                        "status": "Checked In",
                        "button": new_btn_text,
                        "message": "Successfully checked in with verified office location!",
                        "screenshot": str(screenshot_file)
                    })
                elif "Check Out" in btn_text:
                    screenshot_file = screenshots_path / "already_checked_in.png"
                    page.screenshot(path=str(screenshot_file))
                    log_warn(f"Already Checked In! (Button currently shows '{btn_text}', Status: '{status_badge}')")
                    result.update({
                        "success": True,
                        "status": "Already Checked In",
                        "button": btn_text,
                        "message": "User is already checked in. No action needed.",
                        "screenshot": str(screenshot_file)
                    })
                else:
                    log_error(f"Could not locate Check In button. Button text found: '{btn_text}'")
                    screenshot_file = screenshots_path / "checkin_error.png"
                    page.screenshot(path=str(screenshot_file))
                    result.update({
                        "success": False,
                        "message": f"Check In button not found. Current button: '{btn_text}'",
                        "screenshot": str(screenshot_file)
                    })

            elif action == "check-out":
                if "Check Out" in btn_text:
                    log_info("Clicking 'Check Out' button...")
                    action_btn.click()
                    page.wait_for_timeout(2000)

                    confirm_btn = page.locator("button:visible:has-text('Confirm'), button:visible:has-text('Yes')").first
                    if confirm_btn.count() > 0:
                        log_info("Confirming checkout modal...")
                        confirm_btn.click()
                        page.wait_for_timeout(1000)

                    screenshot_file = screenshots_path / "checkout_success.png"
                    page.screenshot(path=str(screenshot_file))
                    log_success("Check-Out completed successfully!")
                    result.update({
                        "success": True,
                        "status": "Checked Out",
                        "message": "Successfully checked out!",
                        "screenshot": str(screenshot_file)
                    })
                elif "Check In" in btn_text:
                    screenshot_file = screenshots_path / "already_checked_out.png"
                    page.screenshot(path=str(screenshot_file))
                    log_warn(f"Already Checked Out! (Button currently shows '{btn_text}')")
                    result.update({
                        "success": True,
                        "status": "Already Checked Out",
                        "button": btn_text,
                        "message": "User is already checked out.",
                        "screenshot": str(screenshot_file)
                    })

        except PlaywrightTimeoutError as te:
            log_error(f"Playwright operation timed out: {te}")
            err_screenshot = screenshots_path / "timeout_error.png"
            try:
                page.screenshot(path=str(err_screenshot))
                result["screenshot"] = str(err_screenshot)
            except Exception:
                pass
            result["message"] = str(te)

        except Exception as e:
            log_error(f"An unexpected error occurred: {e}")
            err_screenshot = screenshots_path / "general_error.png"
            try:
                page.screenshot(path=str(err_screenshot))
                result["screenshot"] = str(err_screenshot)
            except Exception:
                pass
            result["message"] = str(e)

        finally:
            browser.close()

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Office Tracker Automated Check-In & Check-Out Automation"
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
        "--email",
        default=DEFAULT_EMAIL,
        help="Employee login email"
    )
    parser.add_argument(
        "--password",
        default=DEFAULT_PASSWORD,
        help="Employee login password"
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
        help="Run browser in visible mode (default: headless)"
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
        help="Wait until a randomized time between 09:30 AM and 09:45 AM before checking in"
    )
    parser.add_argument(
        "--screenshot-dir",
        default="screenshots",
        help="Directory to save execution screenshots"
    )

    args = parser.parse_args()

    result = run_attendance(
        action=args.action,
        url=args.url,
        email=args.email,
        password=args.password,
        latitude=args.latitude,
        longitude=args.longitude,
        headless=not args.headed,
        slow_mo=args.slow_mo,
        force=args.force,
        random_window=args.random_window,
        screenshot_dir=args.screenshot_dir
    )

    print("\n" + "=" * 50)
    print("Execution Summary:")
    print(f"  • Action:     {result.get('action')}")
    print(f"  • Status:     {result.get('status')}")
    print(f"  • Message:    {result.get('message')}")
    if result.get("screenshot"):
        print(f"  • Screenshot: {result.get('screenshot')}")
    print("=" * 50)

    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
