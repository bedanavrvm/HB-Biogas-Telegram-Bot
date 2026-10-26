# Issue tracker: GitHub

Issues, specifications, implementation tickets, and wayfinding maps live in
GitHub Issues for `bedanavrvm/HB-Biogas-Telegram-Bot`. Use the GitHub CLI (`gh`).
The local `.scratch/` directory is not an alternative issue tracker.

## Target and prerequisites

- Check the current remote against
  `https://github.com/bedanavrvm/HB-Biogas-Telegram-Bot.git` before operating.
  A different remote needs clarification, not a silent repository switch.
- Pass `--repo bedanavrvm/HB-Biogas-Telegram-Bot` to issue and label commands.
  For `gh api`, use the explicit repository path shown below.
- Verify authentication with `gh auth status --hostname github.com`, then check
  access and Issues availability with
  `gh repo view bedanavrvm/HB-Biogas-Telegram-Bot --json nameWithOwner,hasIssuesEnabled,viewerPermission`.
  Missing access or disabled Issues is an operator handoff; do not change
  repository settings or switch trackers automatically.
- Follow the existing `AGENTS.md` security and external-write controls. Setup
  does not authorize publishing unrelated work or committing/pushing changes.

## Conventions

Use these command shapes with the explicit `--repo` option above:

- Create: `gh issue create --title "..." --body-file <file>`.
- Read: `gh issue view <number> --json number,title,body,labels,comments`.
- List: `gh issue list --state open --json number,title,body,labels,assignees`;
  use `--search` and `--label` to narrow the result.
- Comment: `gh issue comment <number> --body-file <file>`.
- Update: `gh issue edit <number> --body-file <file>`.
- Label: `gh issue edit <number> --add-label "..." --remove-label "..."`.
- Close: `gh issue close <number> --comment "..."`.

Search for an existing ticket before creating one. After an uncertain create,
reconcile the remote result before retrying. Keep issue content synthetic or
sanitized; customer records, signed documents and credentials stay out of GitHub.
Use PowerShell here-strings or existing sanitized files for multiline bodies,
not Bash heredoc syntax in PowerShell.

## Pull requests as a triage surface

**PRs as a request surface: no.**

## Skill operations

When a skill says "publish to the issue tracker", create a GitHub issue. When
it says "fetch the relevant ticket", read that issue and its comments. Use
[the configured triage mapping](triage-labels.md), not invented label aliases.

### Wayfinding operations

- Map: one issue labelled `wayfinder:map`, with Notes, Decisions-so-far, and Fog.
- Child: `gh issue create --parent <map-number> ...`, or
  `gh issue edit <map-number> --add-sub-issue <child-number>`.
  Use `wayfinder:research`, `wayfinder:prototype`, `wayfinder:grilling`, or
  `wayfinder:task` as appropriate.
- Blocking: `gh issue edit <child-number> --add-blocked-by <blocker-number>`.
  Native sub-issue/dependency flags require a CLI that supports them; check
  `gh issue create --help` and `gh issue edit --help` on another machine.
- If the CLI lacks native flags, use the GitHub API:
  `gh api --method POST repos/bedanavrvm/HB-Biogas-Telegram-Bot/issues/<map-number>/sub_issues -F sub_issue_id=<child-database-id>`, or
  `gh api --method POST repos/bedanavrvm/HB-Biogas-Telegram-Bot/issues/<child-number>/dependencies/blocked_by -F issue_id=<blocker-database-id>`.
  Obtain numeric database IDs with
  `gh api repos/bedanavrvm/HB-Biogas-Telegram-Bot/issues/<number> --jq .id`;
  neither an issue number nor a `node_id` is a database ID.
- If the repository does not support those relationships, put `Part of #<map>`
  and `Blocked by: #<number>` in child bodies and maintain the map's task list.
- Frontier: choose the first open, unassigned child in map order with no open
  blockers. Read native dependencies or the documented fallback before claiming.
- Claim: assign the selected ticket to the driving developer with
  `gh issue edit <number> --add-assignee @me`.
- Resolve: comment with the result/evidence, close the ticket, and add a concise
  decision plus its issue link to the map's Decisions-so-far section.

Wayfinder labels are separate from the five triage labels. Before a wayfinding
operation, list existing labels and create only the specific missing labels
needed for that authorized operation. Preserve existing colours/descriptions.

## Manual authentication on a new machine

Install GitHub CLI using the
[official Windows instructions](https://github.com/cli/cli/blob/trunk/docs/install_windows.md),
then complete its interactive login:

```powershell
gh auth login --hostname github.com --git-protocol https --web --skip-ssh-key
```

If a just-installed `gh` is not on PATH, open a new terminal or use:

```powershell
& 'C:\Program Files\GitHub CLI\gh.exe' auth login --hostname github.com --git-protocol https --web --skip-ssh-key
```

Use GitHub's browser flow and system credential store. Never paste tokens or
passwords into chat, repository files, or logs. If login reports plaintext
credential storage, resolve secure storage before continuing. The
[official login documentation](https://cli.github.com/manual/gh_auth_login)
describes credential handling.

After login, verify repository access and list labels with
`gh label list --repo bedanavrvm/HB-Biogas-Telegram-Bot --limit 1000 --json name`.
Create each missing configured triage label with `gh label create <name> --repo
bedanavrvm/HB-Biogas-Telegram-Bot --description "..." --color <six-hex-digits>`.
Do not use `--force`; already-existing labels remain unchanged. A repeated setup
should create no additional labels or duplicate configuration sections.
