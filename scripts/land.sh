#!/usr/bin/env bash
# land.sh: stage, commit, sync, validate, and land one local change on
# master through a pull request, exactly as the standing orders require.
#
# Why a script and not a merge Action: SO-2 and SO-6 put every change behind
# a pull request that the agent merges, and SO-4/SO-10 reserve the GitHub
# Actions minutes for the market-hours scans (2000 minute ceiling). The
# governance-guard workflow already validates every PR; this script is the
# local half that stages, writes a SO-7 compliant commit, rebases onto the
# latest master, runs the same checks locally, then opens and merges the PR
# with gh. It never writes to master directly.
#
# Phases: commit, sync, validate, publish (the default runs all four)
#   commit   stage and commit everything (or only the paths after --)
#   sync     fetch origin, rebase the branch onto the latest base branch
#   validate run scripts/check_governance.py and the unittest suite locally
#   publish  push, open or reuse the PR, wait for CI, merge, resync master
#
# Usage examples:
#   scripts/land.sh -m "Fix the capture mirror fallthrough"
#   scripts/land.sh -y -m "Docs: explain the landing flow" -- docs/landing.md
#   scripts/land.sh --dry-run -m "Preview what would be staged"
#   scripts/land.sh -m "Stop after local checks" --until validate
#
# A rerun after a conflict is safe: if the work is already committed, the
# commit phase is skipped and the script continues from the sync step, so a
# hand-resolved rebase can be finished with one more land.sh run.
#
# Exit codes: 0 success, 1 aborted (conflict, failed check, refused state)
set -Eeuo pipefail

BASE="master"
MESSAGE=""
PATHS=()
ASSUME_YES=0
DRY_RUN=0
UNTIL="publish"
DELETE_BRANCH=0

OWNER_NAME="Mr. Rehan"
OWNER_EMAIL="muhammadrehanqureshi@users.noreply.github.com"
OWNER_EMAIL_ALT="111383512+muhammadrehanqureshi@users.noreply.github.com"

now_pkt() { date -u -d "+5 hours" "+%Y-%m-%d %H:%M:%S PKT"; }
step()    { printf "\n== %s ==\n" "$*"; }
note()    { printf "   %s\n" "$*"; }
warn()    { printf "   ! %s\n" "$*"; }
die()     { printf "\nABORT: %s\n" "$*" >&2; exit 1; }

on_err() {
    local code=$?
    printf "\nland.sh stopped early (exit %s). Nothing was merged unless a step above said so.\n" "$code" >&2
    exit "$code"
}
trap on_err ERR

usage() {
    awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
}

# ---------------------------------------------------------------- arguments
while (( $# )); do
    case "$1" in
        -m|--message)    MESSAGE="${2:-}"; shift 2 ;;
        -b|--base)       BASE="${2:-}"; shift 2 ;;
        -y|--yes)        ASSUME_YES=1; shift ;;
        -n|--dry-run)    DRY_RUN=1; shift ;;
        --until)         UNTIL="${2:-}"; shift 2 ;;
        --delete-branch) DELETE_BRANCH=1; shift ;;
        -h|--help)       usage; exit 0 ;;
        --)              shift; PATHS=("$@"); break ;;
        *)               die "unknown argument: $1 (try --help)" ;;
    esac
done

case "$UNTIL" in
    commit|sync|validate|publish) ;;
    *) die "--until must be one of: commit, sync, validate, publish" ;;
esac

# ---------------------------------------------------------------- preflight
step "0/4 preflight ($(now_pkt))"
ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || die "not inside a git repository"
cd "$ROOT"
note "repository: $ROOT"

if [[ -n "$(git ls-files -u)" ]]; then
    die "the index has unresolved conflicts; finish or abort that merge first"
fi

BRANCH=$(git symbolic-ref --short -q HEAD) || die "detached HEAD: check out a feature branch first"
[[ "$BRANCH" != "$BASE" ]] || die "refusing to land on $BASE itself (SO-2: every change is a pull request)"
git remote get-url origin >/dev/null 2>&1 || die "remote 'origin' is not configured"
note "branch: $BRANCH  ->  base: $BASE"

