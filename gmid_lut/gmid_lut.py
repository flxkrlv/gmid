#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gmid_lut.py — УНИВЕРСАЛЬНЫЙ генератор gm/ID LUT и графиков (Spectre).
======================================================================

Работает с любым PDK, для которого есть Spectre-файл моделей (.scs) и в нём
заданы MOS-модели (например `model nmos ...` / `model pmos ...` или
`subckt nmos ...`).

Что делает:
  1. Запускает Spectre для DC-разверток заданных MOS-моделей (одной или
     НЕСКОЛЬКИХ на тип: NMOS_MODELS / PMOS_MODELS — списком).
  2. Сохраняет LUT-таблицу  length × vbs × vgs × vds  в  lut_<techname>/<...>.npz.
  3. Строит SVG-графики (на каждое устройство):
       ID/W(gm/ID), fT(gm/ID), gm·ro(gm/ID), gm/ID(Vov), ID(VGS), ID(VDS),
       Vdsat/Vov/V*(VGS). Если модель не отдаёт Cgg (HV-модели без capmod),
       fT пропускается (методика gm/ID работает и без ёмкостей).
  4. Печатает пример расчёта (сайзинга) по таблице.
  5. По флагу --report собирает PDF-отчёт (LaTeX) со всеми графиками,
     расшифровкой всех параметров LUT и таблицами основных точек.
     Флаг --report-dir PATH собирает отчёты сразу по ВСЕМ .npz в каталоге
     (рекурсивно) — без пересборки LUT и без Spectre.
  6. По флагу --interactive собирает автономный HTML-дашборд (Plotly):
     все графики с hover/зумом, переключатели устройство/VDS/VBS и
     калькулятор рабочей точки (см. gmid_dash.py).

Модели можно задавать либо файлом (MODELS_FILE), либо КАТАЛОГОМ (MODELS_DIR):
корневой .scs-файл-библиотека ищется автоматически, а `include "..."` (в т.ч.
во вложенных папках fast/slow/type) разворачиваются рекурсивно.

ВСЁ НАСТРАИВАЕТСЯ В БЛОКЕ «НАСТРОЙКИ» НИЖЕ (или через аргументы CLI).

Запуск (через launcher, который подключает окружение Cadence; для Cadence
PDK путь к каталогу удобно задавать переменной окружения, напр. GPDK180):

    ./run_gmid.sh --quick                      # быстрый тест (модели из НАСТРОЕК)
    ./run_gmid.sh --report                     # + PDF-отчёт (LaTeX)
    ./run_gmid.sh --interactive                # + HTML-дашборд (Plotly)
    # отчёты по всем .npz каталога, без пересборки и без Spectre:
    ./run_gmid.sh --no-build --no-plot --report-dir lut_gpdk180
    # пример GPDK180: ядро 1.8 В, углы NN/SS/FF/SF/FS
    ./run_gmid.sh -m "$GPDK180/models/spectre/gpdk.scs" \
        --corner NN SS FF SF FS --nmos-model nmos1 --pmos-model pmos1 \
        --vdd 1.8 --vgs-start 0.2 --techname gpdk180
    # или напрямую:
    source ~/.bashrc.cadence
    export LD_LIBRARY_PATH=$(echo "$LD_LIBRARY_PATH" | tr ':' '\n' | grep -v python | paste -sd:)
    python gmid_lut.py --models-file gpdk.scs --techname gpdk180 --quick
