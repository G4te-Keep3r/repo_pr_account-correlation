# repo_pr_account-correlation
**gathering GitHub activity and analyzing account PR behavior by repo**
This project scrapes GitHub pull request data from a curated list of repositories and generates visual analytics to explore patterns in contributor behavior.
 [https://g4te-keep3r.github.io/repo_pr_account-correlation/](https://g4te-keep3r.github.io/repo_pr_account-correlation/)

---

### 🔍 Use Case

Originally built to analyze PR behavior for a personal curiosity, this tool helps identify:
- Which accounts made PRs to multiple target repos
- PR timing trends (e.g., first, second, third+ contributions)
- Linked issue behavior
- Distribution of PR states (e.g., merged, open, closed)
	- *(Potential enhancement: distinguish cases like “waiting for changes”)*
- Behavioral patterns via future semantic analysis after scraping account-level data

It can also be adapted to analyze broader open-source activity across arbitrary repo sets.

---

### 📊 Output

The tool generates a GitHub Pages–friendly HTML report with:
- Pie charts for PR distributions and repo hit counts
- A stacked PR breakdown by contribution order (1st/2nd/3rd+)
- Heatmaps showing PR activity over time
- Visualizations of issue linkage ratios
	*(Note: current DB may be missing some linked issue data)*

---

### ⚠️ Known Bugs / Limitations

> These will be filed as GitHub issues in a future update.

- Some repos (e.g., `openssl/openssl`) show **more PRs in the database than actually exist on GitHub in subsequent runs**
  - ex: Repo openssl/openssl has fewer PRs in GitHub (65) than DB (726)
- No direct deduplication or conflict resolution if data is re-scraped
- Validation and count logic needs refining
	- Repo count can start at wrong numbers (not 0) when a run is interupted, assume something to do with progress.json

---

### 🧪 Experiment Note

This project was created using ChatGPT as an experiment. Gen purpose 4o, no special GPTs used. Plus subscription, and moved to new chats when it got obsessed with something.

> In hindsight:
> - It would have been faster to write large chunks manually
> - Validation checks should’ve been added earlier
> - Collection scope evolved from the window to full history, before settling on filtering to 2025 (for now)

Still, the process was valuable in understanding the trade-offs of AI-assisted dev workflows — though this was copy/paste not IDE-integrated.

---

### 📄 License
MIT — Use freely and modify as needed