command -v python >/dev/null 2>&1 || die "python is required for the governance and test checks"

got_name=$(git config user.name || true)
got_email=$(git config user.email || true)
if [[ "$got_name" != "$OWNER_NAME" ]] || { [[ "$got_email" != "$OWNER_EMAIL" ]] && [[ "$got_email" != "$OWNER_EMAIL_ALT" ]]; }; then
    warn "git identity is '$got_name <$got_email>'"
    die "SO-7 requires the owner identity. Fix once with:
     git config user.name \"$OWNER_NAME\"
     git config user.email \"$OWNER_EMAIL\""
fi
note "author identity ok (SO-7)"

[[ -n "$MESSAGE" ]] || die "a commit message is required: -m \"...\" (SO-7: no dashes, no bot trailers)"

validate_message() {
    python - "$1" <<'PY' || die "commit message rejected by the SO-7 validator above"
import sys
msg = sys.argv[1]
if not msg.strip():
    print("message is empty", file=sys.stderr)
    sys.exit(1)
first = msg.strip().splitlines()[0].strip()
if len(first) < 8:
    print(f"first line is too short to be a useful subject: {first!r}", file=sys.stderr)
    sys.exit(1)
banned = "\u2014\u2013\u2012\u2015\u2e3a\u2e3b"
for ch in msg:
    if ch in banned:
        print(f"SO-7: banned dash character U+{ord(ch):04X} in the message", file=sys.stderr)
        sys.exit(1)
for trailer in ("co-authored-by:", "generated with", "generated-by:", "signed-off-by:"):
    if trailer in msg.lower():
        print(f"SO-7: banned trailer pattern {trailer!r} in the message", file=sys.stderr)
        sys.exit(1)
print("   message passes the SO-7 style rules")
PY
}
validate_message "$MESSAGE"

[[ -f scripts/check_governance.py ]] || die "scripts/check_governance.py is missing; cannot validate locally"
note "base commit: $(git rev-parse --short "origin/$BASE" 2>/dev/null || echo 'origin/'$BASE' not fetched yet')"

if (( DRY_RUN )); then
    step "dry run: nothing will be staged, committed, pushed, or merged"
    note "would stage:"; git status --short | sed "s/^/     /"
    note "with message: $(printf "%s" "$MESSAGE" | head -n1)"
    note "phases: commit -> sync -> validate -> publish (until: $UNTIL)"
    note "run without --dry-run to execute"
    exit 0
fi

