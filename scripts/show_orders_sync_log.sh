#!/bin/bash
# ============================================================
#  TraviesoPrint - Visor del log de sync de ÓRDENES
#
#  Uso:
#    sudo ./show_orders_sync_log.sh                # últimas 10 ejecuciones
#    sudo ./show_orders_sync_log.sh --last 20      # últimas 20
#    sudo ./show_orders_sync_log.sh --errors-only  # solo con errores
#    sudo ./show_orders_sync_log.sh --since "2026-10-12 18:00"
#    sudo ./show_orders_sync_log.sh --follow       # en vivo (tail -f filtrado)
# ============================================================

set -euo pipefail

LOG_FILE="/var/log/traviesoprint/sync_orders.log"
START_MARK="=== ORDERS SYNC START"
END_MARK="=== ORDERS SYNC END"

LAST_N=10
ERRORS_ONLY=0
SINCE=""
FOLLOW=0

# --- Parsear argumentos ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --last)         LAST_N="$2"; shift 2 ;;
        --errors-only)  ERRORS_ONLY=1; shift ;;
        --since)        SINCE="$2"; shift 2 ;;
        --follow)       FOLLOW=1; shift ;;
        -h|--help)
            grep -E '^#  (Uso|    sudo)' "$0" | sed 's/^#  //'
            exit 0 ;;
        *) echo "Argumento desconocido: $1"; exit 1 ;;
    esac
done

if [ ! -f "${LOG_FILE}" ]; then
    echo "No existe ${LOG_FILE}"
    exit 1
fi

# --- Modo follow: solo líneas relevantes ---
if [ "${FOLLOW}" -eq 1 ]; then
    echo "Siguiendo ${LOG_FILE} (solo bloques de sync de órdenes)..."
    echo "Ctrl+C para salir."
    echo ""
    tail -F "${LOG_FILE}" | awk -v s="${START_MARK}" -v e="${END_MARK}" '
        $0 ~ s { print; in_block=1; next }
        $0 ~ e { print; in_block=0; next }
        in_block { print }
    '
    exit 0
fi

# --- Extraer bloques completos ---
extract_blocks() {
    awk -v s="${START_MARK}" -v e="${END_MARK}" '
        $0 ~ s {
            if (in_block) { print buffer }
            in_block=1; buffer=$0"\n"; next
        }
        in_block {
            buffer = buffer $0 "\n"
            if ($0 ~ e) { print buffer; in_block=0; buffer="" }
        }
        END { if (in_block) print buffer }
    ' "${LOG_FILE}"
}

# --- Aplicar filtros ---
BLOCKS=$(extract_blocks)

if [ -n "${SINCE}" ]; then
    BLOCKS=$(echo "${BLOCKS}" | awk -v since="${SINCE}" '
        /=== ORDERS SYNC START/ {
            block=""; keep=0
            # Extraer fecha del bloque
            match($0, /START ([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})/, m)
            if (m[1] >= since) keep=1
        }
        { block = block $0 "\n" }
        /=== ORDERS SYNC END/ {
            if (keep) printf "%s", block
            block=""
        }
    ')
fi

if [ "${ERRORS_ONLY}" -eq 1 ]; then
    BLOCKS=$(echo "${BLOCKS}" | awk '
        BEGIN { RS="=== ORDERS SYNC END"; ORS="=== ORDERS SYNC END\n" }
        /Errores: [^0]/ || /ERROR/ { print }
    ')
fi

if [ -z "${BLOCKS}" ]; then
    echo "No hay bloques de sync que coincidan con los filtros."
    exit 0
fi

# --- Mostrar los últimos N bloques ---
BLOCK_COUNT=$(echo "${BLOCKS}" | grep -c "^=== ORDERS SYNC START" || true)
echo "Total bloques: ${BLOCK_COUNT}. Mostrando últimos ${LAST_N}."
echo ""

echo "${BLOCKS}" | awk -v n="${LAST_N}" '
    BEGIN { RS="=== ORDERS SYNC END\n?"; }
    { blocks[NR] = $0 }
    END {
        start = NR - n + 1
        if (start < 1) start = 1
        for (i = start; i <= NR; i++) {
            printf "%s=== ORDERS SYNC END\n\n", blocks[i]
        }
    }
'
