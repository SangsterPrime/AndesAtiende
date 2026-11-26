#!/bin/sh
set -eu
# Validar antes de envsubst: impedir comillas/directivas inyectadas en nginx.conf.
# Nunca imprimir el valor ni usar set -x.
case "${EP3_API_KEY:-}" in
    ''|*[!A-Za-z0-9_-]*)
        echo 'EP3_API_KEY debe contener 32 a 128 caracteres URL-safe' >&2
        exit 1
        ;;
esac
if [ "${#EP3_API_KEY}" -lt 32 ] || [ "${#EP3_API_KEY}" -gt 128 ]; then
    echo 'EP3_API_KEY debe contener 32 a 128 caracteres URL-safe' >&2
    exit 1
fi
