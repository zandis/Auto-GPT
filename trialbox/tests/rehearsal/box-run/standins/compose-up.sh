#!/bin/sh
# Stand-in for `docker compose up -d --wait` in the real deploy/box-install.sh (its knob TB_BOX_COMPOSE): the stand-in
# box is "up" on the owner's answers (the paid run: the box's real stack restarts).
echo "compose $*" >> "$BR_S/calls.log"
exec python3 "$(dirname "$0")/box.py" wizard-done
