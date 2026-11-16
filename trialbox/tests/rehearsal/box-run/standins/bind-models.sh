#!/bin/sh
# Stand-in for the bind mount of the VM's weights into deploy/models (validation mode, d_models_place): the paid run
# binds /models (root on the VM); here the call is written down and the folder made.
echo "bind-models $1 -> $2" >> "$BR_S/calls.log"
mkdir -p "$2"
