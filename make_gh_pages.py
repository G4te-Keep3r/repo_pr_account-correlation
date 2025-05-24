import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from jinja2 import Environment, FileSystemLoader
import matplotlib.colors as mcolors
import os

# Configuration
DB_PATH = "pull_requests_2025.db"
OUTPUT_DIR = "docs"
TEMPLATE_DIR = "templates"
TEMPLATE_FILE = "report_template.html"
TIME_START = "2025-04-17T00:00:00Z"
TIME_END = "2025-05-21T23:59:59Z"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# Load database
conn = sqlite3.connect(DB_PATH)
df = pd.read_sql_query("SELECT * FROM pull_requests", conn, parse_dates=["created_at", "updated_at", "closed_at", "merged_at"])
df = df[(df["created_at"] >= TIME_START) & (df["created_at"] <= TIME_END)]

# Filter qualified users
user_repo_counts = df.groupby("user_login")["repo"].nunique()
qualified_users = user_repo_counts[user_repo_counts >= 2].index
df_qualified = df[df["user_login"].isin(qualified_users)]

# Generate repo-first categorization
repo_firsts = df_qualified.groupby(['user_login', 'repo'])['created_at'].min().reset_index()
repo_firsts = repo_firsts.sort_values(by=['user_login', 'created_at'])
repo_firsts['repo_index'] = repo_firsts.groupby('user_login').cumcount() + 1
repo_firsts['repo_category'] = repo_firsts['repo_index'].apply(lambda i: "First" if i == 1 else "Second" if i == 2 else "Third+")

# Chart data
first_repo = repo_firsts[repo_firsts['repo_category'] == 'First']['repo'].value_counts()
second_repo = repo_firsts[repo_firsts['repo_category'] == 'Second']['repo'].value_counts()
third_plus_repo = repo_firsts[repo_firsts['repo_category'] == 'Third+']['repo'].value_counts()
all_prs_repo_counts = df_qualified["repo"].value_counts()
repo_hits = df_qualified.groupby(["repo", "user_login"]).size().reset_index(name="count")
repo_hits = repo_hits.groupby("repo")["user_login"].nunique()
heatmap_data = df_qualified.copy()
heatmap_data["date"] = heatmap_data["created_at"].dt.date
all_dates = pd.date_range(start=TIME_START, end=TIME_END).date

def get_heat_series(df, user_repo_map, category):
    user_repo_map = user_repo_map[user_repo_map["repo_category"] == category]
    merged = df.merge(user_repo_map[["user_login", "repo"]], on=["user_login", "repo"])
    counts = merged["date"].value_counts().reindex(all_dates, fill_value=0)
    return counts

heat_first = get_heat_series(heatmap_data, repo_firsts, "First")
heat_second = get_heat_series(heatmap_data, repo_firsts, "Second")
heat_third_plus = get_heat_series(heatmap_data, repo_firsts, "Third+")
heat_all = heatmap_data["date"].value_counts().reindex(all_dates, fill_value=0)
repos_per_user = df_qualified.groupby("user_login")["repo"].nunique().value_counts().sort_index()
state_counts = df_qualified["state"].value_counts()

# Linked issues
df_issues = pd.read_sql_query("SELECT * FROM pr_issues", conn)
df["linked_issue"] = df["id"].isin(df_issues["pr_id"].unique())
issue_counts = df["linked_issue"].value_counts().rename(index={True: "Linked to Issue", False: "No Linked Issue"})

# Get evenly spaced repo colors by permuting index positions
all_repos = sorted(set(first_repo.index).union(second_repo.index).union(third_plus_repo.index).union(repo_hits.index))
n = len(all_repos)
cmap = plt.colormaps.get_cmap("tab20")

# Visually space colors using a stride pattern (e.g., i*3 % n)
spaced_indices = [(i * 3) % n for i in range(n)]
repo_colors = {
    repo: mcolors.to_hex(cmap(spaced_i / n))
    for repo, spaced_i in zip(all_repos, spaced_indices)
}



