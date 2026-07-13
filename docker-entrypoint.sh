#!/bin/sh
set -e

if [ "$1" = "serve" ]; then
    shift
    exec qsardb-client-server "$@"
fi

exec qsardb-client "$@"
