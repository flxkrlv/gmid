#!/usr/bin/env bash
# ===========================================================================
# run_gmid.sh — запуск генераторов gm/ID LUT в окружении Cadence.
#
# Делает три вещи:
#   1) подключает окружение Cadence (Spectre, лицензии, PATH);
#   2) убирает из LD_LIBRARY_PATH каталоги с libpython Cadence — иначе
#      системный/venv Python не стартует («ModuleNotFoundError: encodings»);
#   3) запускает нужный скрипт (по умолчанию gmid_lut.py).
#
# Использование (по умолчанию запускается gmid_lut.py):
#     ./run_gmid.sh                              # прогон по моделям из блока НАСТРОЙКИ
#     ./run_gmid.sh --quick                      # быстрый тест
#     ./run_gmid.sh --report                     # + PDF-отчёт (LaTeX)
#     ./run_gmid.sh --report-dir lut_gpdk180     # отчёты по всем .npz каталога
#     ./run_gmid.sh --interactive                # + HTML-дашборд (Plotly)
#     # пример GPDK180: ядро 1.8 В, углы NN/SS/FF/SF/FS
#     ./run_gmid.sh -m "$GPDK180/models/spectre/gpdk.scs" \
#                    --corner NN SS FF SF FS \
#                    --nmos-model nmos1 --pmos-model pmos1 \
#                    --vdd 1.8 --vgs-start 0.2 --techname gpdk180
#     .venv/bin/python gmid_dash.py lut_gpdk180  # один просмотрщик на все .npz
#
# Первый аргумент считается именем скрипта, если это существующий *.py файл.
# Явно задать скрипт можно через переменную окружения $GMID_SCRIPT
# (по умолчанию — gmid_lut.py).
#
# Python берётся в таком порядке:
#     $GMID_PYTHON  ->  ./.venv/bin/python  ->  python3
# ===========================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- выбор скрипта ----------------------------------------------------------
SCRIPT="${GMID_SCRIPT:-}"

# Если скрипт не задан переменной, а первый аргумент — существующий .py файл,
# заберём его как имя скрипта, а остальные аргументы оставим скрипту.
if [[ -z "$SCRIPT" && $# -gt 0 ]]; then
    case "$1" in
        *.py)
            if [[ -f "$HERE/$1" ]]; then
                SCRIPT="$HERE/$1"; shift
            elif [[ -f "$1" ]]; then
                SCRIPT="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"; shift
            fi
            ;;
    esac
fi
[[ -z "$SCRIPT" ]] && SCRIPT="$HERE/gmid_lut.py"

# --- 1. окружение Cadence (Spectre, лицензии, PATH) ------------------------
# shellcheck disable=SC1090
source "${HOME}/.bashrc.cadence" >/dev/null 2>&1 || true

# --- 2. чистим LD_LIBRARY_PATH от Python-библиотек Cadence -----------------
if [[ -n "${LD_LIBRARY_PATH:-}" ]]; then
    export LD_LIBRARY_PATH="$(echo "$LD_LIBRARY_PATH" \
        | tr ':' '\n' | grep -v 'python' | grep -v '^$' | paste -sd:)"
fi

# --- 3. выбираем интерпретатор Python --------------------------------------
PY="${GMID_PYTHON:-}"
if [[ -z "$PY" ]]; then
    if [[ -x "${HERE}/.venv/bin/python" ]]; then
        PY="${HERE}/.venv/bin/python"
    else
        PY="python3"
    fi
fi

echo "[run_gmid] script : ${SCRIPT}"
echo "[run_gmid] python : ${PY}"
echo "[run_gmid] spectre: $(command -v spectre || echo 'НЕ НАЙДЕН — проверьте ~/.bashrc.cadence')"

exec "${PY}" "${SCRIPT}" "$@"
