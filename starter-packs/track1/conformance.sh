#!/usr/bin/env bash
# Run your agent against every public unit and check it behaves. Locally, offline, in minutes.
#
#   ./conformance.sh <your-image> [path-to-track1-coding-public]
#
# This is the highest-value thing in the pack. Two separate submissions were burned on failures
# this would have caught before any push: an agent that assumed every input was parquet (4 of 87
# units have one), and an agent that wrote `results.parquet` for a unit whose checker wanted
# `results.json`. This script can now read an expected filename for all 87 units: 41 name
# `results.json` and 37 name `summary.json`; the exemplar is the only one naming a `.parquet`
# deliverable.
#
# It does NOT tell you whether your answers are right -- run the unit's own
# `checks/test_outputs.py` for that. It tells you the two things that make a submission score zero
# without ever being about your finance:
#
#   1. did the agent exit 0, on every unit, without crashing
#   2. did it write a file that unit's checker expects in the OUTPUT directory
#
# On (2), read `want` below for exactly what is compared. The names come from the quoted literals
# in the unit's `checks/*.py`, restricted to the ones the checker resolves against the output
# directory -- names it reaches through a data, reference or log root are not deliverables of
# yours, and matching on those would pass an agent that wrote nothing of its own.
#
# And where it cannot read a unit's expected filename at all, it says so -- UNCHECKED -- rather
# than counting the unit as `ok`. No public unit lands there today: the 11 whose `test_outputs.py`
# delegates to `checks/verifier.py` and names no file itself are covered now that the sweep reads
# that second module too. UNCHECKED is not a failure and does not change the exit status; it means
# this script proved nothing about that unit, so run that unit's own checker before you rely on it.
#
# Offline by design: `--network=none` is stricter than the `restricted` mode used in scoring, so
# anything that passes here will not surprise you later.
set -uo pipefail

IMAGE="${1:?usage: conformance.sh <your-image> [kit-path]}"
KIT="${2:-.}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0; CRASH=0; MISSING=0; UNCHECKED=0; TOTAL=0
CRASHED=""; NOFILE=""; NOWANT=""