"""

from __future__ import annotations

import os

# Неинтерактивный бэкенд: plt.show() внутри mosplot не должен блокировать прогон.
os.environ.setdefault("MPLBACKEND", "Agg")

import argparse
import datetime
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.show = lambda *a, **k: None  # noqa: E731


# ===========================================================================
# ┌───────────────────────────────────────────────────────────────────────┐
# │                          Н А С Т Р О Й К И                            │
# │  Правьте этот блок под свой PDK. Значения по умолчанию настроены под   │
# │  пример: GPDK180 — gpdk.scs, модели nmos1 / pmos1 (ядро, 1.8 В).      │
# └───────────────────────────────────────────────────────────────────────┘
# ===========================================================================

# --- Файл моделей (.scs) и имена моделей -----------------------------------
# Можно указать либо конкретный .scs (MODELS_FILE), либо КАТАЛОГ с моделями
# (MODELS_DIR): тогда корневой файл-библиотека ищется автоматически, а все
# `include "..."` (в т.ч. во вложенных папках fast/slow/type) разворачиваются.
# Если задан MODELS_DIR, он имеет приоритет над MODELS_FILE.
#
# Пример GPDK180: путь к PDK берём из переменной окружения
#   export GPDK180=/path/to/gpdk180_v3.3
GPDK180_DIR = os.environ.get("GPDK180", "")
MODELS_FILE = (f"{GPDK180_DIR}/models/spectre/gpdk.scs" if GPDK180_DIR
               else "gpdk.scs")                          # путь к .scs с MOS-моделями
MODELS_DIR: str | None = None                            # каталог с моделями (или None)

# Модели задаются СПИСКОМ (несколько устройств одного типа) или одной строкой.
# Пусто/None/'none' — тип выключен (файлы только для NMOS или только для PMOS
# вполне обычны). Для выключенного типа длины/Vdd/старт не используются.
# Пример: NMOS_MODELS = ["nmos1", "nmos_hv"]
NMOS_MODELS: list[str] | str | None = ["nmos1"]
PMOS_MODELS: list[str] | str | None = ["pmos1"]

# --- Углы процесса (секции) ------------------------------------------------
# Файл плоский (обычный include)  -> CORNERS = None
# Файл-библиотека с секциями      -> CORNERS = ["tt", "ss", "ff", ...]
# Пример GPDK180 (gpdk.scs)        -> ["NN", "SS", "FF", "SF", "FS"]
CORNERS: list[str] | None = ["NN", "SS", "FF", "SF", "FS"]

# --- Имя технологии -> выходной каталог lut_<TECHNAME> ---------------------
# None -> lut_<имя файла моделей>
TECHNAME: str | None = "gpdk180"

# --- Длины каналов (м) -----------------------------------------------------
# Пример GPDK180 (ядро): 0.18 ... 10 µm
GPDK_LENGTHS = np.array([0.18, 0.2, 0.24, 0.3, 0.4, 0.5,
                         0.7, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0]) * 1e-6
NMOS_LENGTHS = GPDK_LENGTHS
PMOS_LENGTHS = GPDK_LENGTHS

# --- Номиналы питания (В) --------------------------------------------------
# Задают диапазон VGS/VDS: 0..|VDD|. VBS: 0..-|VDD| (NMOS) / 0..+|VDD| (PMOS).
# Пример GPDK180 (ядро): 1.8 В
NMOS_VDD = 1.8
PMOS_VDD = 1.8

# --- Развертки -------------------------------------------------------------
# Нижняя граница |VGS| (В): слишком близко к 0 — прибор в глубокой отсечке и
# gm/ID шумит (мелкий ID), поэтому развертку начинаем чуть ниже плато gm/ID.
NMOS_VGS_START = 0.2
PMOS_VGS_START = 0.2
# Шаги разверток (В): полный прогон и быстрый.
SWEEP = dict(vgs=0.025, vds=0.10, vbs=0.50)
QUICK_SWEEP = dict(vgs=0.10, vds=0.50, vbs=1.00)
QUICK_LENGTH_STRIDE = 2        # прореживание списка длин в быстром режиме

# --- Прочее ----------------------------------------------------------------
TEMPERATURE = 27.0             # °C
DEVICE_WIDTH = 40e-6           # фиксированная ширина эталонного транзистора, м
N_PROCESS = int(os.environ.get("GMID_NPROC", "4"))
SPECTRE_BIN = os.environ.get("SPECTRE_BIN", "spectre")
SCRIPT_DIR = Path(__file__).resolve().parent

# Имена экземпляра для нетлиста и для probe рабочих точек.
#   ("M1", "M1")     — модель задана как `model ...` (примитив);
#   ("X1", "X1.m1")  — модель задана как `subckt ...` (внутренний прибор m1).
# None -> автоопределение по файлу моделей (рекомендуется).
MOS_SYMBOLS: tuple[str, str] | None = None

# Дополнительные параметры прибора в нетлист (w добавляется всегда).
# Например: {"as": 1e-12, "ad": 1e-12, "ps": 1e-6, "pd": 1e-6}
EXTRA_DEVICE_PARAMETERS: dict = {}

# --- Отчёт (LaTeX -> PDF), включается флагом --report ----------------------
# Эталонная точка для таблиц «основных точек» в отчёте.
REPORT_GMID = 12.0             # целевое gm/ID, 1/В
REPORT_ID = 10e-6              # целевой ток стока ID, А

# ===========================================================================
#                          К О Н Е Ц   Н А С Т Р О Е К
# ===========================================================================


_DISABLED = {"", "-", "none", "no", "off"}


def _clean_model(name) -> str | None:
    """None / пусто / 'none' -> None (устройство выключено)."""
    if name is None:
        return None
    name = str(name).strip()
    return None if name.lower() in _DISABLED else name


def _model_list(value) -> list[str]:
    """Нормализовать список моделей: строка/None/список -> список имён."""
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    return [c for c in (_clean_model(v) for v in value) if c]


def _devices() -> list[dict]:
    """Список АКТИВНЫХ устройств: все NMOS и/или PMOS из списков моделей."""
    devices: list[dict] = []
    for name in _model_list(NMOS_MODELS):
        devices.append(dict(key=name, model=name, kind="nmos",
                            vdd=abs(NMOS_VDD), vgs_start=abs(NMOS_VGS_START),
                            lengths=np.asarray(NMOS_LENGTHS)))
    for name in _model_list(PMOS_MODELS):
        devices.append(dict(key=name, model=name, kind="pmos",
                            vdd=abs(PMOS_VDD), vgs_start=abs(PMOS_VGS_START),
                            lengths=np.asarray(PMOS_LENGTHS)))
    return devices


def _devices_for(lt: dict) -> list[dict]:
    """Устройства, реально присутствующие в LUT (независимо от текущего конфига).

    Ключи совпавшие с конфигом берутся из конфига (сохраняются заданные длины
    и Vdd); остальные выводятся из самой таблицы (тип по знаку VDS).
    """
    cfg = {d["key"]: d for d in _devices()}
    out: list[dict] = []
    for key, val in lt.items():
        if not isinstance(val, dict) or "length" not in val or "vgs" not in val:
            continue
        if key in cfg:
            out.append(cfg[key])
            continue
        vds = np.asarray(val["vds"], dtype=float)
        kind = "pmos" if vds[-1] < 0 else "nmos"
        out.append(dict(key=key, model=key, kind=kind,
                        vdd=float(np.max(np.abs(vds))),
                        vgs_start=float(np.min(np.abs(np.asarray(val["vgs"], dtype=float)))),
                        lengths=np.asarray(val["length"], dtype=float)))
    return out


def _out_dir(techname: str | None, models_file: str) -> Path:
    name = techname or Path(models_file).stem
    return SCRIPT_DIR / f"lut_{name}"


# ===========================================================================
# 1. АНАЛИЗ ФАЙЛА МОДЕЛЕЙ
# ===========================================================================

def _detect_sections(path: Path) -> list[str]:
    names: list[str] = []
    for line in path.read_text(errors="ignore").splitlines():
        m = re.match(r"\s*section\s+(\S+)", line)
        if m:
            names.append(m.group(1))
    return names


_INCLUDE_RE = re.compile(r'^\s*include\s+"([^"]+)"', re.IGNORECASE)


def _resolve_includes(path: Path, _seen: set | None = None) -> list[Path]:
    """Файл + все файлы, подключённые через `include "..."` (рекурсивно).

    Нужно, потому что модели часто разложены по файлам/папкам
    (корневой lib.scs -> include "type/nmos.scs", "fast/pmos.scs", ...).
    """
    if _seen is None:
        _seen = set()
    try:
        path = path.resolve()
    except OSError:
        return []
    if path in _seen or not path.is_file():
        return []
    _seen.add(path)
    files = [path]
    for line in path.read_text(errors="ignore").splitlines():
        m = _INCLUDE_RE.match(line)
        if m:
            files += _resolve_includes(path.parent / m.group(1), _seen)
    return files


def _model_texts(path: Path) -> list[tuple[Path, str]]:
    """(файл, текст) для данного файла и всех его include-файлов."""
    return [(f, f.read_text(errors="ignore")) for f in _resolve_includes(path)]


def _find_root_models(models_dir: Path) -> Path | None:
    """Найти корневой .scs в каталоге с моделями.

    Приоритет: файл-библиотека с секциями (обычно `models.scs`), затем файл
    с `include`, затем единственный .scs верхнего уровня.
    """
    if not models_dir.is_dir():
        return None
    cands = sorted(p for p in models_dir.glob("*.scs"))
    if not cands:
        return None
    with_sec = [p for p in cands if _detect_sections(p)]
    if with_sec:
        for p in with_sec:
            if p.stem.lower() in ("models", "model", "all"):
                return p
        return with_sec[0]
    with_inc = [p for p in cands if _INCLUDE_RE.search(p.read_text(errors="ignore"))]
    if with_inc:
        for p in with_inc:
            if p.stem.lower() in ("models", "model", "all"):
                return p
        return with_inc[0]
    return cands[0]


def _resolve_models_source(models_file: str, models_dir: str | None,
                           out_dir: Path) -> Path:
    """Определить итоговый .scs: из каталога (с поиском корня) или напрямую.

    Если в каталоге нет корневого файла, синтезируется сводный файл,
    включающий ВСЕ найденные .scs рекурсивно.
    """
    if not models_dir:
        return Path(models_file)
    mdir = Path(models_dir)
    root = _find_root_models(mdir)
    top = sorted(mdir.glob("*.scs"))
    if root is not None and (_detect_sections(root) or len(top) == 1):
        print(f"  корневой файл моделей: {root}")
        return root
    # Нет единого корня — собираем сводный include всех .scs.
    files = sorted(mdir.rglob("*.scs"))
    if not files:
        raise SystemExit(f"ОШИБКА: в каталоге {mdir} не найдено ни одного .scs")
    out_dir.mkdir(parents=True, exist_ok=True)
    merged = out_dir / ".models_merged.scs"
    merged.write_text("\n".join(f'include "{f}"' for f in files) + "\n")
    print(f"  сводный файл моделей ({len(files)} шт.): {merged}")
    return merged


def _check_models_present(path: Path, names: list[str]) -> None:
    """Предупредить, если в файле (или его include) нет заданных моделей."""
    texts = _model_texts(path)
    for name in names:
        pat = re.compile(rf"^\s*(model|subckt|inline\s+subckt)\s+{re.escape(name)}\b",
                         re.MULTILINE | re.IGNORECASE)
        if not any(pat.search(t) for _f, t in texts):
            print(f"  ! ВНИМАНИЕ: модель {name!r} не найдена в {path.name} "
                  "(и его include-файлах)", file=sys.stderr)


def _detect_symbols(path: Path, model: str) -> tuple[str, str]:
    """Определить (имя экземпляра, probe) по виду модели (с учётом include).

    * `model nmos ...`            -> ("M1", "M1")
    * `subckt mymos (d g s b)` с 4-выводным прибором `m1` внутри -> ("X1", "X1.m1")

    Для subckt-моделей (например, `mymos.scs`) рабочие точки внутреннего
    транзистора доступны только по иерархическому имени `X1.m1`.
    """
    pat = re.compile(rf"^\s*(model|inline\s+subckt)\s+{re.escape(model)}\b",
                     re.MULTILINE | re.IGNORECASE)
    for _f, txt in _model_texts(path):
        if pat.search(txt):
            return ("M1", "M1")
    return _scan_subckt_device(path, model) or ("M1", "M1")


def _scan_subckt_device(path: Path, model: str) -> tuple[str, str] | None:
    """Найти 4-выводный прибор внутри `subckt <model> ... ends`."""
    for _f, txt in _model_texts(path):
        inside = False
        for line in txt.splitlines():
            s = line.strip()
            m = re.match(r"subckt\s+(\S+)", s, re.IGNORECASE)
            if m:
                inside = (m.group(1) == model)
                continue
            if re.match(r"ends\b", s, re.IGNORECASE):
                if inside:
                    inside = False
                    break
                continue
            if not inside:
                continue
            m = re.match(r"([A-Za-z_]\w*)\s*\(([^)]*)\)\s*(\S+)", s)
            if m and len(m.group(2).split()) == 4:   # 4 вывода: d g s b
                return ("X1", f"X1.{m.group(1)}")
    return None


def _symbols_for(device: dict, models_file: Path, override) -> tuple[str, str]:
    """Символы экземпляра/probe для устройства: CLI -> конфиг -> автоопределение."""
    if override:
        return (str(override[0]), str(override[1]))
    if MOS_SYMBOLS:
        return (str(MOS_SYMBOLS[0]), str(MOS_SYMBOLS[1]))
    return _detect_symbols(models_file, device["model"])


# ===========================================================================
# 2. ГЕНЕРАЦИЯ LUT
# ===========================================================================

def _make_sweep(device: dict, quick: bool):
    from mosplot.lookup_table_generator import TransistorSweep

    step = QUICK_SWEEP if quick else SWEEP
    vdd = device["vdd"]
    vgs_start = device["vgs_start"]
    lengths = np.asarray(device["lengths"])
    if quick:
        lengths = lengths[::QUICK_LENGTH_STRIDE]

    if device["kind"] == "nmos":
        return TransistorSweep(
            mos_type="nmos",
            vgs=(vgs_start, vdd, step["vgs"]),
            vds=(step["vds"], vdd, step["vds"]),
            vbs=(0.0, -vdd, -step["vbs"]),
            length=lengths,
        )
    return TransistorSweep(
        mos_type="pmos",
        vgs=(-vgs_start, -vdd, -step["vgs"]),
        vds=(-step["vds"], -vdd, -step["vds"]),
        vbs=(0.0, vdd, step["vbs"]),
        length=lengths,
    )


class DeviceFailed(Exception):
    """Устройство не удалось снять (модель падает или subckt несовместим)."""


def _preflight(sim, device: dict, sweep) -> None:
    """Один пробный DC-прогон в главном процессе.

    Модели-`subckt` умеют падать на этапе разбора (например, формула `as(w)`
    даёт отрицательное значение при слишком узком W, или у `subckt` не то
    число выводов). В таком случае рабочие процессы молча погибают, а сборка
    LUT зависает на очереди — поэтому ловим ошибку заранее. При провале
    возбуждаем `DeviceFailed`, чтобы `build_tables` пропустил это устройство
    и продолжил с остальными.
    """
    from mosplot.lookup_table_generator.simulators.spice_simulators.mosfet_simulation import MosfetSimulation

    ms = MosfetSimulation(sim, {device["model"]: sweep}, 1)
    netlist = ms.get_single_netlist("dc")
    sim.make_temp_files()
    try:
        sim.run_simulation(netlist, verbose=False)
    except Exception as exc:  # noqa: BLE001
        raise DeviceFailed(
            f"{exc}\n    (экземпляр/probe: {sim.mos_spice_symbols}, "
            f"W={DEVICE_WIDTH * 1e6:g} um; проверьте число выводов subckt "
            f"и допустимую ширину)") from exc
    finally:
        sim.remove_temp_files()


def build_tables(corners, quick: bool, do_op: bool, args) -> list[Path]:
    from mosplot.lookup_table_generator import LookupTableGenerator
    from mosplot.lookup_table_generator.simulators import SpectreSimulator
    from mosplot.plot import load_lookup_table

    models_file = Path(args.models_file).resolve()
    out_dir = _out_dir(args.techname, str(models_file))
    out_dir.mkdir(parents=True, exist_ok=True)

    devices = _devices()
    if not devices:
        raise SystemExit(
            "ОШИБКА: не задано ни одной модели "
            "(NMOS_MODEL и PMOS_MODEL = None).")
    _check_models_present(models_file, [d["model"] for d in devices])

    dev_params = {"w": DEVICE_WIDTH, **EXTRA_DEVICE_PARAMETERS}
    corner_list = corners if corners else [None]
    produced: list[Path] = []

    for corner in corner_list:
        tag = f"_{corner}" if corner else ""
        print("=" * 72)
        print(f"Модели: {models_file}")
        print(f"Угол:   {corner or '(нет, плоский файл)'}   "
              f"T={TEMPERATURE} C   W={DEVICE_WIDTH * 1e6:g} um")
        print("Устройства: " + ", ".join(
            f"{d['model']} [{_symbols_for(d, models_file, args.symbols)[1]}]"
            for d in devices))
        print("=" * 72)

        merged: dict = {}
        last_meta: dict = {}
        skipped: list[str] = []
        t0 = time.time()
        for device in devices:
            symbols = _symbols_for(device, models_file, args.symbols)
            sim_kwargs = dict(
                simulator_path=SPECTRE_BIN,
                temperature=TEMPERATURE,
                device_parameters=dev_params,
                mos_spice_symbols=symbols,
            )
            if corner:
                sim_kwargs["lib_mappings"] = [(str(models_file), corner)]
            else:
                sim_kwargs["include_paths"] = [str(models_file)]
            sim = SpectreSimulator(**sim_kwargs)

            sweep = _make_sweep(device, quick)
            try:
                _preflight(sim, device, sweep)
            except DeviceFailed as exc:
                print(f"  ! [{device['model']}] ПРОПУЩЕНО: {exc}",
                      file=sys.stderr)
                skipped.append(device["model"])
                continue

            gen = LookupTableGenerator(
                description=f"{models_file.name}{tag} {TEMPERATURE}C gmid lookup table",
                simulator=sim,
                model_sweeps={device["model"]: sweep},
                n_process=N_PROCESS,
            )

            if do_op:
                print(f"Пробная operating-point симуляция ({device['model']}):")
                gen.op_simulation()

            tmp_base = out_dir / f".tmp_{device['key']}{tag}"
            gen.build(str(tmp_base))
            sub = load_lookup_table(str(tmp_base) + ".npz")
            merged[device["key"]] = sub[device["key"]]
            last_meta = {k: sub[k] for k in
                         ("description", "simulator", "parameter_names",
                          "device_parameters")}
            try:
                os.remove(str(tmp_base) + ".npz")
            except OSError:
                pass

        if not merged:
            raise SystemExit(
                "ОШИБКА: ни одно устройство не удалось снять"
                + (f" (пропущены: {', '.join(skipped)})" if skipped else "")
                + ". См. сообщения выше.")
        if skipped:
            print(f"  пропущены устройства: {', '.join(skipped)}",
                  file=sys.stderr)

        # Общие метаданные: объединяем найденные параметры всех устройств.
        param_union = sorted({p for key in merged
                              for p in merged[key].get("parameter_names", [])})
        merged["description"] = last_meta.get("description", "")
        merged["simulator"] = last_meta.get("simulator", "SpectreSimulator")
        merged["parameter_names"] = param_union
        merged["device_parameters"] = last_meta.get("device_parameters", dev_params)

        out_base = out_dir / f"{out_dir.name}{tag}"
        np.savez_compressed(str(out_base) + ".npz",
                            lookup_table=np.array(merged, dtype=object))
        npz_path = out_base.with_suffix(".npz")
        print(f"  -> {npz_path}  ({time.time() - t0:.0f} s)")
        produced.append(npz_path)

    return produced


# ===========================================================================
# 3. ГРАФИКИ
# ===========================================================================

def _pick_lengths(available, count: int = 7) -> list:
    available = np.asarray(available)
    if len(available) <= count:
        return list(available)
    idx = np.unique(np.linspace(0, len(available) - 1, count).round().astype(int))
    return [available[i] for i in idx]


def _fmt_eng(value: float, unit: str = "") -> str:
    value = float(value)
    for scale, prefix in ((1.0, ""), (1e-3, "m"), (1e-6, "µ"), (1e-9, "n"), (1e-12, "p")):
        if abs(value) >= scale:
            return f"{value / scale:.3g} {prefix}{unit}"
    return f"{value:.3g} {unit}"


def plot_device(lookup_table: dict, device: dict, plot_dir: Path) -> None:
    from mosplot.plot import Mosfet

    key = device["key"]
    kind = device["kind"]
    vdd = device["vdd"]
    sign = 1.0 if kind == "nmos" else -1.0
    vds_bias = sign * 0.5 * vdd
    vgs_range = (sign * device["vgs_start"], sign * (vdd - 0.01))

    params = set(lookup_table.get("parameter_names", []))
    has_cgg = "cgg" in params

    def safe(desc, fn):
        """Выполнить построение, не падая при отсутствии параметра в модели."""
        try:
            fn()
            print(f"    ok   {desc}")
        except (KeyError, ValueError) as exc:
            print(f"    ПРОПУСК {desc}: {exc}")

    mos = Mosfet(lookup_table=lookup_table, mos=key, vbs=0.0,
                 vds=vds_bias, vgs=vgs_range)
    lengths = _pick_lengths(mos.length)
    print(f"  [{key}] длины: " + ", ".join(f"{l * 1e6:g}µm" for l in lengths))

    safe("ID/W vs gm/ID", lambda: mos.plot_by_expression(
        x_expression=mos.gmid_expression,
        y_expression=mos.current_density_expression,
        filtered_values=lengths,
        y_scale="log",
        y_eng_format=True, legend_eng_format=True, legend_placement="top",
        fig_size=(8, 4.5),
        save_fig=str(plot_dir / f"idw_vs_gmid_{key}.svg")))

    if has_cgg:
        safe("fT vs gm/ID", lambda: mos.plot_by_expression(
            x_expression=mos.gmid_expression,
            y_expression=mos.transit_frequency_expression,
            filtered_values=lengths,
            y_scale="log",
            y_eng_format=True, legend_eng_format=True, legend_placement="top",
            fig_size=(8, 4.5),
            save_fig=str(plot_dir / f"ft_vs_gmid_{key}.svg")))
    else:
        print("    (Cgg в модели не задан — fT недоступна)")

    safe("gm*ro vs gm/ID", lambda: mos.plot_by_expression(
        x_expression=mos.gmid_expression,
        y_expression=mos.gain_expression,
        filtered_values=lengths,
        y_scale="log",
        y_eng_format=True, legend_eng_format=True, legend_placement="top",
        fig_size=(8, 4.5),
        save_fig=str(plot_dir / f"gmro_vs_gmid_{key}.svg")))

    def _gmid_vov():
        """gm/ID в зависимости от Vov = |VGS| - |Vth| (по длинам)."""
        vgs_axis = np.asarray(mos.lookup_table["vgs"])
        vgs_pts = (vgs_axis[1], vgs_axis[-1], vgs_axis[1] - vgs_axis[0])
        vgs, vth, gmid = mos.lookup_expression_from_table(
            length=lengths, vbs=0.0, vds=vds_bias, vgs=vgs_pts, primary="vgs",
            expression=[mos.vgs_expression, mos.vth_expression,
                        mos.gmid_expression])
        vov = np.abs(vgs) - np.abs(vth)
        gmid = np.abs(gmid)
        if vov.ndim == 1:
            vov, gmid = vov[None, :], gmid[None, :]
        mos.quick_plot(
            x=[vov[i] for i in range(len(lengths))],
            y=[gmid[i] for i in range(len(lengths))],
            legend=[f"{l * 1e6:g}µm" for l in lengths], legend_title="Length",
            x_label=r"$V_{OV}=|V_{GS}|-|V_{th}|$ (V)",
            y_label=r"$g_m/I_D$ (1/V)",
            fig_size=(7, 4.5), legend_placement="top",
            save_fig=str(plot_dir / f"gmid_vs_vov_{key}.svg"))

    safe("gm/ID vs Vov", _gmid_vov)

    safe("ID vs VGS", lambda: mos.plot_by_sweep(
        length=lengths, vbs=0.0, vds=vds_bias, vgs=vgs_range, primary="vgs",
        x_expression=(mos.vgs_expression if kind == "nmos" else mos.vsg_expression),
        y_expression=mos.id_expression,
        y_scale="log", y_eng_format=True, legend_eng_format=True,
        legend_placement="top", fig_size=(7, 4.5),
        save_fig=str(plot_dir / f"id_vs_vgs_{key}.svg")))

    l_iv = float(min(lengths, key=lambda l: abs(l - 0.4 * vdd)))
    vgs_steps = (sign * 0.5 * vdd, sign * vdd, sign * 0.125 * vdd)
    safe("ID vs VDS", lambda: mos.plot_by_sweep(
        length=l_iv, vbs=0.0, vgs=vgs_steps, vds=(sign * 0.01, sign * vdd),
        primary="vds",
        x_expression=(mos.vds_expression if kind == "nmos" else mos.vsd_expression),
        y_expression=mos.id_expression,
        y_eng_format=True, legend_eng_format=True, legend_placement="top",
        fig_size=(7, 4.5),
        save_fig=str(plot_dir / f"id_vs_vds_{key}.svg")))

    def _voltage_plot():
        vgs_axis = np.asarray(mos.lookup_table["vgs"])
        vgs_pts = (vgs_axis[1], vgs_axis[-1], vgs_axis[1] - vgs_axis[0])
        vgs, vdsat, vov, vstar = mos.lookup_expression_from_table(
            length=lengths[len(lengths) // 2], vbs=0.0, vds=vds_bias,
            vgs=vgs_pts, primary="vgs",
            expression=[mos.vgs_expression, mos.vdsat_expression,
                        mos.vov_expression, mos.vstar_expression],
        )
        x = np.abs(vgs)
        mos.quick_plot(
            x=[x, x, x],
            y=[np.abs(vdsat), np.abs(vov), np.abs(vstar)],
            legend=["$V_{DS,sat}$", "$V_{OV}$", "$V^{*}$"],
            x_label="$|V_{GS}|$ (V)", y_label="Voltage (V)",
            y_limit=(0, 1.1 * vdd), legend_placement="top", fig_size=(7, 4.5),
            save_fig=str(plot_dir / f"vdsat_vov_vstar_vs_vgs_{key}.svg"))

    safe("Vdsat/Vov/V* vs VGS", _voltage_plot)


def make_plots(npz_path: Path) -> None:
    from mosplot.plot import load_lookup_table

    plot_dir = npz_path.parent / f"plots_{npz_path.stem}"
    plot_dir.mkdir(parents=True, exist_ok=True)
    print("=" * 72)
    print(f"Графики для {npz_path.name}: -> {plot_dir}")
    print("=" * 72)
    lt = load_lookup_table(str(npz_path))
    for device in _devices_for(lt):
        plot_device(lt, device, plot_dir)


# ===========================================================================
# 4. ПРИМЕР РАСЧЁТА (gm/ID sizing)
# ===========================================================================

def sizing_example(npz_path: Path, mos_name: str,
                   length: float, gmid_target: float = 12.0,
                   id_target: float = 10e-6, vds: float | None = None) -> None:
    from mosplot.plot import load_lookup_table, Mosfet

    lt = load_lookup_table(str(npz_path))
    device = next((d for d in _devices_for(lt) if d["key"] == mos_name), None)
    if device is None:
        raise ValueError(f"Неизвестное устройство {mos_name!r}")

    sign = 1.0 if device["kind"] == "nmos" else -1.0
    vds = 0.5 * device["vdd"] if vds is None else vds

    axis = np.asarray(lt[mos_name]["vgs"])
    step = axis[1] - axis[0]
    length_used = float(min(lt[mos_name]["length"], key=lambda x: abs(x - length)))

    params = set(lt.get("parameter_names", []))
    has_cgg = "cgg" in params

    mos = Mosfet(lookup_table=lt, mos=mos_name, vbs=0.0, vds=sign * vds,
                 vgs=(axis[0], axis[-1], step))
    want = {
        "vgs": mos.vgs_expression,
        "id": mos.id_expression,
        "gm": mos.gm_expression,
        "gds": mos.gds_expression,
        "gmid": mos.gmid_expression,
        "idw": mos.current_density_expression,
        "vdsat": mos.vdsat_expression,
        "vstar": mos.vstar_expression,
    }
    if has_cgg:
        want["ft"] = mos.transit_frequency_expression
        want["cgg"] = mos.cgg_expression
    names = list(want)
    res = mos.lookup_expression_from_table(
        length=length_used, vbs=0.0, vds=sign * vds,
        vgs=(axis[0], axis[-1], step), primary="vgs",
        expression=[want[n] for n in names])
    data = {n: np.asarray(res[i]) for i, n in enumerate(names)}

    vg = np.abs(data["vgs"])
    order = np.argsort(vg)
    curves = {n: np.abs(data[n])[order] for n in data if n != "vgs"}
    vg = vg[order]

    peak = int(np.argmax(curves["gmid"]))
    xs = vg[peak:]
    ys = curves["gmid"][peak:]
    curves = {n: c[peak:] for n, c in curves.items()}

    if not (ys[-1] <= gmid_target <= ys[0]):
        print(f"  ! gm/ID={gmid_target:g} вне диапазона [{ys[-1]:.1f}, {ys[0]:.1f}] "
              f"для {mos_name} L={_fmt_eng(length_used, 'm')}; берётся ближайшая точка.")
    idx = min(max(int(np.searchsorted(-ys, -gmid_target)), 1), len(ys) - 1)
    t = (gmid_target - ys[idx - 1]) / (ys[idx] - ys[idx - 1])
    val = {n: c[idx - 1] + t * (c[idx] - c[idx - 1]) for n, c in curves.items()}
    vgs_i = xs[idx - 1] + t * (xs[idx] - xs[idx - 1])

    id_w_i = val["idw"]
    width = abs(id_target / id_w_i)
    gain = val["gm"] / val["gds"]
    print("-" * 72)
    print(f"РАСЧЁТ ПО ТАБЛИЦЕ  ({npz_path.name})")
    print(f"  устройство : {mos_name}   L = {_fmt_eng(length_used, 'm')}")
    print(f"  цель       : gm/ID = {val['gmid']:.2f} 1/V,  ID = {_fmt_eng(id_target, 'A')}")
    print(f"  VDS        : {abs(vds):g} В")
    print("-" * 72)
    print(f"  ID/W       : {_fmt_eng(id_w_i, 'A/m')}")
    print(f"  W          : {_fmt_eng(width, 'm')}")
    print(f"  gm         : {_fmt_eng(val['gm'], 'S')}")
    print(f"  gm/gds     : {gain:,.1f}  ({20 * np.log10(gain):.1f} dB)")
    if has_cgg:
        print(f"  fT         : {_fmt_eng(val['ft'], 'Hz')}")
        print(f"  Cgg        : {_fmt_eng(val['cgg'], 'F')}")
    else:
        print("  fT / Cgg   : н/д (в модели нет данных о ёмкостях)")
    print(f"  VGS        : {abs(vgs_i):.3f} В")
    print(f"  Vdsat      : {val['vdsat']:.3f} В")
    print(f"  V* (=2ID/gm): {val['vstar']:.3f} В")
    print("-" * 72)


# ===========================================================================
# 5. ОТЧЁТ (LaTeX -> PDF)
# ===========================================================================
# Опциональная сборка PDF-отчёта со всеми картинками, расшифровкой параметров
# LUT, таблицами настроек и «основными точками» (по длинам и по целевому
# gm/ID). Нужен движок LaTeX (xelatex / lualatex / pdflatex) и rsvg-convert
# (или inkscape) для перевода SVG -> PDF. Если движка нет — скрипт всё равно
# сохранит report.tex и рисунки; скомпилировать можно вручную: xelatex report.tex

_SI_RU = ((1e9, "Г"), (1e6, "М"), (1e3, "к"), (1.0, ""),
          (1e-3, "м"), (1e-6, "мк"), (1e-9, "н"), (1e-12, "п"), (1e-15, "ф"))

_REPORT_FIGURES = (
    ("idw_vs_gmid", r"Удельный ток $I_D/W$ от $g_m/I_D$"),
    ("ft_vs_gmid", r"Граничная частота $f_T$ от $g_m/I_D$"),
    ("gmro_vs_gmid", r"Собственное усиление $g_m\!\cdot\!r_o = g_m/g_{ds}$ от $g_m/I_D$"),
    ("gmid_vs_vov", r"$g_m/I_D$ от напряжения перевозбуждения $V_{OV}=|V_{GS}|-|V_{th}|$"),
    ("id_vs_vgs", r"Ток стока $I_D$ от $V_{GS}$ (разные длины)"),
    ("id_vs_vds", r"Ток стока $I_D$ от $V_{DS}$ (выходные характеристики)"),
    ("vdsat_vov_vstar_vs_vgs", r"$V_{DS,sat}$, $V_{OV}$, $V^{*}$ от $V_{GS}$"),
    # старые имена (совместимость с ранее собранными LUT):
    ("ft_gain_vs_gmid", r"$f_T$ и собственное усиление от $g_m/I_D$"),
    ("gain_vs_gmid", r"Собственное усиление $g_m/g_{ds}$ от $g_m/I_D$"),
)

# key, обозначение, смысл, единица
_PARAM_LEGEND = (
    ("id", r"$I_D$", "ток стока", "А"),
    ("vth", r"$V_{th}$", "пороговое напряжение", "В"),
    ("vdsat", r"$V_{DS,sat}$", "напряжение насыщения", "В"),
    ("gm", r"$g_m$", r"крутизна $\partial I_D/\partial V_{GS}$", "См"),
    ("gmbs", r"$g_{mb}$", r"крутизна по подложке $\partial I_D/\partial V_{BS}$", "См"),
    ("gds", r"$g_{ds}$", r"выходная проводимость $\partial I_D/\partial V_{DS}$", "См"),
    ("cgg", r"$C_{gg}$", "полная ёмкость затвора", "Ф"),
    ("cgs", r"$C_{gs}$", "ёмкость затвор-исток", "Ф"),
    ("cgd", r"$C_{gd}$", "ёмкость затвор-сток", "Ф"),
    ("cgb", r"$C_{gb}$", "ёмкость затвор-подложка", "Ф"),
    ("cdd", r"$C_{dd}$", "ёмкость стока", "Ф"),
)

# обозначение, смысл, единица, как считается
_DERIVED_LEGEND = (
    (r"$g_m/I_D$", "эффективность крутизны (КПД)", "1/В", "основная координата sizing"),
    (r"$I_D/W$", "удельный ток", "А/м", "ток на единицу ширины"),
    (r"$f_T$", "граничная частота", "Гц", r"$g_m/(2\pi C_{gg})$"),
    (r"$g_m/g_{ds}$", "собственное усиление", "дБ", r"$20\,\lg(g_m/g_{ds})$"),
    (r"$V^{*}$", r"напряжение $2I_D/g_m$", "В", r"$2/(g_m/I_D)$"),
    (r"$V_{OV}$", "перевозбуждение", "В", r"$V_{GS}-V_{th}$"),
)

_INTRO_TEXT = (
    r"Таблицы $g_m/I_D$ — практический инструмент выбора размеров транзистора. "
    r"Вместо прямого расчёта ширины по формуле рабочую точку задают требуемым "
    r"$g_m/I_D$: этот параметр определяет режим (слабая, умеренная или сильная "
    r"инверсия), а длина канала $L$ — компромисс между усилением, быстродействием "
    r"и запасом по напряжению. Ток стока $I_D$ задаёт масштаб, а ширина находится "
    r"как $W = I_D / (I_D/W)$." + "\n\n" +
    r"Порядок работы: (1) выбрать длину $L$; (2) на кривой $g_m/I_D$ выбрать точку "
    r"компромисса (обычно в области перегиба); (3) снять оттуда $I_D/W$, $V_{GS}$, "
    r"$V_{DS,sat}$, $f_T$ и $g_m/g_{ds}$; (4) вычислить $W$ под требуемый ток. "
    r"Ниже приведены графики и таблицы основных точек для каждого прибора."
)


def _fmt_ru(value: float, unit: str = "") -> str:
    """Число с русской приставкой СИ и единицей: 8.39 мкА, 1.19 мм, 3.33 МГц."""
    v = abs(float(value))
    for scale, prefix in _SI_RU:
        if v >= scale:
            return f"{float(value) / scale:.4g} {prefix}{unit}".strip()
    return f"{float(value):.3g} {unit}".strip()


def _tex_escape(text) -> str:
    """Экранировать спецсимволы LaTeX в обычном тексте."""
    repl = {
        "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
        "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    }
    return "".join(repl.get(c, c) for c in str(text))


def _tex_tabular(headers: list[str], rows: list[list], colspec: str | None = None) -> str:
    """Только окружение tabular (без плавающего table/caption)."""
    spec = colspec or ("l" + "r" * (len(headers) - 1))
    lines = [rf"\begin{{tabular}}{{{spec}}}", r"\toprule",
             " & ".join(str(h) for h in headers) + r" \\", r"\midrule"]
    lines += [" & ".join(str(c) for c in row) + r" \\" for row in rows]
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines)


def _tex_table(headers: list[str], rows: list[list], caption: str, label: str,
               colspec: str | None = None) -> str:
    """Плавающая таблица с подписью и меткой."""
    body = _tex_tabular(headers, rows, colspec)
    return "\n".join([
        r"\begin{table}[htbp]", r"\centering",
        r"\caption{" + caption + r"}", r"\label{" + label + r"}",
        body, r"\end{table}",
    ])


def _tex_preamble(engine: str) -> str:
    common = "\n".join([
        r"\usepackage{geometry}",
        r"\usepackage{graphicx}",
        r"\usepackage{booktabs}",
        r"\usepackage{amsmath}",
        r"\usepackage{xcolor}",
        r"\usepackage{caption}",
        r"\usepackage{hyperref}",
        r"\hypersetup{colorlinks=true,linkcolor=blue!50!black,urlcolor=blue!50!black}",
        r"\graphicspath{{figs/}}",
        r"\setlength{\parindent}{0pt}",
    ])
    if engine in ("xelatex", "lualatex", "tectonic"):
        head = "\n".join([
            r"\documentclass[11pt]{article}",
            r"\usepackage{fontspec}",
            r"\setmainfont{DejaVu Serif}",
            r"\setsansfont{DejaVu Sans}",
            r"\setmonofont{DejaVu Sans Mono}",
        ])
    else:
        head = "\n".join([
            r"\documentclass[11pt]{article}",
            r"\usepackage[T2A]{fontenc}",
            r"\usepackage[utf8]{inputenc}",
            r"\usepackage[russian,english]{babel}",
            r"\usepackage{lmodern}",
        ])
    return head + "\n" + common + "\n"


def _find_tex_engine() -> tuple[str | None, str | None]:
    """Найти движок LaTeX: PATH, локальный .texlive, /usr/local/texlive."""
    order = ("xelatex", "lualatex", "pdflatex", "tectonic")
    for name in order:
        found = shutil.which(name)
        if found:
            return name, found
    roots = [SCRIPT_DIR / ".texlive" / "bin" / "x86_64-linux"]
    tl = Path("/usr/local/texlive")
    if tl.exists():
        roots += sorted(tl.glob("*/bin/*"))
    for root in roots:
        if not root.is_dir():
            continue
        for name in order:
            exe = root / name
            if exe.exists():
                return name, str(exe)
    return None, None


def _svg_to_pdf(svg: Path, pdf: Path) -> bool:
    """SVG -> PDF через rsvg-convert (или inkscape). True, если получилось."""
    exe = shutil.which("rsvg-convert")
    try:
        if exe:
            r = subprocess.run([exe, "-f", "pdf", "-o", str(pdf), str(svg)],
                               capture_output=True, text=True, timeout=120)
        elif shutil.which("inkscape"):
            ink = shutil.which("inkscape")
            r = subprocess.run([ink, "--export-type=pdf",
                                f"--export-filename={pdf}", str(svg)],
                               capture_output=True, text=True, timeout=120)
        else:
            return False
    except Exception:
        return False
    return r.returncode == 0 and pdf.exists() and pdf.stat().st_size > 0


def _report_curves(lt: dict, device: dict, length: float,
                   vds_frac: float = 0.5) -> dict | None:
    """Кривые по VGS для одной длины: монотонная ветвь от максимума gm/ID."""
    from mosplot.plot import Mosfet

    key = device["key"]
    if key not in lt:
        return None
    sign = 1.0 if device["kind"] == "nmos" else -1.0
    vds = sign * device["vdd"] * vds_frac
    has_cgg = "cgg" in set(lt.get("parameter_names", []))

    axis = np.asarray(lt[key]["vgs"], dtype=float)
    step = axis[1] - axis[0]
    mos = Mosfet(lookup_table=lt, mos=key, vbs=0.0, vds=vds,
                 vgs=(axis[0], axis[-1], step))
    want = {
        "vgs": mos.vgs_expression,
        "vth": mos.vth_expression,
        "gmid": mos.gmid_expression,
        "idw": mos.current_density_expression,
        "id": mos.id_expression,
        "gm": mos.gm_expression,
        "gds": mos.gds_expression,
        "vdsat": mos.vdsat_expression,
        "vstar": mos.vstar_expression,
    }
    if has_cgg:
        want["ft"] = mos.transit_frequency_expression
        want["cgg"] = mos.cgg_expression
    names = list(want)
    res = mos.lookup_expression_from_table(
        length=length, vbs=0.0, vds=vds, vgs=(axis[0], axis[-1], step),
        primary="vgs", expression=[want[n] for n in names])
    data = {n: np.abs(np.asarray(res[i])) for i, n in enumerate(names)}

    vg = data.pop("vgs")
    order = np.argsort(vg)
    vg = vg[order]
    data = {n: a[order] for n, a in data.items()}

    peak = int(np.argmax(data["gmid"]))
    out = {"vgs": vg[peak:]}
    out.update({n: a[peak:] for n, a in data.items()})
    return out


def _report_at(curves: dict, gmid: float) -> dict | None:
    """Интерполяция величин по монотонной ветви на заданном gm/ID."""
    ys = curves["gmid"]
    if ys.size < 2 or not (ys[-1] - 1e-9 <= gmid <= ys[0] + 1e-9):
        return None
    idx = min(max(int(np.searchsorted(-ys, -gmid)), 1), len(ys) - 1)
    dy = ys[idx] - ys[idx - 1]
    t = (gmid - ys[idx - 1]) / dy if dy else 0.0
    return {n: c[idx - 1] + t * (c[idx] - c[idx - 1])
            for n, c in curves.items() if n != "gmid"}


def _settings_table(lt: dict, devices: list[dict]) -> str:
    def axis(vals) -> str:
        if vals is None:
            return "н/д"
        v = np.asarray(vals, dtype=float)
        if v.size == 0:
            return "н/д"
        step = abs(v[1] - v[0]) if v.size > 1 else 0.0
        return (f"{_fmt_ru(abs(v).min(), 'В')} ... {_fmt_ru(abs(v).max(), 'В')}, "
                f"шаг {_fmt_ru(step, 'В')}")

    ref = lt[devices[0]["key"]] if devices else {}
    rows = [
        ["Файл моделей", r"\texttt{" + _tex_escape(str(MODELS_FILE)) + "}"],
        [r"Развёртка $V_{GS}$", axis(ref.get("vgs"))],
        [r"Развёртка $V_{DS}$", axis(ref.get("vds"))],
        [r"Развёртка $V_{BS}$", axis(ref.get("vbs"))],
        ["Смещение для таблиц", r"$V_{DS}=0.5\,V_{DD}$, $V_{BS}=0$"],
        ["Число процессов", str(N_PROCESS)],
    ]
    for device in devices:
        key = _tex_escape(device["key"])
        lens = ", ".join(_fmt_ru(l, "м") for l in np.asarray(lt[device["key"]]["length"]))
        rows.append([f"Длины, {key}", lens])
        rows.append([f"$V_{{DD}}$, {key}", f"{device['vdd']:g} В"])
    return _tex_table(["Параметр", "Значение"], rows,
                      "Настройки расчёта", "tab:settings")


def _report_device_section(lt: dict, device: dict, figs_dir: Path,
                           gmid_ref: float, id_ref: float) -> str:
    key = device["key"]
    kind = "NMOS" if device["kind"] == "nmos" else "PMOS"
    lengths = np.asarray(lt[key]["length"], dtype=float)

    parts: list[str] = [
        r"\section{Устройство \texttt{" + _tex_escape(key) + "} (" + kind + ")}",
        r"Смещение: $V_{DS}=0.5\,V_{DD}$, $V_{BS}=0$; напряжения по модулю.",
    ]

    # --- графики ----------------------------------------------------------
    fig_blocks = []
    for spec, caption in _REPORT_FIGURES:
        pdf = figs_dir / f"{spec}_{key}.pdf"
        if not pdf.exists():
            continue
        fig_blocks.append("\n".join([
            r"\begin{figure}[htbp]", r"\centering",
            r"\includegraphics[width=0.92\linewidth]{" + pdf.name + "}",
            r"\caption{" + caption + r"}",
            r"\end{figure}",
        ]))
    if fig_blocks:
        parts.append(r"\subsection{Графики}")
        parts.extend(fig_blocks)

    # --- таблицы основных точек ------------------------------------------
    parts.append(r"\subsection{Основные точки}")
    rows_a, rows_b, curves_by_l = [], [], {}
    for length in lengths:
        curves = _report_curves(lt, device, float(length))
        if curves is None or curves["gmid"].size == 0:
            continue
        curves_by_l[float(length)] = curves
        gmax = float(curves["gmid"][0])
        val = _report_at(curves, gmid_ref)
        if val is None:
            rows_a.append([_fmt_ru(length, "м"), f"{gmax:.3g}", "---", "---", "---"])
            rows_b.append([_fmt_ru(length, "м"), "---", "---", "---", "---", "---"])
            continue
        idw = val["idw"]
        width = id_ref / idw if idw else float("nan")
        gain_db = 20 * np.log10(val["gm"] / val["gds"]) if val["gds"] else float("nan")
        ft = _fmt_ru(val["ft"], "Гц") if "ft" in val else "н/д"
        rows_a.append([_fmt_ru(length, "м"), f"{gmax:.3g}", f"{val['vgs']:.3f}",
                       _fmt_ru(idw, "А/м"), _fmt_ru(width, "м")])
        rows_b.append([_fmt_ru(length, "м"), f"{val['vth']:.3f}", f"{val['vdsat']:.3f}",
                       f"{val['vstar']:.3f}", f"{gain_db:.1f}", ft])

    parts.append(f"Целевая точка: $g_m/I_D = {gmid_ref:g}$ 1/В, "
                 f"$I_D =$ {_fmt_ru(id_ref, 'А')}.")
    parts.append(_tex_table(
        [r"$L$", r"$(g_m/I_D)_{max}$", r"$V_{GS}$", r"$I_D/W$", r"$W$"],
        rows_a, f"Размеры и ток при $g_m/I_D={gmid_ref:g}$ 1/В",
        f"tab:sizing_{key}"))
    parts.append(_tex_table(
        [r"$L$", r"$V_{th}$", r"$V_{DS,sat}$", r"$V^{*}$", r"$g_m/g_{ds}$, дБ", r"$f_T$"],
        rows_b, f"Напряжения, усиление и частота при $g_m/I_D={gmid_ref:g}$ 1/В",
        f"tab:volt_{key}"))

    # --- рабочая кривая при медианной длине -------------------------------
    if curves_by_l:
        l_med = min(curves_by_l, key=lambda l: abs(l - np.median(lengths)))
        curves = curves_by_l[l_med]
        gmax, gmin = float(curves["gmid"][0]), float(curves["gmid"][-1])
        rows_c = []
        for target in (3, 5, 7, 10, 12, 15, 20, 25, 30):
            if not (gmin <= target <= gmax):
                continue
            val = _report_at(curves, float(target))
            if val is None:
                continue
            idw = val["idw"]
            width = id_ref / idw if idw else float("nan")
            gain_db = 20 * np.log10(val["gm"] / val["gds"]) if val["gds"] else float("nan")
            ft = _fmt_ru(val["ft"], "Гц") if "ft" in val else "н/д"
            rows_c.append([f"{target:g}", f"{val['vgs']:.3f}", _fmt_ru(idw, "А/м"),
                           _fmt_ru(width, "м"), f"{gain_db:.1f}", ft])
        if rows_c:
            parts.append(f"Рабочие точки при $L =$ {_fmt_ru(l_med, 'м')} "
                         f"($W$ дана под ток $I_D =$ {_fmt_ru(id_ref, 'А')}):")
            parts.append(_tex_table(
                [r"$g_m/I_D$, 1/В", r"$V_{GS}$", r"$I_D/W$", r"$W$",
                 r"$g_m/g_{ds}$, дБ", r"$f_T$"],
                rows_c, f"Рабочие точки (устройство {_tex_escape(key)}, "
                        f"L={_fmt_ru(l_med, 'м')})",
                f"tab:points_{key}"))
    return "\n\n".join(parts)


def _report_body(lt: dict, devices: list[dict], npz_path: Path, figs_dir: Path,
                 gmid_ref: float, id_ref: float, engine: str) -> str:
    date = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    tech = npz_path.stem
    params = set(lt.get("parameter_names", []))

    doc: list[str] = [_tex_preamble(engine), r"\begin{document}"]
    doc.append("\n".join([
        r"\begin{titlepage}", r"\centering",
        r"{\LARGE\bfseries gm/ID LUT\par}", r"\vspace{0.4em}",
        r"{\large Отчёт: таблицы крутизны и основные точки\par}",
        r"\vspace{0.3em}", r"{\large " + _tex_escape(str(tech)) + r"\par}",
        r"\vspace{2em}",
        _tex_tabular(["Параметр", "Значение"], [
            ["Файл таблицы", r"\texttt{" + _tex_escape(npz_path.name) + "}"],
            ["Файл моделей", r"\texttt{" + _tex_escape(str(MODELS_FILE)) + "}"],
            ["Устройства", ", ".join(r"\texttt{" + _tex_escape(d["key"]) + "}"
                                     for d in devices)],
            ["Температура", r"$" + f"{TEMPERATURE:g}" + r"^\circ$C"],
            [r"Эталонная ширина $W$", _fmt_ru(DEVICE_WIDTH, "м")],
            [r"Эталон $g_m/I_D$", f"{gmid_ref:g} 1/В"],
            [r"Эталон $I_D$", _fmt_ru(id_ref, "А")],
            ["Дата сборки", date],
        ]),
        r"\vfill", r"{\small Документ сгенерирован автоматически: gmid\_lut.py}",
        r"\end{titlepage}",
    ]))
    doc.append(r"\tableofcontents")
    doc.append(r"\newpage")

    doc.append(r"\section{Методика gm/ID}")
    doc.append(_INTRO_TEXT)

    doc.append(r"\section{Расшифровка параметров}")
    doc.append(_tex_table(
        ["Обозначение", "Величина", "Единица", "Есть в LUT"],
        [[sym, desc, unit, ("да" if k in params else "нет")]
         for k, sym, desc, unit in _PARAM_LEGEND],
        "Сохраняемые параметры LUT", "tab:params"))
    doc.append(r"Производные (рассчитываемые) величины:")
    doc.append(_tex_table(
        ["Обозначение", "Величина", "Единица", "Как считается"],
        [[sym, desc, unit, formula] for sym, desc, unit, formula in _DERIVED_LEGEND],
        "Производные величины", "tab:derived"))

    doc.append(r"\section{Настройки развёрток}")
    doc.append(_settings_table(lt, devices))

    for device in devices:
        doc.append(_report_device_section(lt, device, figs_dir, gmid_ref, id_ref))

    doc.append(r"\end{document}")
    return "\n\n".join(doc)


def _run_tex(engine: str, exe: str, tex: Path, out_dir: Path) -> tuple[bool, str]:
    """Прогнать движок LaTeX (дважды) и вернуть (успех, журнал)."""
    cmd = [exe, "-interaction=nonstopmode", "-halt-on-error", tex.name]
    if engine == "tectonic":
        cmd = [exe, "--outdir", str(out_dir), tex.name]
    log = ""
    for _ in range(2):
        try:
            r = subprocess.run(cmd, cwd=str(out_dir), capture_output=True,
                               text=True, timeout=600)
        except Exception as exc:   # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"
        log = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0:
            return False, log
    return True, log


def write_report(npz_path: Path, gmid_ref: float | None = None,
                 id_ref: float | None = None) -> Path | None:
    """Собрать PDF-отчёт из готовой LUT (report_<stem>/report.pdf)."""
    from mosplot.plot import load_lookup_table

    gmid_ref = REPORT_GMID if gmid_ref is None else gmid_ref
    id_ref = REPORT_ID if id_ref is None else id_ref

    lt = load_lookup_table(str(npz_path))
    out_dir = npz_path.parent / f"report_{npz_path.stem}"
    figs_dir = out_dir / "figs"
    figs_dir.mkdir(parents=True, exist_ok=True)
    plot_dir = npz_path.parent / f"plots_{npz_path.stem}"

    devices = _devices_for(lt)
    if not devices:
        print(f"  ! в таблице {npz_path.name} нет известных устройств — отчёт пропущен")
        return None

    print("=" * 72)
    print(f"ОТЧЁТ: LaTeX -> PDF для {npz_path.name}  (-> {out_dir})")
    print("=" * 72)

    # 1. SVG -> PDF
    n_fig = 0
    for device in devices:
        for spec, _cap in _REPORT_FIGURES:
            svg = plot_dir / f"{spec}_{device['key']}.svg"
            if not svg.exists():
                continue
            if _svg_to_pdf(svg, figs_dir / f"{spec}_{device['key']}.pdf"):
                n_fig += 1
            else:
                print(f"  ! не удалось конвертировать {svg.name} "
                      "(нужен rsvg-convert или inkscape)")
    print(f"  рисунков сконвертировано: {n_fig}")

    # 2. LaTeX-исходник
    engine, exe = _find_tex_engine()
    tex_path = out_dir / "report.tex"
    tex_path.write_text(
        _report_body(lt, devices, npz_path, figs_dir, gmid_ref, id_ref,
                     engine or "xelatex"),
        encoding="utf-8")
    print(f"  LaTeX-исходник : {tex_path}")

    # 3. Компиляция
    if engine is None:
        print("  ! LaTeX-движок не найден (xelatex/lualatex/pdflatex). "
              "report.tex сохранён — скомпилируйте вручную.")
        return tex_path
    print(f"  движок         : {engine} ({exe})")
    ok, log = _run_tex(engine, exe, tex_path, out_dir)
    pdf_path = out_dir / "report.pdf"
    if ok and pdf_path.exists():
        for ext in (".aux", ".log", ".out", ".toc"):
            aux = out_dir / (tex_path.stem + ext)
            if aux.exists():
                aux.unlink()
        print(f"  PDF готов      : {pdf_path}")
        return pdf_path
    log_path = out_dir / "report.log"
    log_path.write_text(log, encoding="utf-8")
    print(f"  ! Компиляция не удалась. Журнал: {log_path}")
    for line in log.strip().splitlines()[-12:]:
        print("    " + line)
    return tex_path


# ===========================================================================
# 6. CLI
# ===========================================================================

def _corner_npzs(out_dir: Path, corners) -> list[Path]:
    """Пути .npz для списка углов (существующие и ожидаемые)."""
    corner_list = corners if corners else [None]
    out = []
    for corner in corner_list:
        tag = f"_{corner}" if corner else ""
        out.append(out_dir / f"{out_dir.name}{tag}.npz")
    return out


def main(argv=None) -> int:
    global NMOS_MODELS, PMOS_MODELS, MODELS_FILE
    global NMOS_VDD, PMOS_VDD, NMOS_LENGTHS, PMOS_LENGTHS
    global NMOS_VGS_START, PMOS_VGS_START
    parser = argparse.ArgumentParser(
        description="Универсальный gm/ID LUT генератор (Spectre) для любого PDK.")
    parser.add_argument("--models-file", "-m", default=MODELS_FILE,
                        help="файл моделей .scs (по умолчанию из блока НАСТРОЙКИ)")
    parser.add_argument("--models-dir", default=MODELS_DIR,
                        help="каталог с моделями: корневой .scs ищется автоматически, "
                             "include-файлы (в т.ч. во вложенных папках) разворачиваются")
    parser.add_argument("--nmos-model", "--nmos-models", dest="nmos_models", nargs="+",
                        default=None, help="имя(ена) NMOS-модели (можно несколько); "
                                           "none — выключить NMOS")
    parser.add_argument("--pmos-model", "--pmos-models", dest="pmos_models", nargs="+",
                        default=None, help="имя(ена) PMOS-модели (можно несколько); "
                                           "none — выключить PMOS")
    parser.add_argument("--corner", "--corners", dest="corners", nargs="+", default=None,
                        help="секция(и) угла в файле-библиотеке (например: tt ss ff)")
    parser.add_argument("--techname", default=TECHNAME,
                        help="имя технологии -> каталог lut_<techname> "
                             "(можно вложенное: proc/5v -> lut_proc/5v)")
    parser.add_argument("--vdd", type=float, default=None,
                        help="номинал питания, В (перебивает NMOS_VDD/PMOS_VDD)")
    parser.add_argument("--lengths", nargs="+", type=float, default=None,
                        metavar="L_um",
                        help="длины каналов, мкм (перебивает NMOS-/PMOS_LENGTHS)")
    parser.add_argument("--vgs-start", type=float, default=None, metavar="V",
                        help="нижняя |VGS| развёртки, В "
                             "(перебивает NMOS-/PMOS_VGS_START)")
    parser.add_argument("--symbols", nargs=2, metavar=("INST", "PROBE"),
                        help="имена экземпляра и probe (для subckt-моделей), "
                             "например: X1 X1.m1")
    parser.add_argument("--quick", action="store_true", help="грубые развертки")
    parser.add_argument("--op", action="store_true", help="пробная OP-симуляция")
    parser.add_argument("--no-build", action="store_true", help="только графики")
    parser.add_argument("--no-plot", action="store_true", help="только таблицы")
    parser.add_argument("--demo", action="store_true", help="пример расчёта по таблице")
    parser.add_argument("--report", action="store_true",
                        help="собрать PDF-отчёт (LaTeX) со всеми графиками и таблицами")
    parser.add_argument("--report-dir", default=None, metavar="PATH",
                        help="собрать PDF-отчёты для ВСЕХ .npz в каталоге/файле "
                             "(рекурсивно), без пересборки LUT")
    parser.add_argument("--interactive", "--dash", dest="interactive", action="store_true",
                        help="собрать интерактивный HTML-дашборд (Plotly) со всеми графиками")
    args = parser.parse_args(argv)

    # CLI-переопределения моделей (списки; пусто/'none' -> тип выключен).
    if args.nmos_models is not None:
        NMOS_MODELS = args.nmos_models
    if args.pmos_models is not None:
        PMOS_MODELS = args.pmos_models
    if args.vdd is not None:
        NMOS_VDD = PMOS_VDD = abs(float(args.vdd))
    if args.vgs_start is not None:
        NMOS_VGS_START = PMOS_VGS_START = abs(float(args.vgs_start))
    if args.lengths is not None:
        NMOS_LENGTHS = np.array([float(x) for x in args.lengths]) * 1e-6
        PMOS_LENGTHS = np.array(NMOS_LENGTHS, dtype=float)
    if not _devices():
        print("ОШИБКА: не задано ни одной модели "
              "(--nmos-model/--pmos-model = none).", file=sys.stderr)
        return 2

    out_dir = _out_dir(args.techname, args.models_dir or args.models_file)

    if not args.no_build:
        models_file = _resolve_models_source(args.models_file, args.models_dir, out_dir)
        if not models_file.exists():
            print(f"ОШИБКА: файл моделей не найден: {models_file}", file=sys.stderr)
            return 2
        if shutil.which(SPECTRE_BIN) is None and not Path(SPECTRE_BIN).exists():
            print("ОШИБКА: не найден Spectre. Выполните `source ~/.bashrc.cadence`\n"
                  "или задайте SPECTRE_BIN=/путь/к/spectre", file=sys.stderr)
            return 2

        sections = _detect_sections(models_file)
        if args.corners is None and sections:
            print(f"ОШИБКА: файл {models_file.name} похож на библиотеку с секциями "
                  f"{sections}.\nЗадайте угол: --corner {sections[0]} [и т.д.]",
                  file=sys.stderr)
            return 2

        args.models_file = str(models_file)
        MODELS_FILE = str(models_file)
        build_tables(args.corners, args.quick, args.op, args)

    npz_list = _corner_npzs(out_dir, args.corners)

    if not args.no_plot:
        for npz in npz_list:
            if npz.exists():
                make_plots(npz)
            else:
                print(f"нет таблицы {npz} — пропуск графиков")

    if args.demo and npz_list[0].exists():
        from mosplot.plot import load_lookup_table
        lt = load_lookup_table(str(npz_list[0]))
        for dev in _devices_for(lt):
            sizing_example(npz_list[0], dev["key"],
                           length=float(np.median(dev["lengths"])),
                           gmid_target=12.0, id_target=10e-6)

    if args.report or args.report_dir:
        from gmid_dash import _gather_npz
        if args.report_dir:
            targets = _gather_npz([args.report_dir], recursive=True)
            if not targets:
                print(f"в {args.report_dir} нет .npz — пропуск отчётов")
            for npz in targets:
                write_report(npz)
        else:
            for npz in npz_list:
                if npz.exists():
                    write_report(npz)
                else:
                    print(f"нет таблицы {npz} — пропуск отчёта")

    if args.interactive:
        from gmid_dash import build_dashboard
        # Один дашборд на весь прогон: все найденные .npz (в т.ч. все углы)
        # попадают в него как варианты одного и того же устройства.
        existing = [p for p in npz_list if p.exists()]
        if existing:
            build_dashboard(existing, out_dir=out_dir)
        else:
            print("нет таблиц — пропуск дашборда")

    print("\nГотово.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
