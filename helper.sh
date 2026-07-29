#!/bin/bash -e

for f in $(./lint.sh 2>&1 | rg -o '^[^:]+\.py' | sort -u); do
    echo "# $f"
    cat -n "$f"
    echo
done

echo "# Lint and pytest"

./lint.sh 2>&1