for unit in "$KIT"/units/t1-*; do
    [ -d "$unit" ] || continue
    id="$(basename "$unit")"
    TOTAL=$((TOTAL + 1))
    out="$WORK/$id"; mkdir -p "$out"

    # Both output paths, because the checkers disagree about which they read and the real harness
    # binds the same directory at both.
    docker run --rm --network=none \
        -v "$(cd "$unit" && pwd)":/input:ro \
        -v "$out":/output -v "$out":/app/output \
        "$IMAGE" solve --task-dir /input --out /app/output >"$out/.stdout" 2>"$out/.stderr"
    rc=$?

    # The filenames this unit's checker expects to find in the OUTPUT directory. Quoted literals
    # in the checker are the only machine-readable statement of the output contract -- there is no
    # schema file. Take single quotes as well as double, and the basename of a quoted path: most
    # checkers write Path("/app/output/results.csv") or f"{OUTPUT_DIR}/results.csv", not a bare
    # filename.
    #
    # Read every `checks/*.py`, not just `test_outputs.py`. On some units `test_outputs.py` is a
    # thin shim that imports `run_verification` from `checks/verifier.py` and names no file
    # itself; the filenames it will look for are literals in that second module. Units with a
    # `conftest.py` are picked up by the same glob.
    #
    # Position, not spelling, separates a deliverable from an input, and only deliverables belong
    # in `want`. A checker names a deliverable either bare -- a helper joins it to the output dir,
    # as in load_json("summary.json") -- or under an output root. It reaches an INPUT through a
    # data or reference root instead: DATA_DIR, data_dir, INPUT_PATH, REF_DIR, input_csv(),
    # /app/data/..., /app/<file>, /tests/reference_data. Input and reference files ship with the
    # unit, so they exist before the agent starts; accepting one here would credit an agent that
    # wrote no deliverable at all.
    #
    # A THIRD root has to be dropped now that `verifier.py` and `conftest.py` are read: the LOG
    # directory. Both write `reward.txt`, `diagnostic.json` and `reward_summary.json` through a
    # `log_dir` / `LOG_DIR` / `/logs/verifier` root. Those are the scorer's own artifacts, not
    # yours -- the checker writes them, it never expects to find them -- so they are dropped the
    # same way an input is.
    #
    # So drop the lines that reach into an input, reference or log root first, then keep only bare
    # names and output-rooted ones. Finally drop anything still carrying an unresolved `{...}` --
    # that is an f-string hole, not a name.
    want="$(grep -hE "['\"][A-Za-z0-9_./{}-]+\.(json|parquet|csv|txt)['\"]" \
              "$unit"/checks/*.py 2>/dev/null \
            | grep -viE '(data|input|ref|reference|log)_(dir|path)|input_(json|csv|parquet|text)|/app/data|/input|/tests/reference|/logs|[^a-z0-9_](data|ref) */' \
            | grep -oE "['\"][A-Za-z0-9_./{}-]+\.(json|parquet|csv|txt)['\"]" \
            | tr -d "'\"" \
            | grep -E '^[^/]+$|^(/app)?/output/|^\{OUTPUT_DIR\}/' \
            | sed 's:.*/::' | grep -v '[{}]' | sort -u)"

    if [ "$rc" -ne 0 ]; then
        CRASH=$((CRASH + 1)); CRASHED="$CRASHED $id"
        printf '%-46s CRASH exit=%s  %s\n' "$id" "$rc" "$(tail -1 "$out/.stderr" 2>/dev/null | cut -c1-70)"
        continue
    fi

    # No filename to check against means we know nothing about this unit. Say so; do not count it
    # as a pass. An agent that writes nothing at all used to be credited `ok` here.
    if [ -z "$want" ]; then
        UNCHECKED=$((UNCHECKED + 1)); NOWANT="$NOWANT $id"
        printf '%-46s exit 0, no expected filename readable -- UNCHECKED\n' "$id"
        continue
    fi

    # Any one of the expected names is enough. `want` holds only names the checker resolves
    # against the output directory, but a unit with several deliverables is still a pass here if
    # it wrote any one of them -- this is a floor check, not a completeness check. Run the unit's
    # own test_outputs.py to find out whether you wrote all of them, and wrote them correctly.
    hit=0
    for f in $want; do [ -f "$out/$f" ] && hit=1 && break; done
    if [ "$hit" -eq 0 ]; then
        MISSING=$((MISSING + 1)); NOFILE="$NOFILE $id"
        printf '%-46s exit 0 but wrote none of: %s\n' "$id" "$(echo $want | cut -c1-60)"
        continue
    fi
    PASS=$((PASS + 1))
done

if [ "$TOTAL" -eq 0 ]; then
    echo "no units found under $KIT/units/ -- wrong kit path?" >&2
    echo "pass the kit as the second argument: ./conformance.sh <your-image> /path/to/track1-coding-public" >&2
    exit 2
fi

echo
echo "units $TOTAL   ok $PASS   crashed $CRASH   wrote-nothing-expected $MISSING   unchecked $UNCHECKED"
[ -n "$CRASHED" ] && { echo; echo "CRASHED:"; for u in $CRASHED; do echo "  $u"; done; }
[ -n "$NOFILE" ]  && { echo; echo "NO EXPECTED OUTPUT:"; for u in $NOFILE; do echo "  $u"; done; }
[ -n "$NOWANT" ]  && { echo; echo "UNCHECKED -- no expected filename in checks/test_outputs.py, so"; \
                       echo "this script proved nothing here. Run each unit's own checker:"; \
                       for u in $NOWANT; do echo "  $u"; done; }

echo
echo "Reminder: exit 0 and the right filename is the FLOOR, not a pass. Run the unit's own"
echo "checks/test_outputs.py to find out whether the numbers are right."
[ "$TOTAL" -gt 0 ] && [ "$CRASH" -eq 0 ] && [ "$MISSING" -eq 0 ]
