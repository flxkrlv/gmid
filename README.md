<a id="top"></a>

# gmid (fork) — gm/ID LUT toolchain for Spectre

**Language / Язык:** [English](#english) · [Русский](#русский)

> This repository is a fork of [**medwatt/gmid**](https://github.com/medwatt/gmid)
> (the *Mosplot* framework). It adds a self-contained, ready-to-run toolchain for
> characterising MOS devices with **Cadence Spectre** and producing gm/ID design
> data: lookup-table generation, SVG design charts, a LaTeX→PDF report and an
> interactive HTML dashboard. See [Acknowledgments](#acknowledgments).

---

## English

### What is this?

`gmid` is a fork of [medwatt/gmid](https://github.com/medwatt/gmid) — a Python
framework for analog circuit design using the **gm/ID methodology** (lookup
tables, design charts, multi-corner circuit optimization). The fork keeps the
upstream `mosplot` package untouched and adds a small, opinionated wrapper
directory, [`gmid_lut/`](gmid_lut), that turns Mosplot's machinery into a
one-command tool for real PDKs.

Everything the added scripts do is documented in their source comments; this
README is a faithful summary of those comments.

### What is different in this fork?

Upstream Mosplot exposes a general **library API**: you construct a simulator,
define `TransistorSweep`s, build a `LookupTableGenerator`, then write your own
plotting/optimization code. This fork adds, on top of that library, three files
(commit `c5e94cc`, *"add Spectre gm/ID LUT toolchain (gmid_lut/)"*):

| File | Role |
| --- | --- |
| [`gmid_lut/gmid_lut.py`](gmid_lut/gmid_lut.py) | Universal gm/ID LUT generator + charts + sizing demo + LaTeX→PDF report, driven by a config block and CLI. |
| [`gmid_lut/gmid_dash.py`](gmid_lut/gmid_dash.py) | Standalone interactive Plotly HTML dashboard from one or more `.npz` tables, with an operating-point calculator. |
| [`gmid_lut/run_gmid.sh`](gmid_lut/run_gmid.sh) | Launcher that sources the Cadence environment, cleans `LD_LIBRARY_PATH`, picks a Python interpreter and runs the toolchain. |

In short, the fork adds an **application** layer (Spectre-only, any PDK, CLI +
opinionated defaults) where upstream is a **framework**. The fork is designed so
that a working GPDK180 run needs only `./run_gmid.sh --quick`.

### Requirements

* Python 3.9+ (upstream `pyproject.toml`).
* Dependencies from upstream: `numpy`, `matplotlib`, `scipy`, `cma`, `numba`.
  The dashboard additionally needs `plotly`.
* **Cadence Spectre** (lookup-table generation only). The generator uses
  `SpectreSimulator`, so ngspice/HSPICE are *not* used by `gmid_lut.py`.
* Optional: a LaTeX engine (`xelatex`/`lualatex`/`pdflatex`/`tectonic`) and
  `rsvg-convert` (or `inkscape`) for the PDF report.

### Installation

```bash
git clone https://github.com/flxkrlv/gmid.git
cd gmid
pip install -e .
pip install plotly            # only for the interactive dashboard
```

The generator is run through [`gmid_lut/run_gmid.sh`](gmid_lut/run_gmid.sh),
which expects a Cadence environment (`~/.bashrc.cadence`) and a bash shell
(Linux).

### Quick start

Real invocations documented in the code:

```bash
./run_gmid.sh --quick                                    # quick test (models from settings)
./run_gmid.sh --report                                   # + PDF report (LaTeX)
./run_gmid.sh --interactive                              # + HTML dashboard (Plotly)

# Reports for every .npz in a directory, no rebuild and no Spectre:
./run_gmid.sh --no-build --no-plot --report-dir lut_gpdk180

# GPDK180 example: 1.8 V core, corners NN/SS/FF/SF/FS
./run_gmid.sh -m "$GPDK180/models/spectre/gpdk.scs" \
    --corner NN SS FF SF FS --nmos-model nmos1 --pmos-model pmos1 \
    --vdd 1.8 --vgs-start 0.2 --techname gpdk180

# Or directly, sourcing Cadence first:
source ~/.bashrc.cadence
export LD_LIBRARY_PATH=$(echo "$LD_LIBRARY_PATH" | tr ':' '\n' | grep -v python | paste -sd:)
python gmid_lut.py --models-file gpdk.scs --techname gpdk180 --quick

# Dashboard for a whole directory of tables:
.venv/bin/python gmid_dash.py lut_gpdk180
```

### Command line — `gmid_lut.py`

The script prints, builds, plots and reports. **All settings can be given either
in the config block (see below) or overridden on the CLI.** CLI wins.

| Argument | Default | Description |
| --- | --- | --- |
| `--models-file`, `-m` | `MODELS_FILE` from settings | `.scs` file containing the MOS models. |
| `--models-dir` | `MODELS_DIR` (`None`) | Directory with models. The root library `.scs` is found automatically and `include "..."` files (including nested `fast/slow/type` folders) are expanded recursively. Takes priority over `--models-file`. |
| `--nmos-model`, `--nmos-models` | `NMOS_MODELS` | One or more NMOS model names (space-separated). `none` disables the NMOS type. |
| `--pmos-model`, `--pmos-models` | `PMOS_MODELS` | One or more PMOS model names. `none` disables the PMOS type. |
| `--corner`, `--corners` | `CORNERS` | One or more sections of a library model file, e.g. `tt ss ff`. |
| `--techname` | `TECHNAME` | Technology name → output directory `lut_<techname>`. Nested paths allowed (`proc/5v` → `lut_proc/5v`). |
| `--vdd` | `NMOS_VDD`/`PMOS_VDD` | Supply, V. Overrides both NMOS and PMOS values. |
| `--lengths` | `NMOS_LENGTHS`/`PMOS_LENGTHS` | Channel lengths in **µm** (overrides both). |
| `--vgs-start` | `NMOS_VGS_START`/`PMOS_VGS_START` | Lower `\|VGS\|` of the sweep, V (overrides both). |
| `--symbols INST PROBE` | auto-detected | Instance name and probe name for subcircuit models, e.g. `X1 X1.m1`. |
| `--quick` | off | Coarse sweeps (`QUICK_SWEEP`) and thinned length list. |
| `--op` | off | Run one trial operating-point simulation. |
| `--no-build` | off | Do not run Spectre; only plot/report from existing `.npz` tables. |
| `--no-plot` | off | Build tables only, skip charts. |
| `--demo` | off | Print a gm/ID sizing example computed from the table. |
| `--report` | off | Build a PDF report (LaTeX) with all figures and tables. |
| `--report-dir PATH` | `None` | Build PDF reports for **every** `.npz` in a directory/file (recursively), without rebuilding the LUT. |
| `--interactive`, `--dash` | off | Build the standalone interactive HTML dashboard (Plotly). |

Behaviour notes taken from the code:

* The file is written per **corner**: `lut_<techname>[_<corner>].npz` (e.g.
  `lut_gpdk180_NN.npz`). With no corners, the name has no suffix.
* A flat model file → one table (no corner). A library file with sections
  requires `--corner`; otherwise the script errors and lists the sections found.
* A pre-flight DC run catches broken models (e.g. a `subckt` with the wrong pin
  count, or `as(w)` formulas that go negative at small `W`). A failing device is
  skipped with a warning; the rest still build. If **every** device fails, the
  run aborts.
* If the model exposes no `cgg`, `fT`/`Cgg` are skipped — the gm/ID method still
  works.
* If no `.scs` root is found in `--models-dir`, a merged `.models_merged.scs`
  including all found `.scs` is synthesised.

### Command line — `gmid_dash.py`

Builds a standalone (offline) HTML file from one or more ready `.npz` tables.
Plotly.js is embedded, so no internet connection is needed; open the file by
double-click.

| Argument | Default | Description |
| --- | --- | --- |
| `sources` (positional, 1+) | — | `.npz` files and/or directories containing them. |
| `-o`, `--out` | `None` | Path of the output `index.html`. |
| `--out-dir` | `None` | Directory; writes `<out-dir>/dash_<name>/index.html`. |
| `--no-recursive` | off | Do not search subdirectories for `.npz`. |

When several tables are given, devices with the same name become **variants**
(corners/supplies) of a single entry in the dashboard's device list.

Programmatic API:

```python
from gmid_dash import build_dashboard, solve_point

build_dashboard("lut_gpdk180/lut_gpdk180_NN.npz")                   # one table
build_dashboard(["lut_gpdk180/lut_gpdk180_NN.npz",
                 "lut_gpdk180/lut_gpdk180_SS.npz"])                 # several -> variants
build_dashboard("lut_gpdk180")                                      # whole directory

pt = solve_point("lut_gpdk180/lut_gpdk180_NN.npz", "nmos1", length=1e-6,
                 gmid=12.0, id_target=10e-6)
```

`solve_point` finds a bias point from one driving quantity (`gmid` > `vgs` >
`vov` > `idw`) and, if `id_target` (or `w_target`) is given, also computes `W`
(or `ID`).

### The settings block ("НАСТРОЙКИ")

The top of `gmid_lut.py` has an editable config block, framed by the comments
`НАЧАЛО`/`КОНЕЦ НАСТРОЕК`. Defaults are tuned for the example GPDK180
(`gpdk.scs`, `nmos1`/`pmos1`, 1.8 V core).

| Setting | Default | Meaning |
| --- | --- | --- |
| `GPDK180_DIR` | `$GPDK180` | If set, default `MODELS_FILE` becomes `$GPDK180/models/spectre/gpdk.scs`. |
| `MODELS_FILE` | `gpdk.scs` (or the GPDK180 path) | `.scs` with MOS models. |
| `MODELS_DIR` | `None` | Directory with models; takes priority over `MODELS_FILE`. |
| `NMOS_MODELS` | `["nmos1"]` | List (or single string) of NMOS models. Empty/`none` disables the type. |
| `PMOS_MODELS` | `["pmos1"]` | List of PMOS models. |
| `CORNERS` | `["NN","SS","FF","SF","FS"]` | Corner sections; `None` for a flat file. |
| `TECHNAME` | `"gpdk180"` | Output directory `lut_<TECHNAME>`. `None` → `lut_<models-file-stem>`. |
| `GPDK_LENGTHS` / `NMOS_LENGTHS` / `PMOS_LENGTHS` | `0.18 … 10 µm` | Channel lengths (m). |
| `NMOS_VDD` / `PMOS_VDD` | `1.8` | Supply (V). Sets the `VGS`/`VDS` range `0..\|VDD\|` and `VBS` range `0..−\|VDD\|` (NMOS) / `0..+\|VDD\|` (PMOS). |
| `NMOS_VGS_START` / `PMOS_VGS_START` | `0.2` | Lower `\|VGS\|` (V): starting closer to 0 puts the device deep in cutoff where gm/ID is noisy. |
| `SWEEP` | `vgs=0.025, vds=0.10, vbs=0.50` | Sweep steps (V) for a full run. |
| `QUICK_SWEEP` | `vgs=0.10, vds=0.50, vbs=1.00` | Sweep steps (V) for the `--quick` run. |
| `QUICK_LENGTH_STRIDE` | `2` | Length-list decimation factor in quick mode. |
| `TEMPERATURE` | `27.0` | Simulation temperature, °C. |
| `DEVICE_WIDTH` | `40e-6` | Fixed width of the reference transistor, m. |
| `N_PROCESS` | `$GMID_NPROC` or `4` | Number of parallel simulation processes. |
| `SPECTRE_BIN` | `$SPECTRE_BIN` or `"spectre"` | Spectre binary. |
| `MOS_SYMBOLS` | `None` | `(instance, probe)` names; `None` → auto-detect from the model file. |
| `EXTRA_DEVICE_PARAMETERS` | `{}` | Extra instance parameters written to the netlist (`w` is always added). E.g. `{"as":1e-12,"ad":1e-12,"ps":1e-6,"pd":1e-6}`. |
| `REPORT_GMID` | `12.0` | Reference gm/ID (1/V) for the report tables. |
| `REPORT_ID` | `10e-6` | Reference drain current (A) for the report tables. |

Auto-detection details (from the comments): a model written as `model nmos ...`
is probed as `("M1", "M1")`; a `subckt` wrapping a 4-terminal device `m1` is
probed as `("X1", "X1.m1")`.

### Environment variables

| Variable | Used by | Effect |
| --- | --- | --- |
| `GPDK180` | `gmid_lut.py` | Default PDK path for `MODELS_FILE`. |
| `GMID_NPROC` | `gmid_lut.py` | Overrides `N_PROCESS` (parallel processes). |
| `SPECTRE_BIN` | `gmid_lut.py` | Overrides the Spectre binary path. |
| `MPLBACKEND` | `gmid_lut.py` | Forced to `Agg` so `plt.show()` never blocks. |
| `GMID_SCRIPT` | `run_gmid.sh` | Script to run (default `gmid_lut.py`). |
| `GMID_PYTHON` | `run_gmid.sh` | Python interpreter to use. |

`run_gmid.sh` selects Python in this order: `$GMID_PYTHON` → `./.venv/bin/python`
→ `python3`. If its first argument is an existing `*.py` file, that file is used
as the script and the remaining arguments are passed to it.

### Output layout

For `--techname gpdk180` with corners `NN SS FF SF FS`:

```
gmid_lut/
├─ lut_gpdk180/
│  ├─ lut_gpdk180_NN.npz            # lookup table per corner
│  ├─ lut_gpdk180_SS.npz
│  ├─ ...
│  ├─ plots_lut_gpdk180_NN/         # SVG charts per table
│  │  ├─ idw_vs_gmid_nmos1.svg
│  │  ├─ ft_vs_gmid_nmos1.svg       # only if the model exposes Cgg
│  │  ├─ gmro_vs_gmid_nmos1.svg
│  │  ├─ gmid_vs_vov_nmos1.svg
│  │  ├─ id_vs_vgs_nmos1.svg
│  │  ├─ id_vs_vds_nmos1.svg
│  │  ├─ vdsat_vov_vstar_vs_vgs_nmos1.svg
│  │  └─ ...
│  ├─ report_lut_gpdk180_NN/        # PDF report (with --report)
│  │  ├─ report.tex
│  │  ├─ report.pdf
│  │  └─ figs/
│  └─ dash_lut_gpdk180/index.html   # dashboard (with --interactive)
```

The table is a 4-D array indexed by `length × vbs × vgs × vds`, saved with
`numpy.savez_compressed`. Its keys are the device names plus
`description`, `simulator`, `parameter_names` and `device_parameters`.

### Charts produced per device

For each device (`<key>` = model name) the generator produces:

* `idw_vs_gmid` — `ID/W` vs `gm/ID` (log Y)
* `ft_vs_gmid` — transit frequency `fT` vs `gm/ID` (only if `cgg` exists)
* `gmro_vs_gmid` — intrinsic gain `gm·ro = gm/gds` vs `gm/ID` (log Y)
* `gmid_vs_vov` — `gm/ID` vs `Vov = |VGS| − |Vth|`
* `id_vs_vgs` — `ID` vs `VGS` for several lengths (log Y)
* `id_vs_vds` — output characteristics `ID` vs `VDS` at `VGS = 0.5·VDD, VDD`
* `vdsat_vov_vstar_vs_vgs` — `VDS,sat`, `VOV`, `V*` vs `VGS`

If the model has no capacitance data, `fT` is skipped with a message — the gm/ID
method works without capacitances.

### PDF report (`--report` / `--report-dir`)

Assembles a LaTeX document with: a title page (table file, model file, devices,
temperature, reference width/`gm/ID`/`ID`, build date), the gm/ID methodology
introduction, a legend of all saved LUT parameters and derived quantities, the
sweep settings table, and — per device — all available figures plus "key point"
tables (per length and at the target `gm/ID`). SVG→PDF conversion needs
`rsvg-convert` or `inkscape`; compilation needs a LaTeX engine. If no engine is
found, `report.tex` and the figures are still written so you can compile
manually (`xelatex report.tex`).

### Interactive dashboard (`--interactive` / `gmid_dash.py`)

* All static charts become interactive (hover, zoom, pan, toggle lengths by
  clicking the legend).
* Switchers for device / run-corner (when several `.npz` are combined) / `VDS`
  (as a fraction of `VDD`) / `VBS`.
* Point search by `gm/ID`, `|VGS|`, `Vov` or `ID/W`, marking the found point on
  the charts.
* Operating-point calculator: give the known quantity (gm/ID or VGS/Vov/ID/W)
  and a target current, and get all other parameters plus the width `W`.

### Acknowledgments

This fork would not exist without [**medwatt/gmid**](https://github.com/medwatt/gmid)
by **Mohamed Watfa** (with Alberto Garcia-Ortiz and Gilles Sassatelli). The
`mosplot` framework, its lookup-table engine, the `SpectreSimulator` and the
plotting/interpolation code are the upstream work — the `gmid_lut/` scripts are
a thin application layer built on top of them. If you use this in academic work,
please cite the upstream project:

```bibtex
@article{watfa2026residual,
  author  = {Watfa, Mohamed and Garcia-Ortiz, Alberto and Sassatelli, Gilles},
  title   = {A Residual-Equation Framework for {$\mathrm{gm}/I_D$} Analog Circuit Design
             with Automated Multicorner Sizing},
  journal = {IEEE Transactions on Circuits and Systems I: Regular Papers},
  year    = {2026},
  doi     = {10.1109/TCSI.2026.3736902}
}
```

The HSPICE output parser in upstream is based on
[hspiceParser](https://github.com/HMC-ACE/hspiceParser).

The upstream *Mosplot* README, guides and figures are kept in this repository
under [`docs/`](docs) and mirrored at the original project:
<https://github.com/medwatt/gmid>.

[⬆ Back to top](#top)

---

## Русский

### Что это

`gmid` — форк проекта [**medwatt/gmid**](https://github.com/medwatt/gmid)
(фреймворк *Mosplot*). Это Python-фреймворк для проектирования аналоговых схем
по методике **gm/ID** (таблицы крутизны, графики, многокорнерная оптимизация).
Форк не трогает апстримный пакет `mosplot`, а добавляет поверх него небольшой
самодостаточный каталог [`gmid_lut/`](gmid_lut), превращающий механику Mosplot
в инструмент «одной команды» для реальных PDK.

Всё, что делают добавленные скрипты, описано в комментариях к их коду; этот
README — аккуратное изложение этих комментариев.

### Чем отличается именно этот репозиторий

Апстримный Mosplot даёт **библиотечный API**: сам создаёшь симулятор, задаёшь
`TransistorSweep`, собираешь `LookupTableGenerator`, а затем пишешь свой код
построения и оптимизации. Форк добавляет поверх библиотеки три файла (коммит
`c5e94cc`, *"add Spectre gm/ID LUT toolchain (gmid_lut/)"*):

| Файл | Назначение |
| --- | --- |
| [`gmid_lut/gmid_lut.py`](gmid_lut/gmid_lut.py) | Универсальный генератор gm/ID LUT + графики + пример расчёта + PDF-отчёт (LaTeX), управляется блоком настроек и CLI. |
| [`gmid_lut/gmid_dash.py`](gmid_lut/gmid_dash.py) | Автономный интерактивный HTML-дашборд (Plotly) из одного/нескольких `.npz`, с калькулятором рабочей точки. |
| [`gmid_lut/run_gmid.sh`](gmid_lut/run_gmid.sh) | Launcher: подключает окружение Cadence, чистит `LD_LIBRARY_PATH`, выбирает Python и запускает инструмент. |

Коротко: форк добавляет **прикладной слой** (только Spectre, любой PDK, CLI и
готовые значения по умолчанию), тогда как апстрим — это **фреймворк**. Форк
спроектирован так, чтобы рабочий прогон GPDK180 требовал лишь
`./run_gmid.sh --quick`.

### Требования

* Python 3.9+ (из `pyproject.toml` апстрима).
* Зависимости апстрима: `numpy`, `matplotlib`, `scipy`, `cma`, `numba`.
  Для дашборда дополнительно нужен `plotly`.
* **Cadence Spectre** (только для генерации LUT). Генератор использует
  `SpectreSimulator`, поэтому ngspice/HSPICE в `gmid_lut.py` *не* применяются.
* Опционально: движок LaTeX (`xelatex`/`lualatex`/`pdflatex`/`tectonic`) и
  `rsvg-convert` (или `inkscape`) для PDF-отчёта.

### Установка

```bash
git clone https://github.com/flxkrlv/gmid.git
cd gmid
pip install -e .
pip install plotly            # только для интерактивного дашборда
```

Генератор запускается через [`gmid_lut/run_gmid.sh`](gmid_lut/run_gmid.sh),
который ожидает окружение Cadence (`~/.bashrc.cadence`) и bash (Linux).

### Быстрый старт

Примеры запусков из комментариев к коду:

```bash
./run_gmid.sh --quick                                    # быстрый тест (модели из НАСТРОЕК)
./run_gmid.sh --report                                   # + PDF-отчёт (LaTeX)
./run_gmid.sh --interactive                              # + HTML-дашборд (Plotly)

# отчёты по всем .npz каталога, без пересборки и без Spectre:
./run_gmid.sh --no-build --no-plot --report-dir lut_gpdk180

# пример GPDK180: ядро 1.8 В, углы NN/SS/FF/SF/FS
./run_gmid.sh -m "$GPDK180/models/spectre/gpdk.scs" \
    --corner NN SS FF SF FS --nmos-model nmos1 --pmos-model pmos1 \
    --vdd 1.8 --vgs-start 0.2 --techname gpdk180

# или напрямую, сначала подключив Cadence:
source ~/.bashrc.cadence
export LD_LIBRARY_PATH=$(echo "$LD_LIBRARY_PATH" | tr ':' '\n' | grep -v python | paste -sd:)
python gmid_lut.py --models-file gpdk.scs --techname gpdk180 --quick

# дашборд сразу по всему каталогу таблиц:
.venv/bin/python gmid_dash.py lut_gpdk180
```

### Команда запуска `gmid_lut.py` и все её аргументы

Скрипт печатает, строит, рисует и собирает отчёты. **Любую настройку можно
задать как в блоке НАСТРОЙКИ, так и переопределить аргументом CLI** (CLI имеет
приоритет).

| Аргумент | По умолчанию | Описание |
| --- | --- | --- |
| `--models-file`, `-m` | `MODELS_FILE` из настроек | `.scs`-файл с MOS-моделями. |
| `--models-dir` | `MODELS_DIR` (`None`) | Каталог с моделями: корневой `.scs`-файл-библиотека ищется автоматически, а `include "..."` (в т.ч. во вложенных `fast/slow/type`) разворачиваются рекурсивно. Приоритет над `--models-file`. |
| `--nmos-model`, `--nmos-models` | `NMOS_MODELS` | Одно или несколько имён NMOS-моделей (списком). `none` — тип выключен. |
| `--pmos-model`, `--pmos-models` | `PMOS_MODELS` | Одно или несколько имён PMOS-моделей. `none` — тип выключен. |
| `--corner`, `--corners` | `CORNERS` | Секция(и) угла в файле-библиотеке, напр. `tt ss ff`. |
| `--techname` | `TECHNAME` | Имя технологии → каталог `lut_<techname>`. Можно вложенное (`proc/5v` → `lut_proc/5v`). |
| `--vdd` | `NMOS_VDD`/`PMOS_VDD` | Номинал питания, В. Перебивает оба значения. |
| `--lengths` | `NMOS_LENGTHS`/`PMOS_LENGTHS` | Длины каналов в **мкм** (перебивает оба списка). |
| `--vgs-start` | `NMOS_VGS_START`/`PMOS_VGS_START` | Нижняя `\|VGS\|` развёртки, В (перебивает оба). |
| `--symbols INST PROBE` | автоопределение | Имена экземпляра и probe (для subckt-моделей), напр. `X1 X1.m1`. |
| `--quick` | выкл | Грубые развёртки (`QUICK_SWEEP`) и прореживание списка длин. |
| `--op` | выкл | Пробная operating-point симуляция. |
| `--no-build` | выкл | Не запускать Spectre; только графики/отчёты по готовым `.npz`. |
| `--no-plot` | выкл | Только таблицы, без графиков. |
| `--demo` | выкл | Печать примера расчёта (сайзинга) по таблице. |
| `--report` | выкл | PDF-отчёт (LaTeX) со всеми графиками и таблицами. |
| `--report-dir PATH` | `None` | PDF-отчёты для **всех** `.npz` в каталоге/файле (рекурсивно), без пересборки LUT. |
| `--interactive`, `--dash` | выкл | Автономный интерактивный HTML-дашборд (Plotly). |

Детали поведения из кода:

* Таблица пишется на каждый **угол**: `lut_<techname>[_<corner>].npz`
  (например `lut_gpdk180_NN.npz`). Без углов суффикса нет.
* Плоский файл моделей → одна таблица (без угла). Файл-библиотека с секциями
  требует `--corner`; иначе скрипт сообщает ошибку и печатает список секций.
* Пробный DC-прогон (`preflight`) ловит «падающие» модели (неверное число
  выводов `subckt`, отрицательные формулы `as(w)` при узком `W`). Сбойное
  устройство пропускается с предупреждением, остальные собираются. Если упали
  **все** устройства — прогон прерывается.
* Если модель не отдаёт `cgg`, график `fT`/`Cgg` пропускается — методика gm/ID
  работает и без ёмкостей.
* Если в `--models-dir` нет корневого `.scs`, синтезируется сводный
  `.models_merged.scs`, включающий все найденные `.scs`.

### Команда `gmid_dash.py`

Строит автономный (offline) HTML-файл из одной/нескольких готовых `.npz`.
Plotly.js встраивается в файл, поэтому интернет не нужен — файл открывается
двойным кликом.

| Аргумент | По умолчанию | Описание |
| --- | --- | --- |
| `sources` (позиционный, 1+) | — | `.npz`-файлы и/или каталоги с ними. |
| `-o`, `--out` | `None` | Путь к выходному `index.html`. |
| `--out-dir` | `None` | Каталог; кладёт `<out-dir>/dash_<name>/index.html`. |
| `--no-recursive` | выкл | Не искать `.npz` во вложенных подкаталогах. |

Если таблиц несколько, одноимённые устройства становятся **вариантами**
(угол/питание) одного пункта в списке устройств дашборда.

Программный API:

```python
from gmid_dash import build_dashboard, solve_point

build_dashboard("lut_gpdk180/lut_gpdk180_NN.npz")                   # один .npz
build_dashboard(["lut_gpdk180/lut_gpdk180_NN.npz",
                 "lut_gpdk180/lut_gpdk180_SS.npz"])                 # несколько -> варианты
build_dashboard("lut_gpdk180")                                      # каталог

pt = solve_point("lut_gpdk180/lut_gpdk180_NN.npz", "nmos1", length=1e-6,
                 gmid=12.0, id_target=10e-6)
```

`solve_point` находит рабочую точку по одному заданному параметру
(`gmid` > `vgs` > `vov` > `idw`) и, если задан `id_target` (или `w_target`),
считает ширину `W` (или ток `ID`).

### Блок настроек («НАСТРОЙКИ»)

В начале `gmid_lut.py` есть редактируемый блок, обрамлённый комментариями
`НАЧАЛО`/`КОНЕЦ НАСТРОЕК`. Значения по умолчанию настроены под пример GPDK180
(`gpdk.scs`, `nmos1`/`pmos1`, ядро 1.8 В).

| Настройка | По умолчанию | Смысл |
| --- | --- | --- |
| `GPDK180_DIR` | `$GPDK180` | Если задана, `MODELS_FILE` по умолчанию = `$GPDK180/models/spectre/gpdk.scs`. |
| `MODELS_FILE` | `gpdk.scs` (или путь GPDK180) | `.scs` с MOS-моделями. |
| `MODELS_DIR` | `None` | Каталог с моделями; приоритет над `MODELS_FILE`. |
| `NMOS_MODELS` | `["nmos1"]` | Список (или строка) NMOS-моделей. Пусто/`none` — тип выключен. |
| `PMOS_MODELS` | `["pmos1"]` | Список PMOS-моделей. |
| `CORNERS` | `["NN","SS","FF","SF","FS"]` | Секции углов; `None` для плоского файла. |
| `TECHNAME` | `"gpdk180"` | Выходной каталог `lut_<TECHNAME>`. `None` → `lut_<имя-файла>`. |
| `GPDK_LENGTHS` / `NMOS_LENGTHS` / `PMOS_LENGTHS` | `0.18 … 10 µm` | Длины каналов (м). |
| `NMOS_VDD` / `PMOS_VDD` | `1.8` | Питание (В). Задаёт диапазоны `VGS`/`VDS` = `0..\|VDD\|` и `VBS` = `0..−\|VDD\|` (NMOS) / `0..+\|VDD\|` (PMOS). |
| `NMOS_VGS_START` / `PMOS_VGS_START` | `0.2` | Нижняя `\|VGS\|` (В): слишком близко к 0 — прибор в глубокой отсечке, gm/ID шумит. |
| `SWEEP` | `vgs=0.025, vds=0.10, vbs=0.50` | Шаги развёрток (В) полного прогона. |
| `QUICK_SWEEP` | `vgs=0.10, vds=0.50, vbs=1.00` | Шаги развёрток (В) для `--quick`. |
| `QUICK_LENGTH_STRIDE` | `2` | Прореживание списка длин в быстром режиме. |
| `TEMPERATURE` | `27.0` | Температура симуляции, °C. |
| `DEVICE_WIDTH` | `40e-6` | Фиксированная ширина эталонного транзистора, м. |
| `N_PROCESS` | `$GMID_NPROC` или `4` | Число параллельных процессов симуляции. |
| `SPECTRE_BIN` | `$SPECTRE_BIN` или `"spectre"` | Бинарник Spectre. |
| `MOS_SYMBOLS` | `None` | Имена `(экземпляр, probe)`; `None` → автоопределение по файлу моделей. |
| `EXTRA_DEVICE_PARAMETERS` | `{}` | Доп. параметры прибора в нетлист (`w` добавляется всегда). Напр. `{"as":1e-12,"ad":1e-12,"ps":1e-6,"pd":1e-6}`. |
| `REPORT_GMID` | `12.0` | Эталонный `gm/ID` (1/В) для таблиц отчёта. |
| `REPORT_ID` | `10e-6` | Эталонный ток стока (А) для таблиц отчёта. |

Автоопределение символов (из комментариев): модель `model nmos ...`
пробуется как `("M1", "M1")`; `subckt`, внутри которого 4-выводный прибор `m1`,
пробуется как `("X1", "X1.m1")`.

### Переменные окружения

| Переменная | Где используется | Действие |
| --- | --- | --- |
| `GPDK180` | `gmid_lut.py` | Путь к PDK для `MODELS_FILE` по умолчанию. |
| `GMID_NPROC` | `gmid_lut.py` | Перебивает `N_PROCESS` (число процессов). |
| `SPECTRE_BIN` | `gmid_lut.py` | Перебивает путь к Spectre. |
| `MPLBACKEND` | `gmid_lut.py` | Принудительно `Agg`, чтобы `plt.show()` не блокировал. |
| `GMID_SCRIPT` | `run_gmid.sh` | Запускаемый скрипт (по умолчанию `gmid_lut.py`). |
| `GMID_PYTHON` | `run_gmid.sh` | Интерпретатор Python. |

`run_gmid.sh` выбирает Python в порядке: `$GMID_PYTHON` → `./.venv/bin/python`
→ `python3`. Если первый аргумент — существующий `*.py`-файл, он берётся как
скрипт, а остальные аргументы передаются ему.

### Структура выходных файлов

Для `--techname gpdk180` и углов `NN SS FF SF FS`:

```
gmid_lut/
├─ lut_gpdk180/
│  ├─ lut_gpdk180_NN.npz            # таблица LUT на каждый угол
│  ├─ lut_gpdk180_SS.npz
│  ├─ ...
│  ├─ plots_lut_gpdk180_NN/         # SVG-графики к таблице
│  │  ├─ idw_vs_gmid_nmos1.svg
│  │  ├─ ft_vs_gmid_nmos1.svg       # только если в модели есть Cgg
│  │  ├─ gmro_vs_gmid_nmos1.svg
│  │  ├─ gmid_vs_vov_nmos1.svg
│  │  ├─ id_vs_vgs_nmos1.svg
│  │  ├─ id_vs_vds_nmos1.svg
│  │  ├─ vdsat_vov_vstar_vs_vgs_nmos1.svg
│  │  └─ ...
│  ├─ report_lut_gpdk180_NN/        # PDF-отчёт (с --report)
│  │  ├─ report.tex
│  │  ├─ report.pdf
│  │  └─ figs/
│  └─ dash_lut_gpdk180/index.html   # дашборд (с --interactive)
```

Таблица — это 4-мерный массив с индексами `length × vbs × vgs × vds`,
сохраняется через `numpy.savez_compressed`. Ключи: имена устройств плюс
`description`, `simulator`, `parameter_names`, `device_parameters`.

### Графики, строящиеся на каждое устройство

Для каждого устройства (`<key>` = имя модели) строятся:

* `idw_vs_gmid` — `ID/W` от `gm/ID` (лог. ось Y)
* `ft_vs_gmid` — граничная частота `fT` от `gm/ID` (только при наличии `cgg`)
* `gmro_vs_gmid` — собственное усиление `gm·ro = gm/gds` от `gm/ID` (лог. Y)
* `gmid_vs_vov` — `gm/ID` от `Vov = |VGS| − |Vth|`
* `id_vs_vgs` — `ID` от `VGS` для нескольких длин (лог. Y)
* `id_vs_vds` — выходные характеристики `ID(VDS)` при `VGS = 0.5·VDD, VDD`
* `vdsat_vov_vstar_vs_vgs` — `VDS,sat`, `VOV`, `V*` от `VGS`

Если в модели нет данных о ёмкостях, `fT` пропускается с сообщением — методика
gm/ID работает и без ёмкостей.

### PDF-отчёт (`--report` / `--report-dir`)

Собирает LaTeX-документ: титульную страницу (файл таблицы, файл моделей,
устройства, температура, эталонные ширина/`gm/ID`/`ID`, дата сборки), введение
по методике gm/ID, расшифровку всех сохраняемых и производных параметров LUT,
таблицу настроек развёрток и — по каждому устройству — все доступные графики и
таблицы «основных точек» (по длинам и по целевому `gm/ID`). Для конвертации
SVG→PDF нужен `rsvg-convert` или `inkscape`; для сборки — движок LaTeX. Если
движка нет, `report.tex` и рисунки всё равно сохраняются, и можно собрать
вручную (`xelatex report.tex`).

### Интерактивный дашборд (`--interactive` / `gmid_dash.py`)

* Все статические графики становятся интерактивными (hover, зум, панорамирование,
  вкл/выкл кривых по длине кликом по легенде).
* Переключатели: устройство / прогон-угол (если объединено несколько `.npz`) /
  `VDS` (доля `VDD`) / `VBS`.
* Поиск точки по `gm/ID`, `|VGS|`, `Vov` или `ID/W` с отметкой найденной точки
  на графиках.
* Калькулятор рабочей точки: задаёшь известное (`gm/ID` или VGS/Vov/ID/W) и
  целевой ток — получаешь остальные параметры и ширину `W`.

### Благодарности

Этот форк не существовал бы без [**medwatt/gmid**](https://github.com/medwatt/gmid)
автора **Mohamed Watfa** (совместно с Alberto Garcia-Ortiz и Gilles Sassatelli).
Фреймворк `mosplot`, его движок LUT, `SpectreSimulator` и код построения/интерполяции
— работа апстрима; скрипты `gmid_lut/` — лишь тонкий прикладной слой над ними.
Если вы используете это в научной работе, пожалуйста, цитируйте апстрим:

```bibtex
@article{watfa2026residual,
  author  = {Watfa, Mohamed and Garcia-Ortiz, Alberto and Sassatelli, Gilles},
  title   = {A Residual-Equation Framework for {$\mathrm{gm}/I_D$} Analog Circuit Design
             with Automated Multicorner Sizing},
  journal = {IEEE Transactions on Circuits and Systems I: Regular Papers},
  year    = {2026},
  doi     = {10.1109/TCSI.2026.3736902}
}
```

Парсер вывода HSPICE в апстриме основан на
[hspiceParser](https://github.com/HMC-ACE/hspiceParser).

Оригинальный README *Mosplot*, руководства и рисунки сохранены в этом
репозитории в каталоге [`docs/`](docs) и продублированы в исходном проекте:
<https://github.com/medwatt/gmid>.

[⬆ Наверх](#top)
