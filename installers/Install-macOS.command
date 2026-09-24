#!/bin/zsh
cd "$(dirname "$0")"
python3 install.py
status=$?
echo "Installer exit status: $status"
read -k 1 "?Press any key to close."
exit $status
