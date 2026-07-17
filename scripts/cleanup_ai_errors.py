import json
import sqlite3
from pathlib import Path

def cleanup_ai_errors():
    dashboard_json_path = Path("data/recommended_jobs_dashboard_data.json")
    db_path = Path("data/user_workspace/job_scout.db")

    if not dashboard_json_path.exists():
        print("Dashboard JSON not found.")
        return

    with open(dashboard_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    jobs = data.get("jobs", [])
    original_count = len(jobs)

    cleaned_jobs = []
    for job in jobs:
        # Check if the job has an AI error
        if job.get("decision_category") == "LOW_PROBABILITY" and "AI scoring could not complete" in str(job.get("reason", "")):
            continue
        # Also catch terminal_status = ai_error just in case
        if job.get("terminal_status") == "ai_error":
            continue
        cleaned_jobs.append(job)

    cleaned_count = len(cleaned_jobs)
    removed_count = original_count - cleaned_count

    data["jobs"] = cleaned_jobs
    with open(dashboard_json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Removed {removed_count} ghost jobs from dashboard JSON.")

    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT job_key, payload_json FROM jobs")
        rows = cursor.fetchall()
        keys_to_delete = []
        for job_key, payload_str in rows:
            try:
                job = json.loads(payload_str)
            except Exception:
                continue
            if job.get("decision_category") == "LOW_PROBABILITY" and "AI scoring could not complete" in str(job.get("reason", "")):
                keys_to_delete.append(job_key)
            elif job.get("terminal_status") == "ai_error":
                keys_to_delete.append(job_key)
        
        if keys_to_delete:
            cursor.executemany("DELETE FROM jobs WHERE job_key = ?", [(k,) for k in keys_to_delete])
            db_removed = cursor.rowcount
            conn.commit()
            print(f"Removed {db_removed} ghost jobs from SQLite database.")
        else:
            print("No ghost jobs found in SQLite database.")
        conn.close()
    else:
        print("SQLite DB not found, skipped.")

if __name__ == "__main__":
    cleanup_ai_errors()
