# Repository contribution instructions

- Read CONTRIBUTING.md before branch, code, documentation or test changes.
- Start new work from the latest verified origin/main on a short-lived feature-group or story branch. A branch should normally last about 1–3 days; split independent changes rather than accumulating a whole sprint.
- The 15 October 2026 reverse-engineering baseline e50c746e3f8892128e25d0f2baadc27f8e0a0521 and initial branch map are historical references, not the current release baseline. Do not restore them over later approved work.
- Continue excluding Trial_Code, final_changes and the unmerged c3e46ea venue helper unless the user explicitly changes scope. Preserve those refs and original history.
- Scope changes by their diff; do not copy or recommit existing code to make a branch appear feature-exclusive. Multiple authors may contribute.
- Include affected Jira keys in feature/fix commits and PRs. Current imported stories use US keys; historical SCRUM keys and executable test names retain their original meaning.
- Keep real authors, dates and execution results. A green CI run or agent review is separate from teammate correctness review, manual walkthrough and PO acceptance.
- Preserve local changes and refs. Obtain explicit instruction before branch deletion, force pushes, history rewriting or merging into main.
