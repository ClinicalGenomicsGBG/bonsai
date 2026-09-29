#!/usr/bin/env bash
set -euo pipefail

podman-compose exec api bonsai_api index
podman-compose exec api bonsai_api create-user -u admin                 \
                                               -p admin                 \
                                               --fname Place            \
                                               --lname Holder           \
                                               -m place.holder@example.com \
                                               -r admin