def save_pie(data, title, filename, label=True, full_repo_order=None, use_repo_colors=True, offset=0):
    if full_repo_order is not None:
        data = data.reindex(full_repo_order, fill_value=0)
        data = data[data > 0]

    if use_repo_colors:
        colors = [repo_colors.get(repo, "#444") for repo in data.index]
    else:
        cmap = plt.colormaps.get_cmap("tab10")
        colors = [mcolors.to_hex(cmap(i / len(data))) for i in range(len(data))]

    plt.figure(figsize=(8, 8))
    plt.pie(
        data,
        labels=data.index if label else None,
        autopct="%1.1f%%" if label else None,
        colors=colors,
        textprops={"color": "white"},
        startangle=140+offset
    )
    plt.title(title, color="white")
    plt.axis("equal")
    plt.gca().set_facecolor("#121212")
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, filename), facecolor="#121212")
    plt.close()



def save_heatmap(series, title, filename):
    plt.figure(figsize=(12, 2))
    ax = sns.heatmap([series.values], cmap="inferno", cbar=True, xticklabels=30)
    plt.title(title, color="white")
    ax.set_facecolor("#121212")
    plt.xticks(color="white")
    plt.yticks(color="white")
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, filename), facecolor="#121212")
    plt.close()

def save_bar(series, title, filename):
    plt.figure(figsize=(10, 6))
    ax = series.plot(kind='bar', color='skyblue')
    plt.title(title, color="white")
    plt.xlabel("Repos Contributed To", color="white")
    plt.ylabel("Number of Users", color="white")
    plt.xticks(color="white")
    plt.yticks(color="white")
    ax.set_facecolor("#121212")
    plt.gcf().patch.set_facecolor("#121212")
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, filename), facecolor="#121212")
    plt.close()

# Save charts
# Use repo_hits.index as master order
master_repo_order = repo_hits.index.tolist()
save_pie(repo_hits, "Repos Hit (Unique Contributors)", "pie_repo_hits.png", label=True)
save_pie(first_repo, "First PR", "pie_first_repo.png", label=False, full_repo_order=master_repo_order)
save_pie(second_repo, "Second PR", "pie_second_repo.png", label=False, full_repo_order=master_repo_order)
save_pie(third_plus_repo, "Third+ PR", "pie_third_plus_repo.png", full_repo_order=master_repo_order)
save_pie(all_prs_repo_counts, "All PRs by Repo", "pie_all_prs_repo.png", full_repo_order=master_repo_order)
save_pie(state_counts, "PR State Distribution", "pie_state_distribution.png", use_repo_colors=False, offset=30)
save_pie(issue_counts, "PRs With vs Without Linked Issues", "pie_linked_issues.png", use_repo_colors=False)

save_heatmap(heat_first, "Heatmap: First PR Dates", "heat_first_pr.png")
save_heatmap(heat_second, "Heatmap: Second PR Dates", "heat_second_pr.png")
save_heatmap(heat_third_plus, "Heatmap: Third+ PR Dates", "heat_third_plus_pr.png")
save_heatmap(heat_all, "Heatmap: All PR Dates", "heat_all_pr.png")
save_bar(repos_per_user, "Number of Repos Each User Contributed To", "bar_repos_per_user.png")

# Render HTML
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
template = env.get_template(TEMPLATE_FILE)
summary = f"{len(qualified_users)} accounts made PRs to at least 2 different repos between {TIME_START[:10]} and {TIME_END[:10]}."
charts = [
    {"filename": "pie_repo_hits.png", "title": "Repos Hit (Unique Contributors)"},
    {
        "title": "PR Order Breakdown (still unique contributors)",
        "layout": "row",
        "subcharts": [
            {"filename": "pie_first_repo.png", "title": "First PR"},
            {"filename": "pie_second_repo.png", "title": "Second PR"},
            {"filename": "pie_third_plus_repo.png", "title": "Third+ PR"},
        ]
    },
    {"filename": "pie_all_prs_repo.png", "title": "All PRs by Repo"},
    {"filename": "pie_state_distribution.png", "title": "PR State Distribution"},
    {"filename": "pie_linked_issues.png", "title": "PRs With vs Without Linked Issues"},
    {"filename": "heat_first_pr.png", "title": "Heatmap: First PR Dates"},
    {"filename": "heat_second_pr.png", "title": "Heatmap: Second PR Dates"},
    {"filename": "heat_third_plus_pr.png", "title": "Heatmap: Third+ PR Dates"},
    {"filename": "heat_all_pr.png", "title": "Heatmap: All PR Dates"},
    {"filename": "bar_repos_per_user.png", "title": "Number of Repos Each User Contributed To"},
]

html = template.render(summary=summary, charts=charts)
with open(os.path.join(OUTPUT_DIR, "index.html"), "w") as f:
    f.write(html)

print("✅ Report generated successfully.")