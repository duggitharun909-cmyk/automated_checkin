#!/usr/bin/env python3
"""
Office Tracker — Automated Daily Scheduler
Features:
  - Automatically skips Saturdays and Sundays
  - Generates a unique randomized check-in time every weekday between 09:30 AM and 09:45 AM
  - Ensures a different time every day
  - Injects office geolocation coordinates (TechGy office premises)
  - Runs in background or terminal with countdown logging
"""

import argparse
from datetime import datetime, timedelta
import random
import sys
import time
from checkin import (
    run_attendance,
    load_users,
    is_weekend,
    WINDOW_START_STR,
    WINDOW_END_STR,
    DEFAULT_LATITUDE,
    DEFAULT_LONGITUDE,
    Style
)


def get_random_time_for_day(day_date: datetime) -> datetime:
    """
    Computes a random target datetime for a given day between start and end window.
    """
    sh, sm = map(int, WINDOW_START_STR.split(":"))
    eh, em = map(int, WINDOW_END_STR.split(":"))

    start_sec = sh * 3600 + sm * 60
    end_sec = eh * 3600 + em * 60

    rand_sec = random.randint(start_sec, end_sec)
    h = rand_sec // 3600
    m = (rand_sec % 3600) // 60
    s = rand_sec % 60

    return day_date.replace(hour=h, minute=m, second=s, microsecond=0)


def get_next_run_datetime(from_time: datetime = None) -> datetime:
    """
    Calculates the next weekday check-in time.
    If today is a weekday and current time < today's random target, returns today's target.
    Otherwise advances to the next weekday (Monday-Friday) and returns its randomized target.
    """
    if from_time is None:
        from_time = datetime.now()

    # If today is weekday
    if not is_weekend(from_time):
        today_target = get_random_time_for_day(from_time)
        if from_time < today_target:
            return today_target

    # Look for next weekday
    next_day = from_time + timedelta(days=1)
    while is_weekend(next_day):
        next_day += timedelta(days=1)

    return get_random_time_for_day(next_day)


def start_scheduler(headed: bool = False):
    print("=" * 60)
    print(f"{Style.BOLD}🚀 Office Tracker Automated Check-In Daemon Started{Style.RESET}")
    print(f"• Days:           {Style.GREEN}Monday – Friday (Weekends Skipped){Style.RESET}")
    print(f"• Time Window:    {Style.CYAN}{WINDOW_START_STR} AM – {WINDOW_END_STR} AM (Randomized daily){Style.RESET}")
    print(f"• Geolocation:    {Style.YELLOW}Lat {DEFAULT_LATITUDE}, Lng {DEFAULT_LONGITUDE}{Style.RESET}")
    print("=" * 60)

    while True:
        now = datetime.now()

        if is_weekend(now):
            next_run = get_next_run_datetime(now)
            wait_sec = (next_run - now).total_seconds()
            print(f"\n{Style.YELLOW}[WEEKEND]{Style.RESET} Today is {now.strftime('%A')}. Sleeping until Monday morning ({next_run.strftime('%A, %b %d at %I:%M:%S %p')})...")
            # Sleep in intervals or until Monday
            sleep_duration = min(wait_sec, 3600)
            time.sleep(sleep_duration)
            continue

        next_target = get_next_run_datetime(now)

        if now < next_target:
            wait_seconds = (next_target - now).total_seconds()
            hrs = int(wait_seconds // 3600)
            mins = int((wait_seconds % 3600) // 60)
            secs = int(wait_seconds % 60)

            print(f"\n{Style.CYAN}[SCHEDULED]{Style.RESET} Today is {now.strftime('%A, %b %d')}.")
            print(f"👉 Next Check-In Target: {Style.BOLD}{Style.GREEN}{next_target.strftime('%I:%M:%S %p')}{Style.RESET}")
            print(f"⏳ Waiting {hrs}h {mins}m {secs}s...")

            # Sleep until target time
            time.sleep(wait_seconds)

        # Trigger check-in
        print(f"\n{Style.GREEN}{Style.BOLD}[ALARM]{Style.RESET} Check-in time reached ({datetime.now().strftime('%I:%M:%S %p')})! Triggering check-in...")
        try:
            users = load_users()
            res = run_attendance(
                users=users,
                action="check-in",
                headless=not headed,
                force=False
            )
            print(f"[RESULT] {res.get('status')}: {res.get('message')}")
        except Exception as e:
            print(f"{Style.RED}[ERROR]{Style.RESET} Failed to execute check-in: {e}")

        # Sleep past the window so it doesn't trigger again today
        print("Sleeping 1 hour to advance past today's checkin window...")
        time.sleep(3600)


def main():
    parser = argparse.ArgumentParser(description="Office Tracker Automated Daily Scheduler")
    parser.add_argument("--headed", action="store_true", help="Run browser in visible mode")
    parser.add_argument("--preview", action="store_true", help="Preview next 7 days randomized check-in schedule")
    args = parser.parse_args()

    if args.preview:
        print("\n📅 Preview of next 7 days check-in schedule:")
        cur = datetime.now()
        for i in range(7):
            d = cur + timedelta(days=i)
            day_str = d.strftime("%A, %b %d")
            if is_weekend(d):
                print(f"  • {day_str:20}: {Style.YELLOW}SKIPPED (Weekend){Style.RESET}")
            else:
                rand_t = get_random_time_for_day(d)
                print(f"  • {day_str:20}: {Style.GREEN}Check-In at {rand_t.strftime('%I:%M:%S %p')}{Style.RESET}")
        print()
        sys.exit(0)

    try:
        start_scheduler(headed=args.headed)
    except KeyboardInterrupt:
        print("\nScheduler stopped by user.")


if __name__ == "__main__":
    main()
