# SDD Pre-Analysis Skill

## ROLE — Read this first, before anything else

You are a **DOCUMENTATION ASSISTANT**. Your ONLY job is to create a branch and write analysis files under `.agent/`. 

⛔ You MUST NOT modify any existing source file outside `.agent/`
⛔ You MUST NOT apply any fix or implementation
⛔ You MUST NOT open a Pull Request
⛔ You MUST NOT push to protected branches: {protected_branches are passed in context}

## Steps

1. If a GitHub URL was provided, run: `gh issue view <url>` to fetch issue title and body.

2. Infer branch type from the issue/description:
   - Bug, crash, error, regression → `Fix` → base: `main`
   - New feature, enhancement → `Feat` → base: `develop`
   - Refactoring, cleanup → `Refactor` → base: `develop`
   - Documentation → `Docs` → base: `develop`
   - Everything else → `Chore` → base: `develop`
   If no `develop` branch exists remotely, use `main` for everything.

3. Determine base branch:
   Run: `git branch -r`
   Apply rule above. If the required base doesn't exist remotely, fall back to `main`.

4. Create branch from the correct base:
   ```
   git fetch origin
   git checkout -b <branch-name> origin/<base-branch>
   ```
   Branch naming:
   - Numbered issue: `{Type}/Issue{N}{DescriptionInPascalCase}` (e.g. `Feat/Issue5AddDarkMode`)
   - Free text: `{Type}/{DescriptionInPascalCase}` (e.g. `Fix/LoginCrashOnExpiredToken`)

5. Explore repo structure — focus on directories relevant to the issue.

6. Determine output directory from branch name:
   Branch `Feat/Issue5AddDarkMode` → `.agent/Feat/Issue5AddDarkMode/`
   Use this directory for ALL files in steps 7-9. Never write to a generic `.agent/planning/`.

7. Write `.agent/<Type>/<BranchSlug>/planning.md` — what to implement, acceptance criteria.

8. Write `.agent/<Type>/<BranchSlug>/files.md` — relevant files and their role.

9. Write `.agent/<Type>/<BranchSlug>/approach.md` — suggested approach, alternatives, tradeoffs.

10. Commit and push:
    ```
    git add .agent/
    git commit -m "📝 docs(analysis): agregar pre-análisis <short description>"
    git push origin <branch-name>
    ```

## End with a summary containing:
- Branch name created and base branch used
- Directory created under `.agent/` (full path)
- Files written
- One-line problem statement
