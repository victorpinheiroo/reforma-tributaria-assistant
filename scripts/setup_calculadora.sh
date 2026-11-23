#!/usr/bin/env bash
# Fetch, build and run the official calculator at a pinned version, with a portable JDK 25.
#   scripts/setup_calculadora.sh            # clone + database + jar (idempotent)
#   scripts/setup_calculadora.sh run        # start on :8080 (offline profile)
set -euo pipefail
VERSION="1.7.2"   # pin: bump deliberately and re-run the spike/fixtures
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
JDK="$(ls -d "$ROOT"/tools/jdk-25* 2>/dev/null | head -1 || true)"
[ -n "$JDK" ] || { echo "Portable JDK 25 not found in tools/ (see docs/PLAN.md)"; exit 1; }
export JAVA_HOME="$JDK" PATH="$JDK/bin:$PATH"
CALC="$ROOT/vendor/calculadora"
if [ ! -d "$CALC" ]; then
  git clone --depth 1 --branch "$VERSION" https://github.com/ReceitaFederal/calculadora-rtc-regime-regular.git "$CALC"
fi
cd "$CALC"
if [ ! -f calculadora/db/calculadora-pro.db ]; then
  mkdir -p calculadora/db
  ./mvnw flyway:migrate -Dflyway.configFiles=./flyway/flyway-pro.conf --batch-mode --errors -q
fi
[ -f target/api-regime-geral.jar ] || ./mvnw clean package -DskipTests --batch-mode -q
if [ "${1:-}" = "run" ]; then
  exec java -Dspring.profiles.active=offline -jar target/api-regime-geral.jar
fi
echo "ready: $CALC/target/api-regime-geral.jar (run with: $0 run)"
