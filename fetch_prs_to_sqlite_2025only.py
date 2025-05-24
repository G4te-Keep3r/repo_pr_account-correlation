import requests
import sqlite3
import time
import os
import re
import logging
import pandas as pd
from dotenv import load_dotenv
from tqdm import tqdm
from datetime import datetime
import json

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    raise Exception("GitHub token not found. Set GITHUB_TOKEN in .env or environment.")

HEADERS_oldddddd = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json"
}

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

DB_FILE = "pull_requests_2025.db"
TIME_START = "2025-04-14T00:00:00Z"
TIME_END = "2025-05-21T23:59:59Z"
REPO_FILE = "repos.csv"
CALL_COUNT = 0

# Setup log files per run
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
status_log_filename = f"status_log_{timestamp}.txt"
data_log_filename = f"data_log_{timestamp}.txt"

# Status logger (INFO, WARNINGS, STATE)
status_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
status_handler = logging.FileHandler(status_log_filename)
status_handler.setFormatter(status_formatter)
status_handler.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(status_formatter)
console_handler.setLevel(logging.WARNING)

logger = logging.getLogger("status_logger")
logger.setLevel(logging.INFO)
logger.addHandler(status_handler)
logger.addHandler(console_handler)

# Data logger (everything inserted into DB)
data_logger = logging.getLogger("data_logger")
data_logger.setLevel(logging.INFO)
data_log_handler = logging.FileHandler(data_log_filename)
data_log_handler.setFormatter(logging.Formatter("%(message)s"))
data_logger.addHandler(data_log_handler)

def extract_linked_issues(pr_body):
    issue_refs = re.findall(r'#(\d+)', pr_body or '')
    return list(set(int(num) for num in issue_refs))

def fetch_issue_title(repo, issue_number):
    owner, name = repo.split("/")
    url = f"https://api.github.com/repos/{owner}/{name}/issues/{issue_number}"
    response = github_get(url)
    if response.status_code != 200:
        return None
    return response.json().get("title")



def fetch_all_prs(repo):
    owner, name = repo.split("/")
    pr_list = []
    page = 1
    pbar = tqdm(desc=f"Fetching {repo}", unit="page")

    while True:
        url = f"https://api.github.com/repos/{owner}/{name}/pulls"
        params = {
            "state": "all",
            "per_page": 100,
            "page": page,
            "sort": "created",
            "direction": "desc",
            "since": "2025-01-01T00:00:00Z",
        }
        response = github_get(url, params=params)
        pbar.update(1)

        if response.status_code != 200:
            print(f"Failed to fetch PRs for {repo}: {response.status_code}")
            break

        data = response.json()
        if not data:
            break

        filtered = [pr for pr in data if pr.get("user", {}).get("type") != "Bot" and pr["created_at"] >= "2025-01-01T00:00:00Z"]
        pr_list.extend(filtered)

        if len(data) < 100:
            break

        page += 1
        time.sleep(0.5)

    pbar.close()
    return pr_list




def fetch_incremental_prs(repo, since):
    validate_tail_count = 25  # Number of recent PRs to refetch and validate
    owner, name = repo.split("/")
    pr_list = []
    page = 1
    pbar = tqdm(desc=f"Incremental {repo}", unit="page")

    validate_batch = []
    found_cutoff = False

    while True:
        url = f"https://api.github.com/repos/{owner}/{name}/pulls"
        params = {
            "state": "all",
            "per_page": 100,
            "page": page,
            "sort": "created",
            "direction": "desc"
        }
        response = github_get(url, params=params)
        pbar.update(1)

        if response.status_code != 200:
            print(f"Failed to fetch PRs for {repo}: {response.status_code}")
            break

        data = response.json()
        if not data:
            break

        filtered = [pr for pr in data if pr.get("user", {}).get("type") != "Bot"]
        new_prs = []
        for pr in filtered:
            if len(validate_batch) < validate_tail_count:
                pr["__validation_type"] = "validate"
                validate_batch.append(pr)
            if pr["created_at"] > since:
                pr["__validation_type"] = "new"
                new_prs.append(pr)
            elif not found_cutoff:
                found_cutoff = True
                break

        pr_list.extend(new_prs)
        if len(new_prs) < len(data):
            break
        page += 1
        time.sleep(0.5)

    pbar.close()
    for pr in validate_batch:
        if pr not in pr_list:
            pr_list.append(pr)
    return pr_list



