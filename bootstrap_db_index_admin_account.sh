#!/usr/bin/env bash
set -euo pipefail

# podc --env-file development.env -f docker-compose.yml -f compose.yml
podman-compose --env-file development.env -f docker-compose.yml -f compose.yml exec api bonsai_api index
podman-compose --env-file development.env -f docker-compose.yml -f compose.yml exec api bonsai_api create-user -u admin                 \
                                               -p admin                 \
                                               --fname Place            \
                                               --lname Holder           \
                                               -m place.holder@example.com \
                                               -r admin