# ------------------------------------------------------------- 1/4 commit
step "1/4 commit"
if (( ${#PATHS[@]} )); then
    note "staging only the given paths"
    git add -- "${PATHS[@]}"
else
    note "staging every change under the repository (respects .gitignore)"
    git add -A
fi
git status --short | sed "s/^/     /"
if git diff --cached --quiet; then
    # The resume path, for example after a rebase conflict was resolved by
    # hand: the work is already committed, so this phase is a no-op instead of
    # an error, and the run continues from the sync step.
    ahead=$(git rev-list --count "origin/$BASE..HEAD" 2>/dev/null || echo 0)
    (( ahead > 0 )) || die "nothing to commit and no commits ahead of origin/$BASE: there is nothing to land"
    note "nothing new to commit; continuing with the $ahead commit(s) already ahead of origin/$BASE"
else
    if (( ! ASSUME_YES )); then
        [[ -t 0 ]] || die "no terminal for confirmation; pass --yes to accept the staged set"
        read -r -p "   commit these changes as '$OWNER_NAME'? [y/N] " answer
        [[ "$answer" == [Yy] ]] || die "declined at the confirmation prompt"
    fi
    git commit -m "$MESSAGE"
    note "commit: $(git log --oneline -1)"
fi
if [[ "$UNTIL" == "commit" ]]; then
    printf "\nStopping after the commit phase (--until commit). Nothing was pushed.\n"
    exit 0
fi

# --------------------------------------------------------------- 2/4 sync
step "2/4 sync with origin/$BASE"
git fetch origin --prune
note "rebasing $BRANCH onto origin/$BASE"
if ! git pull --rebase origin "$BASE"; then
    git rebase --abort 2>/dev/null || true
    die "rebase conflict against origin/$BASE. Resolve it by hand (fix the files, git add them, git rebase --continue), then rerun land.sh: the work is already committed, so it skips the commit phase and continues. The rebase was aborted; your branch is unchanged."
fi
note "branch is now on top of $(git rev-parse --short "origin/$BASE")"
note "commits to land:"; git log --oneline "origin/$BASE..HEAD" | sed "s/^/     /"
if [[ "$UNTIL" == "sync" ]]; then
    printf "\nStopping after the sync phase (--until sync). Nothing was pushed.\n"
    exit 0
fi

# ----------------------------------------------------------- 3/4 validate
step "3/4 validate (same commands the governance-guard workflow runs)"
GOVERN_COMMIT_RANGE="origin/$BASE..HEAD" python scripts/check_governance.py
note "governance: passed"
python -m unittest discover -s tests
note "tests: passed"
if command -v node >/dev/null 2>&1; then
    node --input-type=module --check < cloud/worker.js
    note "worker syntax: passed"
else
    warn "node is not installed here; the worker syntax check runs in CI only"
fi
if [[ "$UNTIL" == "validate" ]]; then
    printf "\nStopping after the validate phase (--until validate). Nothing was pushed.\n"
    exit 0
fi

# ------------------------------------------------------------ 4/4 publish
step "4/4 publish"
command -v gh >/dev/null 2>&1 || die "gh is required to open and merge the pull request"
gh auth status >/dev/null 2>&1 || die "gh is not authenticated; run: gh auth login"

git push -u origin HEAD
note "pushed $BRANCH"

TITLE=$(printf "%s" "$MESSAGE" | head -n1)
if pr=$(gh pr view --json number --jq .number 2>/dev/null); then
    note "reusing the open pull request #$pr"
else
    gh pr create --base "$BASE" --head "$BRANCH" --title "$TITLE" --body "$MESSAGE" >/dev/null
    pr=$(gh pr view --json number --jq .number)
    note "opened pull request #$pr"
fi

step "waiting for CI checks on PR #$pr"
for _ in $(seq 1 18); do
    names=$(gh pr checks "$pr" --json name --jq ".[].name" 2>/dev/null || true)
    [[ -n "$names" ]] && break
    sleep 10
done
[[ -n "${names:-}" ]] || die "no CI checks appeared on PR #$pr after three minutes; refusing to merge unvalidated"
if ! gh pr checks "$pr" --watch --fail-fast; then
    gh pr checks "$pr" || true
    die "CI checks failed on PR #$pr; nothing was merged"
fi
note "all checks passed"

for _ in $(seq 1 6); do
    mergeable=$(gh pr view "$pr" --json mergeable --jq .mergeable)
    [[ "$mergeable" != "UNKNOWN" ]] && break
    sleep 5
done
[[ "${mergeable:-}" == "MERGEABLE" ]] || die "PR #$pr is not mergeable right now (state: ${mergeable:-unknown}). If $BASE moved, rerun land.sh to resync."

merge_args=(--merge)
(( DELETE_BRANCH )) && merge_args+=(--delete-branch)
gh pr merge "$pr" "${merge_args[@]}"
note "merged PR #$pr into $BASE"

merge_sha=$(gh pr view "$pr" --json mergeCommit --jq ".mergeCommit.oid" 2>/dev/null || true)
[[ -n "$merge_sha" ]] && note "merge commit: ${merge_sha:0:10}"

if git show-ref --verify --quiet "refs/heads/$BASE"; then
    git checkout "$BASE"
    git pull --ff-only origin "$BASE"
    note "local $BASE is up to date"
fi

step "landed"
note "PR #$pr: $TITLE"
note "phases completed: commit, sync, validate, publish"
note "finished $(now_pkt)"