def create_db_schema(conn):
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS pull_requests (
            id INTEGER PRIMARY KEY,
            repo TEXT,
            number INTEGER,
            title TEXT,
            state TEXT,
            created_at TEXT,
            updated_at TEXT,
            closed_at TEXT,
            merged_at TEXT,
            user_login TEXT,
            user_id INTEGER,
            head_ref TEXT,
            head_repo_full_name TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS pr_issues (
            pr_id INTEGER,
            issue_number INTEGER,
            issue_title TEXT,
            FOREIGN KEY(pr_id) REFERENCES pull_requests(id)
        )
    """)
    conn.commit()

def github_get(url, params=None):
    global CALL_COUNT
    while True:
        response = requests.get(url, headers=HEADERS, params=params)
        CALL_COUNT += 1
        if response.status_code == 403:
            remaining = int(response.headers.get("X-RateLimit-Remaining", 0))
            reset = int(response.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait_time = max(reset - int(time.time()), 1)
            logger.warning(f"Rate limit hit. Waiting {wait_time} seconds (resets at {reset})")
            print(f"\n[Rate Limit] Waiting {wait_time} seconds...")
            for i in range(wait_time, 0, -1):
                print(f"  Resuming in {i} seconds...", end="\r")
                time.sleep(1)
            print()
            continue
        return response

failed_pr_log_file = None

def insert_prs(conn, repo, pr_list):
    global failed_pr_log_file
    c = conn.cursor()
    for pr in tqdm(pr_list, desc=f"Inserting {repo} PRs"):
        if pr.get("user", {}).get("type") == "Bot":
            continue

        try:
            pr_id = pr["id"]
            pr_number = pr["number"]
            pr_title = pr["title"]
            pr_state = pr["state"]
            pr_created = pr["created_at"]
            pr_updated = pr["updated_at"]
            pr_closed = pr.get("closed_at")
            pr_merged = pr.get("merged_at")
            pr_user_login = pr["user"]["login"] if pr.get("user") else None
            pr_user_id = pr["user"]["id"] if pr.get("user") else None
            pr_head_ref = pr["head"]["ref"] if pr.get("head") else None
            pr_head_repo = pr["head"]["repo"]["full_name"] if pr["head"].get("repo") else None
            pr_body = pr.get("body", "")

            c.execute("""
                INSERT OR IGNORE INTO pull_requests (
                    id, repo, number, title, state, created_at, updated_at,
                    closed_at, merged_at, user_login, user_id,
                    head_ref, head_repo_full_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pr_id, repo, pr_number, pr_title, pr_state, pr_created, pr_updated,
                pr_closed, pr_merged, pr_user_login, pr_user_id, pr_head_ref, pr_head_repo
            ))

            status = pr.get("__validation_type", "corrected")
            data_logger.info(f"{status.upper()} PR: {repo} #{pr_number} by {pr_user_login} on {pr_created}: {pr_title}")


            issue_numbers = extract_linked_issues(pr_body)
            for issue_number in issue_numbers:
                issue_title = fetch_issue_title(repo, issue_number)
                if issue_title:
                    c.execute("""
                        INSERT OR IGNORE INTO pr_issues (pr_id, issue_number, issue_title)
                        VALUES (?, ?, ?)
                    """, (pr_id, issue_number, issue_title))
                    data_logger.info(f"  Linked ISSUE: #{issue_number} - {issue_title}")

        except Exception as e:
            logger.warning(f"Failed to insert PR #{pr.get('number')} from {repo}: {e}")
            if not failed_pr_log_file:
                fail_log_name = f"failed_prs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
                failed_pr_log_file = open(fail_log_name, "w", encoding="utf-8")
            failed_pr_log_file.write(json.dumps(pr) + "\n")

    if failed_pr_log_file:
        failed_pr_log_file.close()

    conn.commit()

