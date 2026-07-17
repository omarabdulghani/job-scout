import argparse
import asyncio
import json
import sqlite3
import sys
import datetime
import time
from pathlib import Path
from typing import Any

from agent.browser import BrowserController
from agent.dashboard_user_state import DashboardUserStateStore, STATUS_UNREVIEWED, build_job_key
from agent.safe_file_io import atomic_write_json

class ExpiredJobsCleaner:
    def __init__(self, target_categories=None):
        self.dashboard_file = Path("data/recommended_jobs_dashboard_data.json")
        self.db_path = Path("data/applications.db")
        self.scout_db_path = Path("data/user_workspace/job_scout.db")
        self.user_state = DashboardUserStateStore()
        self.progress_file = Path("data/clean_expired_progress.json")
        self.history_file = Path("data/clean_expired_history.json")
        self.target_categories = target_categories or ["LOW_PROBABILITY", "REJECTED"]
        self.scan_mode = "SKIP_ACTIVE"
        
    def _update_progress(self, current, total, status, job_title=""):
        data = {
            "current": current,
            "total": total,
            "status": status,
            "job_title": job_title,
            "target_categories": self.target_categories
        }
        atomic_write_json(self.progress_file, data)
        
    def _append_history(self, job_title, result, reason=""):
        data = {"sessions": []}
        if self.history_file.exists():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass
                
        if not data.get("sessions"):
            data["sessions"] = [{"id": 1, "start_time": datetime.datetime.now(datetime.timezone.utc).isoformat(), "history": {"cleaned": [], "not_expired": [], "unknown": []}}]
            
        session = data["sessions"][0]
        
        entry = {"title": job_title}
        if reason:
            entry["reason"] = reason
            
        session["history"][result].append(entry)
        atomic_write_json(self.history_file, data)

    def _get_target_jobs(self) -> list[dict[str, Any]]:
        try:
            with open(self.dashboard_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []

        jobs = data.get("jobs", [])
        targets = []
        for job in jobs:
            job_key = build_job_key(job)
            if not job_key:
                continue
                
            decision = job.get("decision_category", "LOW_PROBABILITY")
            if not decision: decision = "LOW_PROBABILITY"
            
            if "ALL_UNREVIEWED" not in self.target_categories and decision not in self.target_categories:
                continue
            
            saved = self.user_state.data.get("jobs", {}).get(job_key, {})
            status = saved.get("status", STATUS_UNREVIEWED)
            last_active = saved.get("last_verified_active")
            
            if status == STATUS_UNREVIEWED:
                if self.scan_mode == "SKIP_ACTIVE" and last_active:
                    try:
                        last_active_date = datetime.datetime.fromisoformat(last_active)
                        if datetime.datetime.now() - last_active_date < datetime.timedelta(days=7):
                            continue
                    except Exception:
                        pass
                targets.append(job)
                
        return targets

    def _mark_job_expired(self, job: dict[str, Any]):
        job_key = build_job_key(job)
        if not job_key:
            return
        from agent.operational_store import OperationalStore
        store = OperationalStore(Path("."))
        store.true_amnesia_delete(job_key, self.dashboard_file, self.user_state.path)

    async def run(self):
        resume_index = 0
        if self.progress_file.exists():
            try:
                with open(self.progress_file, "r", encoding="utf-8") as f:
                    prog = json.load(f)
                    if prog.get("status") != "Complete":
                        if prog.get("target_categories") == self.target_categories:
                            resume_index = prog.get("current", 0)
            except Exception:
                pass

        if resume_index == 0:
            data = {"sessions": []}
            if self.history_file.exists():
                try:
                    with open(self.history_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    pass
            new_id = (data["sessions"][0].get("id", 0) + 1) if data.get("sessions") else 1
            new_session = {
                "id": new_id,
                "start_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "status": "Running...",
                "history": {"cleaned": [], "not_expired": [], "unknown": []}
            }
            data["sessions"].insert(0, new_session)
            atomic_write_json(self.history_file, data)

        self._update_progress(resume_index, 0, "Gathering jobs...")
        jobs = self._get_target_jobs()
        total = len(jobs)
        
        if total == 0 or resume_index >= total:
            self._update_progress(total, total, "Complete")
            return

        self._update_progress(resume_index, total, "Starting browser...")
        
        browser = BrowserController(headless=False, profile_dir="data/browser_profile")
        await browser.start()
        
        try:
            page = browser.page
            
            for i in range(resume_index, total):
                job = jobs[i]
                url = job.get("url")
                title = job.get("title", "Unknown Job")
                
                if not url or "linkedin.com" not in url.lower():
                    self._append_history(title, "unknown", reason="Invalid or Non-LinkedIn URL")
                    self._update_progress(i + 1, total, f"Checking {i+1}/{total}...", title)
                    continue
                    
                self._update_progress(i, total, f"Checking {i+1}/{total}...", title)
                
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(2) 
                    
                    content = await page.content()
                    content_lower = content.lower()
                    
                    current_url = page.url.lower()
                    page_title = await page.title()
                    page_title = page_title.lower()
                    
                    is_auth_wall = "authwall" in current_url or "login" in current_url or "signup" in current_url
                    is_captcha = "security verification" in page_title or "security challenge" in page_title
                    
                    # Pause and Wait Strategy for Security Walls
                    while is_auth_wall or is_captcha:
                        self._update_progress(i, total, f"PAUSED - Security Wall! Please solve in the visible browser...", title)
                        await asyncio.sleep(5)
                        
                        # Once the user solves it, LinkedIn usually auto-redirects them to the job or feed.
                        # So we check the content again
                        content = await page.content()
                        content_lower = content.lower()
                        current_url = page.url.lower()
                        page_title = await page.title()
                        page_title = page_title.lower()
                        
                        is_auth_wall = "authwall" in current_url or "login" in current_url or "signup" in current_url
                        is_captcha = "security verification" in page_title or "security challenge" in page_title
                        
                        # If the challenge is gone, we must reload the actual job page because they might have been redirected away
                        if not is_auth_wall and not is_captcha:
                            self._update_progress(i, total, f"Resuming after Security Wall bypass...", title)
                            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                            await asyncio.sleep(2)
                            content = await page.content()
                            content_lower = content.lower()
                            break
                    
                    is_expired = False
                    is_unknown = False
                    reason = ""
                    
                    if "no longer accepting applications" in content_lower:
                        is_expired = True
                    elif "this job is no longer available" in content_lower:
                        is_expired = True
                    elif "this page doesn't exist" in content_lower:
                        is_expired = True
                    elif "unable to load the page" in content_lower:
                        is_expired = True
                    elif "page not found" in content_lower and "linkedin" in content_lower:
                        is_expired = True
                    
                    if not is_expired:
                        alert_box = await page.query_selector(".jobs-details-top-card__apply-error, .artdeco-inline-feedback--error")
                        if alert_box:
                            text = await alert_box.inner_text()
                            if "no longer accepting" in text.lower():
                                is_expired = True
                                
                    current_url = page.url.lower()
                    page_title = await page.title()
                    page_title = page_title.lower()
                    is_auth_wall = "authwall" in current_url or "login" in current_url or "signup" in current_url
                    is_captcha = "security verification" in page_title or "security challenge" in page_title
                    
                    if is_auth_wall or is_captcha:
                        is_unknown = True
                        reason = "Auth Wall / Security Challenge"
                                
                    if is_expired:
                        self._mark_job_expired(job)
                        self._append_history(title, "cleaned")
                    elif is_unknown:
                        self._append_history(title, "unknown", reason=reason)
                    else:
                        self._append_history(title, "not_expired")
                        job_key = build_job_key(job)
                        if job_key:
                            if "jobs" not in self.user_state.data:
                                self.user_state.data["jobs"] = {}
                            if job_key not in self.user_state.data["jobs"]:
                                self.user_state.data["jobs"][job_key] = {}
                            self.user_state.data["jobs"][job_key]["last_verified_active"] = datetime.datetime.now().isoformat()
                            atomic_write_json(self.user_state.path, self.user_state.data)
                        
                except Exception as e:
                    print(f"Error checking {url}: {e}")
                    self._append_history(title, "unknown", reason=f"Timeout or Load Error")
                    
                self._update_progress(i + 1, total, f"Checking {i+1}/{total}... (Cooling down)", title)
                import random
                await asyncio.sleep(random.uniform(2, 4))
                
        finally:
            if browser.playwright:
                await browser.playwright.stop()
                
        self._update_progress(total, total, "Complete", "All done!")
        
        # Complete session
        if self.history_file.exists():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("sessions"):
                    session = data["sessions"][0]
                    session["end_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    session["status"] = "Completed"
                    start = datetime.datetime.fromisoformat(session["start_time"])
                    session["duration_seconds"] = int((datetime.datetime.now(datetime.timezone.utc) - start).total_seconds())
                    atomic_write_json(self.history_file, data)
            except Exception:
                pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--targets", nargs="+", default=["LOW_PROBABILITY", "REJECTED"])
    parser.add_argument("--scan-mode", type=str, default="SKIP_ACTIVE")
    args = parser.parse_args()
    cleaner = ExpiredJobsCleaner(target_categories=args.targets)
    cleaner.scan_mode = args.scan_mode
    asyncio.run(cleaner.run())
