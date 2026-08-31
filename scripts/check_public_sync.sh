#!/usr/bin/env bash
# Verify this staging repo has not been bypassed.
#
# Staging is EXPECTED to be ahead of public -- that is where work happens.
# The failure this catches is the opposite: a commit on public that is NOT in
# staging, which means someone edited the public repo directly instead of
# publishing from here. That silently forks the two and is how a release
# quietly loses a fix.
#
# Exit 0  staging contains every public commit (ahead or equal)   -- healthy
# Exit 1  public has commits staging does not                     -- bypassed
# Exit 2  could not determine                                     -- never a pass
set -uo pipefail

PUBLIC_REPO="${PUBLIC_REPO:-}"
if [[ -z "$PUBLIC_REPO" ]]; then
  # staging repo is <public-name>-staging; strip the suffix.
  origin="$(git config --get remote.origin.url || true)"
  name="$(basename "${origin%.git}")"
  PUBLIC_REPO="Agenthon-2026/${name%-staging}"
fi
echo "staging : $(git rev-parse --abbrev-ref HEAD) @ $(git rev-parse --short HEAD)"
echo "public  : $PUBLIC_REPO"

git remote remove _public 2>/dev/null || true
git remote add _public "https://github.com/${PUBLIC_REPO}.git"
if ! git fetch -q _public main --depth=200 2>/dev/null; then
  echo "RESULT: UNDETERMINED -- could not fetch $PUBLIC_REPO"
  echo "A check that cannot run is not a pass."
  git remote remove _public 2>/dev/null || true
  exit 2
fi

missing="$(git rev-list --count HEAD.._public/main 2>/dev/null || echo ERR)"
ahead="$(git rev-list --count _public/main..HEAD 2>/dev/null || echo ERR)"
if [[ "$missing" == "ERR" || "$ahead" == "ERR" ]]; then
  echo "RESULT: UNDETERMINED -- histories unrelated"; git remote remove _public; exit 2
fi

echo "staging is ahead of public by : $ahead commit(s)"
echo "public has commits missing here: $missing"

if [[ "$missing" -ne 0 ]]; then
  echo
  echo "RESULT: FAIL -- public was edited directly."
  echo "These commits exist on public and not here:"
  git log --oneline HEAD.._public/main | sed 's/^/  /'
  echo
  echo "Fix: merge them into staging before publishing again, or the next"
  echo "release will silently revert them."
  git remote remove _public; exit 1
fi

echo
echo "RESULT: OK -- nothing on public is missing here."
if [[ "$ahead" -gt 0 ]]; then
  echo "Pending release (staging ahead by $ahead):"
  git log --oneline _public/main..HEAD | sed 's/^/  /'
fi
git remote remove _public
exit 0
