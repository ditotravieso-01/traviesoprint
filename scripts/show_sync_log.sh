#!/bin/bash
# ============================================================
#  TraviesoPrint · Visor del log de sincronización con Odoo
#
#  Muestra los últimos N ciclos de sync con fecha, hora y
#  detalle de clientes nuevos, actualizados y errores.
#
#  Uso:
#    ./scripts/show_sync_log.sh         # últimos 5 ciclos
#    ./scripts/show_sync_log.sh 10      # últimos 10 ciclos
#    sudo ./scripts/show_sync_log.sh    # si no tienes permisos
# ============================================================
set -euo pipefail

N="${1:-5}"
LOG_FILE="/var/log/traviesoprint/sync.log"

# Colores
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'
RED='\033[0;31m'; GRAY='\033[0;90m'; BOLD='\033[1m'; NC='\033[0m'

if [ ! -f "${LOG_FILE}" ]; then
    echo -e "${RED}No existe ${LOG_FILE}${NC}"
    echo "El cron aún no ha corrido o la integración no está configurada."
    exit 1
fi

if [ ! -r "${LOG_FILE}" ]; then
    echo -e "${YELLOW}No tienes permiso para leer ${LOG_FILE}.${NC}"
    echo "Ejecutá con sudo:"
    echo "  sudo $0 $*"
    exit 1
fi

# Validar que N sea número
if ! [[ "${N}" =~ ^[0-9]+$ ]] || [ "${N}" -lt 1 ]; then
    echo -e "${RED}Argumento inválido. Debe ser un número entero positivo.${NC}"
    exit 1
fi

# Contar bloques
total_blocks=$(grep -c '^=== SYNC START' "${LOG_FILE}" 2>/dev/null || echo 0)

echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD} TraviesoPrint · Log de sincronización con Odoo${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"
echo -e " ${GRAY}Archivo:${NC}  ${LOG_FILE}"
echo -e " ${GRAY}Bloques:${NC}  ${total_blocks} totales · mostrando últimos ${N}"
echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"

if [ "${total_blocks}" -eq 0 ]; then
    echo ""
    echo -e "${YELLOW}El log no contiene bloques en formato nuevo.${NC}"
    echo ""
    echo -e "${GRAY}Últimas líneas del log:${NC}"
    tail -10 "${LOG_FILE}"
    echo ""
    echo -e "${GRAY}Nota: el formato '=== SYNC START ===' se introduce al${NC}"
    echo -e "${GRAY}actualizar app/cli.py. Los ciclos viejos no lo tienen.${NC}"
    exit 0
fi

# Extraer los últimos N bloques con awk
BLOCKS="$(awk -v n="${N}" '
    /^=== SYNC START/ {
        block_idx++
        in_block = 1
        block[block_idx] = $0 "\n"
        next
    }
    in_block {
        block[block_idx] = block[block_idx] $0 "\n"
        if (/^=== SYNC END/) {
            in_block = 0
        }
    }
    END {
        start = block_idx - n + 1
        if (start < 1) start = 1
        for (i = start; i <= block_idx; i++) {
            printf "----BLOCK-START----\n"
            printf "%s", block[i]
            printf "----BLOCK-END----\n"
        }
    }
' "${LOG_FILE}")"

# Procesar cada bloque
idx=0
total_shown=$(echo "${BLOCKS}" | grep -c '^----BLOCK-START----' || echo 0)

echo "${BLOCKS}" | awk -v total="${total_shown}" '
BEGIN {
    green="\033[0;32m"; yellow="\033[1;33m"; red="\033[0;31m"
    blue="\033[0;34m"; gray="\033[0;90m"; bold="\033[1m"; nc="\033[0m"
    idx = 0
}
/^----BLOCK-START----/ {
    idx++
    in_block = 1
    start_line = ""
    end_line = ""
    nuevos = 0; actualizados = 0; errores = 0; sin_cambios = 0; total_proc = 0
    detalles = ""
    next
}
/^----BLOCK-END----/ {
    in_block = 0
    printf "\n%s[%d/%d]%s  %s%s%s\n", bold, idx, total, nc, blue, start_time, nc
    if (end_time != "") {
        printf "  %sFinalizó: %s · duró %ss%s\n", gray, end_time, elapsed, nc
    }
    printf "  Total procesados: %s%d%s\n", bold, total_proc, nc
    if (nuevos > 0) {
        printf "  %sNuevos:%s %s%d%s\n", green, nc, bold, nuevos, nc
    } else {
        printf "  Nuevos: %d\n", nuevos
    }
    if (actualizados > 0) {
        printf "  %sActualizados:%s %s%d%s\n", yellow, nc, bold, actualizados, nc
    } else {
        printf "  Actualizados: %d\n", actualizados
    }
    if (sin_cambios > 0) printf "  Sin cambios: %d\n", sin_cambios
    if (errores > 0) {
        printf "  %sErrores:%s %s%d%s\n", red, nc, bold, errores, nc
    } else {
        printf "  Errores: %d\n", errores
    }
    if (detalles != "") {
        printf "%s", detalles
    }
    next
}
in_block {
    if (/^=== SYNC START /) {
        # Extraer timestamp
        match($0, /=== SYNC START (.*) ===/, m)
        start_time = m[1]
    } else if (/^=== SYNC END /) {
        match($0, /=== SYNC END (.*) \(([0-9.]+)s\) ===/, m)
        end_time = m[1]
        elapsed = m[2]
    } else if (/^Total procesados: /) {
        sub(/^Total procesados: /, "")
        total_proc = $0 + 0
    } else if (/^Nuevos: /) {
        sub(/^Nuevos: /, "")
        nuevos = $0 + 0
    } else if (/^Actualizados: /) {
        sub(/^Actualizados: /, "")
        actualizados = $0 + 0
    } else if (/^Sin cambios: /) {
        sub(/^Sin cambios: /, "")
        sin_cambios = $0 + 0
    } else if (/^Errores: /) {
        sub(/^Errores: /, "")
        errores = $0 + 0
    } else if (/^  \+ /) {
        nombre = $0
        sub(/^  \+ /, "", nombre)
        detalles = detalles sprintf("    %s+%s %s\n", green, nc, nombre)
    } else if (/^  ~ /) {
        nombre = $0
        sub(/^  ~ /, "", nombre)
        detalles = detalles sprintf("    %s~%s %s\n", yellow, nc, nombre)
    } else if (/^  ! /) {
        nombre = $0
        sub(/^  ! /, "", nombre)
        detalles = detalles sprintf("    %s!%s %s\n", red, nc, nombre)
    } else if (/^  \.\.\. y /) {
        detalles = detalles sprintf("    %s%s%s\n", gray, $0, nc)
    }
}
END {
    print ""
}
'

echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"
echo -e " ${GRAY}Comandos útiles:${NC}"
echo -e "   ${GRAY}tail -f ${LOG_FILE}${NC}             ${GRAY}# ver en vivo${NC}"
echo -e "   ${GRAY}sudo crontab -u travieso -l${NC}      ${GRAY}# ver cron${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"
echo ""
