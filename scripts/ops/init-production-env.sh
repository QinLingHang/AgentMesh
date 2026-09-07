#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
OUTPUT=${1:-"$ROOT/.env.production"}
[ ! -e "$OUTPUT" ] || { echo "$OUTPUT already exists" >&2; exit 1; }
cp "$ROOT/.env.production.example" "$OUTPUT"
mysql_secret=$(openssl rand -hex 24)
mysql_root_secret=$(openssl rand -hex 24)
minio_secret=$(openssl rand -hex 32)
jwt_secret=$(openssl rand -hex 48)
governance_secret=$(openssl rand -hex 48)
verification_secret=$(openssl rand -hex 24)
runtime_secret=$(openssl rand -hex 24)
sed -i \
  -e "s/CHANGE_ME_mysql_password/$mysql_secret/g" \
  -e "s/CHANGE_ME_mysql_root_password/$mysql_root_secret/g" \
  -e "s/CHANGE_ME_minio_secret/$minio_secret/g" \
  -e "s/CHANGE_ME_jwt_secret_at_least_32_characters/$jwt_secret/g" \
  -e "s/CHANGE_ME_governance_master_key_at_least_32_characters/$governance_secret/g" \
  -e "s/CHANGE_ME_verification_pepper_at_least_16_characters/$verification_secret/g" \
  -e "s/CHANGE_ME_runtime_internal_token_at_least_16_characters/$runtime_secret/g" \
  "$OUTPUT"
chmod 600 "$OUTPUT" 2>/dev/null || true
echo "Created $OUTPUT with generated local secrets. Review public origin/TLS/email/model settings."
