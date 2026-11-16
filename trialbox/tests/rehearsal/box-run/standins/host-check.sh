#!/bin/sh
# Stand-in for deploy/check_host.sh in the real deploy/box-install.sh (its knob TB_BOX_HOST_CHECK): a FAIL list, as a
# fresh cloud box without a backup target would have (the paid run: the real host check; 10-doctor judges it).
echo "hostcheck" >> "$BR_S/calls.log"
echo "FAIL backup: no target"
exit 1