def load_checkpoint():
    checkpoint_file = "checkpoint.json"
    if os.path.exists(checkpoint_file):
        with open(checkpoint_file, "r") as f:
            return json.load(f)
    return {"finished": False, "completed": []}

def save_checkpoint(completed_repos, finished=False):
    with open("checkpoint.json", "w") as f:
        json.dump({"finished": finished, "completed": completed_repos}, f, indent=2)


def main():
    df = pd.read_csv(REPO_FILE)
    grouped = df.groupby("Lang")
    language_list = list(grouped.groups.keys())

    conn = sqlite3.connect(DB_FILE)
    create_db_schema(conn)

    checkpoint = load_checkpoint()
    finished = checkpoint.get("finished", False)
    completed_repos = set(checkpoint.get("completed", []))

    total_langs = len(language_list)
    lang_counter = 0

    for lang, group in grouped:
        lang_counter += 1
        print(f"\n== Processing language: {lang} ({lang_counter}/{total_langs}) ==")

        repo_entries = group["Public repo"].tolist()
        repo_list = []
        for entry in repo_entries:
            repos = [r.strip() for r in re.split(r"&&|,", entry) if r.strip()]
            repo_list.extend(repos)

        total_repos = sum(len([r.strip() for entry in group_["Public repo"].tolist() for r in re.split(r"&&|,", entry) if r.strip()]) for _, group_ in grouped)
        global_repo_idx = len(completed_repos)

        for idx, repo_url in enumerate(repo_list):
            if "github.com/" not in repo_url:
                continue
            repo = repo_url.split("github.com/")[-1].strip("/")
            global_repo_idx += 1
            print(f"\nProcessing {repo} ({global_repo_idx}/{total_repos})")

            if repo in completed_repos:
                print(f"  Skipping {repo}, already completed. Validating count...")
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM pull_requests WHERE repo = ?", (repo,))
                local_count = cur.fetchone()[0]

                owner, name = repo.split("/")
                url = f"https://api.github.com/repos/{owner}/{name}/issues"
                params = {"state": "all", "per_page": 100, "page": 1, "since": "2025-01-01T00:00:00Z"}
                remote_count = 0
                latest_created = ""

                while True:
                    response = github_get(url, params=params)
                    if response.status_code != 200:
                        print(f"Failed to fetch for validation: {repo}")
                        break
                    page_data = [pr for pr in response.json() if "pull_request" in pr and pr.get("user", {}).get("type") != "Bot"]
                    if page_data:
                        latest_created = page_data[0]["created_at"] if not latest_created else latest_created
                    remote_count += len(page_data)
                    if len(page_data) < 100:
                        break
                    params["page"] += 1

                if remote_count == local_count:
                    print(f"  ✅ Repo {repo} validated (GitHub = {remote_count}, DB = {local_count})")
                    continue
                elif remote_count > local_count:
                    print(f"  ⚠️ Repo {repo} has more PRs on GitHub ({remote_count}) than DB ({local_count})")
                    print(f"  📅 Checking for new PRs since {latest_created}...")
                else:
                    print(f"  ❌ Repo {repo} has fewer PRs in GitHub ({remote_count}) than DB ({local_count})")

            pr_list = fetch_all_prs(repo)
            insert_prs(conn, repo, pr_list)
            print(f"Inserted {len(pr_list)} PRs for {repo}.")
            completed_repos.add(repo)
            save_checkpoint(list(completed_repos), finished=False)

    conn.close()
    save_checkpoint(list(completed_repos), finished=True)
    print("\nAll repositories processed. Checkpoint updated as complete.")

if __name__ == "__main__":
    main()
