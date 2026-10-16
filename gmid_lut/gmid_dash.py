#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gmid_dash.py — интерактивный HTML-дашборд gm/ID (Plotly).
======================================================================

Строит автономный (offline) HTML-файл по готовой LUT `.npz`:

  * все графики из статического набора, но интерактивные:
    ID/W, fT, gm·ro, gm/ID↔Vov, ID(VGS), Vdsat/Vov/V*(VGS), ID(VDS);
  * hover показывает значения по осям и все параметры точки (курсор-спайки);
  * переключатели устройство / прогон-угол (если в дашборд собрано несколько
    .npz) / VDS(доля VDD) / VBS, вкл/выкл кривых по L кликом по легенде,
    зум и панорамирование;
  * «поиск по точкам»: поиск ближайшей рабочей точки по gm/ID, |VGS|, Vov
    или ID/W с отметкой на графиках;
  * калькулятор: задаёшь известное (gm/ID или VGS/Vov/ID/W) и целевой ток —
    получаешь остальные параметры и ширину W.

Plotly.js встраивается в файл, поэтому интернет не нужен. Файл открывается
двойным кликом в браузере.

Программный API:

    from gmid_dash import build_dashboard, solve_point
    build_dashboard("lut_gpdk180/lut_gpdk180_NN.npz")            # один .npz
    build_dashboard(["lut_gpdk180/lut_gpdk180_NN.npz",
                     "lut_gpdk180/lut_gpdk180_SS.npz"])          # несколько -> варианты
    build_dashboard("lut_gpdk180")                               # каталог (рекурсивно)
    pt = solve_point("lut_gpdk180/lut_gpdk180_NN.npz", "nmos1", length=1e-6,
                     gmid=12.0, id_target=10e-6)

CLI:

    python gmid_dash.py lut_gpdk180            # все .npz каталога
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

# Кванты, которые тянем из таблицы (кроме vgs/vov — они обрабатываются особо).
_QUANTITIES = ("vth", "vdsat", "vov", "vstar", "gmid", "idw", "id",
               "gm", "gds", "gain", "ft", "cgg")


def _r(a, nsig: int = 6):
    """Список чисел с округлением до nsig значащих цифр (None для NaN/inf)."""
    out = []
    for x in np.asarray(a, dtype=float).ravel():
        out.append(None if not np.isfinite(x) else float(f"{x:.{nsig}g}"))
    return out


def _pick_lengths(available, count: int) -> list:
    available = np.asarray(available, dtype=float)
    if len(available) <= count:
        return list(available)
    idx = np.unique(np.linspace(0, len(available) - 1, count).round().astype(int))
    return [float(available[i]) for i in idx]


def _curve(lt: dict, device: dict, vds: float, vbs: float, length: float,
           stride: int, have_ft: bool) -> tuple[dict, int]:
    """Кривые по VGS для одной длины/смещений. Возвращает (rec, peak)."""
    from mosplot.plot import Mosfet

    key = device["key"]
    axis = np.asarray(lt[key]["vgs"], dtype=float)
    step = axis[1] - axis[0]
    mos = Mosfet(lookup_table=lt, mos=key, vbs=vbs, vds=vds,
                 vgs=(axis[0], axis[-1], step))
    want = {
        "vgs": mos.vgs_expression, "vth": mos.vth_expression,
        "vdsat": mos.vdsat_expression, "vstar": mos.vstar_expression,
        "gmid": mos.gmid_expression, "idw": mos.current_density_expression,
        "id": mos.id_expression, "gm": mos.gm_expression,
        "gds": mos.gds_expression, "gain": mos.gain_expression,
    }
    if have_ft:
        want["ft"] = mos.transit_frequency_expression
        want["cgg"] = mos.cgg_expression
    names = list(want)
    with np.errstate(divide="ignore", invalid="ignore"):
        res = mos.lookup_expression_from_table(
            length=length, vbs=vbs, vds=vds, vgs=(axis[0], axis[-1], step),
            primary="vgs", expression=[want[n] for n in names])

    raw = {n: np.asarray(res[i], dtype=float) for i, n in enumerate(names)}
    vg = np.abs(raw["vgs"])
    order = np.argsort(vg)
    vg = vg[order]
    rec = {n: np.abs(raw[n])[order] for n in names if n != "vgs"}
    rec["vov"] = vg - np.abs(raw["vth"])[order]   # знаковый Vov
    rec["vgs"] = vg
    peak = int(np.argmax(rec["gmid"]))

    sl = slice(0, None, max(1, stride))
    out = {n: _r(rec[n][sl]) for n in rec}
    # индекс пика после прореживания
    out_peak = peak // max(1, stride)
    return out, out_peak


def _iv_curves(lt: dict, device: dict, length: float, vdd: float,
               stride: int) -> list:
    """Семейство ID(VDS) для нескольких VGS при фиксированной длине."""
    from mosplot.plot import Mosfet

    key = device["key"]
    sign = 1.0 if device["kind"] == "nmos" else -1.0
    vds_axis = np.asarray(lt[key]["vds"], dtype=float)
    vgs_axis = np.asarray(lt[key]["vgs"], dtype=float)
    mos = Mosfet(lookup_table=lt, mos=key, vbs=0.0,
                 vds=sign * vdd, vgs=(vgs_axis[0], vgs_axis[-1]))
    curves = []
    for frac in (0.5, 0.75, 1.0):
        vgs = sign * frac * vdd
        with np.errstate(divide="ignore", invalid="ignore"):
            res = mos.lookup_expression_from_table(
                length=length, vbs=0.0, vgs=vgs,
                vds=(vds_axis[0], vds_axis[-1], vds_axis[1] - vds_axis[0]),
                primary="vds",
                expression=[mos.vds_expression, mos.id_expression])
        x = np.abs(np.asarray(res[0], dtype=float))
        y = np.abs(np.asarray(res[1], dtype=float))
        order = np.argsort(x)
        sl = slice(0, None, max(1, stride))
        curves.append({"vgs": round(abs(vgs), 4),
                       "vds": _r(x[order][sl]), "id": _r(y[order][sl])})
    return curves


def _npz_label(npz_path) -> str:
    """Человекочитаемая метка таблицы (угол) из имени файла."""
    stem = Path(npz_path).stem
    return stem[4:] if stem.startswith("lut_") else stem


def _collect_one(npz_path, n_vbs: int = 3, vds_fracs=(0.35, 0.5, 0.7, 1.0),
                 max_lengths: int = 8, stride: int = 2) -> dict:
    """Собрать данные одного .npz: {device_key: entry}."""
    from gmid_lut import _devices_for
    from mosplot.plot import load_lookup_table

    lt = load_lookup_table(str(npz_path))
    devices = {}
    for device in _devices_for(lt):
        key = device["key"]
        if key not in lt:
            continue
        vdd = abs(device["vdd"])
        have_ft = "cgg" in set(lt.get("parameter_names", []))
        lengths = _pick_lengths(lt[key]["length"], max_lengths)

        vds_axis = np.asarray(lt[key]["vds"], dtype=float)
        vbs_axis = np.asarray(lt[key]["vbs"], dtype=float)

        # VDS: ближайшие точки сетки к заданным долям VDD (без повторов).
        vds_idx = []
        for frac in vds_fracs:
            i = int(np.argmin(np.abs(np.abs(vds_axis) - frac * vdd)))
            if i not in vds_idx:
                vds_idx.append(i)
        vds_values = [float(vds_axis[i]) for i in vds_idx]
        vds_fracs_used = [round(abs(v) / vdd, 3) for v in vds_values]

        # VBS: несколько точек сетки (0, средняя, максимальная по модулю).
        n_vbs = max(1, min(n_vbs, len(vbs_axis)))
        vbs_idx = list(np.unique(np.linspace(0, len(vbs_axis) - 1, n_vbs)
                                 .round().astype(int)))
        vbs_values = [float(vbs_axis[i]) for i in vbs_idx]

        series: dict = {}
        for vi, vds in enumerate(vds_values):
            for bi, vbs in enumerate(vbs_values):
                combo = {}
                for li, length in enumerate(lengths):
                    rec, peak = _curve(lt, device, vds, vbs, length,
                                       stride, have_ft)
                    rec["peak"] = peak
                    combo[str(li)] = rec
                series[f"{vi}_{bi}"] = combo

        iv = _iv_curves(lt, device, float(lengths[len(lengths) // 2]),
                        vdd, stride)

        devices[key] = {
            "kind": device["kind"], "vdd": round(vdd, 4),
            "lengths": _r(lengths), "have_ft": have_ft,
            "vds_values": _r(vds_values), "vds_fracs": vds_fracs_used,
            "vbs_values": _r(vbs_values),
            "series": series, "iv": iv,
        }
    return devices


def collect(npz_paths, n_vbs: int = 3, vds_fracs=(0.35, 0.5, 0.7, 1.0),
            max_lengths: int = 8, stride: int = 2) -> dict:
    """Собрать данные для дашборда из одного или нескольких .npz.

    Каждое устройство получает словарь `variants` (метка .npz -> данные) —
    так один и тот же транзистор, снятый в разных углах/на разном питании,
    показывается как один пункт в списке устройств с переключателем варианта.
    """
    if isinstance(npz_paths, (str, Path)):
        npz_paths = [npz_paths]

    devices: dict = {}
    for npz in npz_paths:
        label = _npz_label(npz)
        for key, entry in _collect_one(npz, n_vbs, vds_fracs,
                                       max_lengths, stride).items():
            dev = devices.get(key)
            if dev is None:
                dev = devices[key] = {"kind": entry["kind"],
                                      "variants": {}, "order": []}
            if label not in dev["variants"]:
                dev["order"].append(label)
            dev["variants"][label] = entry
    return {"devices": devices, "order": list(devices)}


# ---------------------------------------------------------------------------
# Программный поиск точки (для notebook / скриптов)
# ---------------------------------------------------------------------------

def solve_point(npz_path, device: str, length: float | None = None,
                vds: float | None = None, vbs: float = 0.0,
                gmid: float | None = None, vgs: float | None = None,
                vov: float | None = None, idw: float | None = None,
                id_target: float | None = None,
                w_target: float | None = None) -> dict:
    """Найти рабочую точку по одному заданному параметру.

    Драйвер выбирается по тому, что задано: gmid > vgs > vov > idw.
    Если задан id_target (или w_target) — считаются W (или ID).
    """
    from gmid_lut import _devices_for
    from mosplot.plot import load_lookup_table

    lt = load_lookup_table(str(npz_path))
    dev = next((d for d in _devices_for(lt) if d["key"] == device), None)
    if dev is None:
        raise ValueError(f"Неизвестное устройство {device!r}")

    sign = 1.0 if dev["kind"] == "nmos" else -1.0
    vdd = abs(dev["vdd"])
    length = float(np.median(dev["lengths"])) if length is None else float(length)
    vds = sign * 0.5 * vdd if vds is None else sign * abs(vds)

    have_ft = "cgg" in set(lt.get("parameter_names", []))
    rec, _peak = _curve(lt, dev, vds, vbs, length, 1, have_ft)
    arr = {k: np.array([np.nan if x is None else x for x in v])
           for k, v in rec.items() if isinstance(v, list)}
    peak = rec["peak"]

    if gmid is not None:
        xs, val, lo = arr["gmid"], gmid, peak
    elif vgs is not None:
        xs, val, lo = arr["vgs"], abs(vgs), 0
    elif vov is not None:
        xs, val, lo = arr["vov"], vov, 0
    elif idw is not None:
        xs, val, lo = arr["idw"], idw, 0
    else:
        raise ValueError("задайте один из: gmid / vgs / vov / idw")

    seg = xs[lo:]
    if xs[lo] > xs[-1]:        # убывающая (gm/ID)
        i = int(np.argmin(np.abs(seg - val)))
    else:
        i = int(np.argmin(np.abs(seg - val)))
    idx = lo + i
    point = {k: float(arr[k][idx]) for k in arr if not np.isnan(arr[k][idx])}
    point["L"] = length
    point["vds"] = abs(vds)
    point["vbs"] = vbs
    point["W"] = None
    point["ID"] = point.get("id")
    if id_target:
        point["W"] = abs(id_target / point["idw"])
        point["ID"] = id_target
    elif w_target:
        point["ID"] = abs(w_target * point["idw"])
    return point


# ---------------------------------------------------------------------------
# HTML/JS
# ---------------------------------------------------------------------------

def _plotly_js() -> str:
    try:
        from plotly.offline import get_plotlyjs
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "Не установлен plotly. Установите: "
            ".venv/bin/pip install plotly") from exc
    return get_plotlyjs()


_HTML = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>gm/ID dashboard — __TITLE__</title>
<script>__PLOTLY__</script>
<style>
  :root { --bd:#d9dee3; --bg:#f7f8fa; }
  * { box-sizing: border-box; }
  body { margin:0; font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;
         color:#1c2733; background:#fff; }
  header { padding:14px 20px; border-bottom:1px solid var(--bd); background:var(--bg); }
  header h1 { margin:0 0 2px; font-size:18px; }
  header .sub { color:#5a6b7b; font-size:13px; }
  .controls { display:flex; gap:18px; flex-wrap:wrap; align-items:flex-end;
              padding:12px 20px; border-bottom:1px solid var(--bd); background:#fff; }
  .controls label { display:flex; flex-direction:column; font-size:12px; color:#5a6b7b; gap:3px; }
  select,input[type=number],input[type=text] { padding:5px 7px; border:1px solid var(--bd);
              border-radius:6px; font-size:13px; background:#fff; color:#1c2733; }
  .controls label.chk { flex-direction:row; align-items:center; gap:6px;
              font-size:13px; color:#1c2733; cursor:pointer; }
  .controls label.chk input { margin:0; }
  .calc { margin:12px 20px; padding:12px 14px; border:1px solid var(--bd);
          border-radius:10px; background:var(--bg); }
  .calc h2 { margin:0 0 8px; font-size:14px; }
  .calc .row { display:flex; gap:14px; flex-wrap:wrap; align-items:flex-end; }
  .calc label { display:flex; flex-direction:column; font-size:12px; color:#5a6b7b; gap:3px; }
  button { padding:7px 14px; border:1px solid #3b6ea5; background:#3b6ea5; color:#fff;
           border-radius:6px; font-size:13px; cursor:pointer; }
  button:hover { background:#2f5c8c; }
  button.ghost { background:#fff; color:#3b6ea5; }
  #calcOut { margin:10px 0 0; padding:10px; background:#fff; border:1px solid var(--bd);
             border-radius:8px; font:12.5px/1.5 ui-monospace,Menlo,Consolas,monospace;
             white-space:pre-wrap; min-height:20px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(560px,1fr));
          gap:8px; padding:8px 12px 40px; }
  .fig { width:100%; height:430px; border:1px solid var(--bd); border-radius:10px; }
  .hint { color:#8496a6; font-size:12px; }
</style>
</head>
<body>
<header>
  <h1>gm/ID — интерактивный дашборд</h1>
  <div class="sub">LUT: <b>__TITLE__</b> &nbsp;·&nbsp; наведите курсор на кривую (значения по осям и все параметры точки);
    колесо — зум; клик по легенде — вкл/выкл длину.</div>
</header>

<div class="controls">
  <label>Устройство<select id="dev"></select></label>
  <label>Прогон / угол<select id="var"></select></label>
  <label>V<sub>DS</sub><select id="vds"></select></label>
  <label>V<sub>BS</sub><select id="vbs"></select></label>
  <label class="chk"><input type="checkbox" id="logVds"> лог. шкала ID(VDS)</label>
  <label class="chk"><input type="checkbox" id="logVgs" checked> лог. шкала ID(VGS)</label>
  <span class="hint" id="ctx"></span>
</div>

<div class="calc">
  <h2>Калькулятор рабочей точки</h2>
  <div class="row">
    <label>Задаю<select id="drv">
      <option value="gmid">gm/ID</option>
      <option value="vgs">|VGS|</option>
      <option value="vov">Vov</option>
      <option value="idw">ID/W</option>
    </select></label>
    <label>Значение<input id="val" type="number" step="any" value="12"></label>
    <label>Длина<select id="len"></select></label>
    <label>Целевой ID, А<input id="cid" type="number" step="any" placeholder="напр. 10e-6"></label>
    <label>или W, м<input id="cw" type="number" step="any" placeholder="напр. 20e-6"></label>
    <button id="find">Найти точку</button>
    <button id="clear" class="ghost">Сбросить</button>
  </div>
  <pre id="calcOut">Задайте параметр и нажмите «Найти точку» — результат появится здесь и отметится на графиках.</pre>
</div>

<div class="grid">
  <div id="fig_idw" class="fig"></div>
  <div id="fig_ft" class="fig"></div>
  <div id="fig_gmro" class="fig"></div>
  <div id="fig_gvov" class="fig"></div>
  <div id="fig_idvgs" class="fig"></div>
  <div id="fig_vvv" class="fig"></div>
  <div id="fig_idvds" class="fig"></div>
</div>

<script>__APP__</script>
</body>
</html>
"""


_APP_JS = r"""
const DATA = __DATA__;
const DEVS = (DATA.order && DATA.order.length) ? DATA.order : Object.keys(DATA.devices);
const QS = ['vgs','vth','vdsat','vov','vstar','gmid','idw','id','gm','gds','gain','ft','cgg'];
const CFG = {responsive:true, displaylogo:false, scrollZoom:true,
             modeBarButtonsToRemove:['lasso2d','select2d']};
const state = {dev:DEVS[0], var:null, vi:0, bi:0, point:null, logVds:false, logVgs:true};

const FIGS = [
  {id:'fig_idw',   x:'gmid', y:'idw',  xl:'g_m/I_D (1/V)', yl:'I_D/W (A/m)', ylog:true},
  {id:'fig_ft',    x:'gmid', y:'ft',   xl:'g_m/I_D (1/V)', yl:'f_T (Hz)',    ylog:true, ft:true},
  {id:'fig_gmro',  x:'gmid', y:'gain', xl:'g_m/I_D (1/V)', yl:'g_m·r_o = g_m/g_ds', ylog:true},
  {id:'fig_gvov',  x:'vov',  y:'gmid', xl:'V_OV = |V_GS| − |V_th| (V)', yl:'g_m/I_D (1/V)'},
  {id:'fig_idvgs', x:'vgs',  y:'id',   xl:'|V_GS| (V)', yl:'I_D (A)',      ylog:true},
];

function devData(){ return DATA.devices[state.dev]; }
function vd(){ return devData().variants[state.var]; }
function series(){ return vd().series[state.vi+'_'+state.bi]; }
function fmtL(L){ let s=(L*1e6).toPrecision(3); return s.replace(/\.?0+$/,'')+' µm'; }
function fmtEng(x){
  if(x===null||x===undefined||!isFinite(x)) return '—';
  const a=Math.abs(x);
  const U=[[1e9,'G'],[1e6,'M'],[1e3,'k'],[1,''],[1e-3,'m'],[1e-6,'µ'],[1e-9,'n'],[1e-12,'p']];
  for(const [s,p] of U){ if(a>=s) return (x/s).toPrecision(4).replace(/\.?0+$/,'')+' '+p; }
  return x.toPrecision(4);
}
function cd(rec){
  const ft = rec.ft && rec.ft.length;
  return rec.vgs.map((_,i)=>[rec.vgs[i],rec.gmid[i],rec.idw[i],rec.id[i],
    rec.vth[i],rec.vdsat[i],rec.vstar[i], ft?rec.ft[i]:null, rec.gain[i], rec.vov[i]]);
}
function hoverTpl(hasFt){
  let s='<b>%{fullData.name}</b><br>'
    +'gm/ID = %{customdata[1]:.4g} 1/V<br>'
    +'ID/W = %{customdata[2]:.4g} A/m<br>'
    +'|VGS| = %{customdata[0]:.3f} V<br>'
    +'ID = %{customdata[3]:.4g} A<br>'
    +'Vth = %{customdata[4]:.3f} V<br>'
    +'Vdsat = %{customdata[5]:.3f} V<br>'
    +'V* = %{customdata[6]:.3f} V<br>';
  if(hasFt) s+='fT = %{customdata[7]:.4g} Hz<br>';
  s+='gm·ro = %{customdata[8]:.4g}<extra></extra>';
  return s;
}
function layout(spec, title){
  return {
    title:{text:title||'', font:{size:13}},
    xaxis:{title:{text:spec.xl}, showspikes:true, spikemode:'across',
           spikesnap:'cursor', spikedash:'dot', spikethickness:1,
           gridcolor:'#eef1f4', zeroline:false},
    yaxis:{title:{text:spec.yl}, type: spec.ylog?'log':'linear',
           showspikes:true, spikemode:'across', spikesnap:'cursor',
           spikedash:'dot', gridcolor:'#eef4f7'},
    hovermode:'x unified', hoverlabel:{namelength:-1},
    legend:{orientation:'h', y:-0.22, font:{size:11}}, 
    margin:{t:34,r:14,b:64,l:64},
    paper_bgcolor:'#fff', plot_bgcolor:'#fff'
  };
}
function markerTrace(spec){
  if(!state.point) return null;
  const p=state.point;
  if(p[spec.x]===undefined || p[spec.y]===undefined) return null;
  return {type:'scatter', mode:'markers', name:'точка',
    x:[p[spec.x]], y:[p[spec.y]],
    marker:{size:13, color:'#d62728', symbol:'x-thin', line:{width:2}},
    hovertemplate:'найденная точка<extra></extra>'};
}
function renderFig(spec){
  const dev=vd(), ser=series(), traces=[];
  Object.keys(ser).forEach(li=>{
    const rec=ser[li]; const hasFt=rec.ft && rec.ft.length;
    if(spec.ft && !hasFt) return;
    traces.push({type:'scatter', mode:'lines', name:'L='+fmtL(dev.lengths[li]),
      x:rec[spec.x], y:rec[spec.y], customdata:cd(rec),
      hovertemplate:hoverTpl(hasFt)});
  });
  const m=markerTrace(spec); if(m) traces.push(m);
  const sp=(spec.id==='fig_idvgs')?Object.assign({}, spec, {ylog:!!state.logVgs}):spec;
  Plotly.react(spec.id, traces, layout(sp), CFG);
}
function renderVVV(){
  const dev=vd(), ser=series(); const keys=Object.keys(ser);
  const li=keys[Math.floor(keys.length/2)]; const rec=ser[li];
  const mk=(y,n)=>({type:'scatter',mode:'lines',name:n,x:rec.vgs,y:rec[y],
    customdata:cd(rec),hovertemplate:'<b>'+n+'</b> = %{y:.3f} V<extra></extra>'});
  const traces=[mk('vdsat','V_DS,sat'),mk('vov','V_OV'),mk('vstar','V*')];
  const layout_={...layout({xl:'|V_GS| (V)', yl:'Voltage (V)'}, 'V_dsat / V_OV / V*   (L='+fmtL(dev.lengths[li])+')')};
  Plotly.react('fig_vvv', traces, layout_, CFG);
}
function renderIV(){
  const dev=vd();
  const traces=dev.iv.map(c=>({type:'scatter',mode:'lines',
    name:'VGS='+c.vgs.toFixed(2)+' V', x:c.vds, y:c.id,
    hovertemplate:'<b>VGS='+c.vgs.toFixed(2)+' V</b><br>VDS=%{x:.3f} V<br>ID=%{y:.4g} A<extra></extra>'}));
  const spec={xl:'|V_DS| (V)', yl:'I_D (A)', ylog:!!state.logVds};
  Plotly.react('fig_idvds', traces,
    layout(spec, 'ID(VDS), L='+fmtL(dev.lengths[Math.floor(dev.lengths.length/2)])), CFG);
}
function renderAll(){ FIGS.forEach(renderFig); renderVVV(); renderIV(); }

/* ---- controls ---- */
function fillDev(){
  const sel=document.getElementById('dev');
  sel.innerHTML=DEVS.map(k=>'<option value="'+k+'">'+k+' ('+DATA.devices[k].kind.toUpperCase()+')</option>').join('');
  sel.value=state.dev;
}
function fillVar(){
  const d=devData(), sel=document.getElementById('var');
  const order=d.order||Object.keys(d.variants);
  if(!state.var || order.indexOf(state.var)<0) state.var=order[0];
  sel.innerHTML=order.map(v=>'<option value="'+v+'">'+v+'</option>').join('');
  sel.value=state.var;
}
function updateCtx(){
  const el=document.getElementById('ctx'); if(!el) return;
  const d=devData(), e=vd();
  el.textContent = state.dev+' ('+d.kind.toUpperCase()+') · '+state.var
    +' · VDD='+e.vdd+' V';
}
function fillVds(){
  const d=vd(), sel=document.getElementById('vds');
  sel.innerHTML=d.vds_values.map((v,i)=>'<option value="'+i+'">'+
    (100*d.vds_fracs[i]).toFixed(0)+'% VDD = '+v.toFixed(2)+' V</option>').join('');
  sel.value=state.vi;
}
function fillVbs(){
  const d=vd(), sel=document.getElementById('vbs');
  sel.innerHTML=d.vbs_values.map((v,i)=>'<option value="'+i+'">'+
    (v===0?'0 V':v.toFixed(2)+' V')+'</option>').join('');
  sel.value=state.bi;
}
function fillLen(){
  const d=vd(), sel=document.getElementById('len');
  sel.innerHTML='<option value="auto">авто (все длины)</option>'+
    d.lengths.map((L,i)=>'<option value="'+i+'">L='+fmtL(L)+'</option>').join('');
}
function refresh(){ fillVar(); fillVds(); fillVbs(); fillLen(); updateCtx(); }
function bind(){
  document.getElementById('dev').onchange=e=>{
    state.dev=e.target.value; state.var=null; state.vi=0; state.bi=0; state.point=null;
    refresh(); renderAll(); clearOut();
  };
  document.getElementById('var').onchange=e=>{
    state.var=e.target.value; state.vi=0; state.bi=0; state.point=null;
    fillVds(); fillVbs(); fillLen(); updateCtx(); renderAll(); clearOut();
  };
  document.getElementById('vds').onchange=e=>{ state.vi=+e.target.value; renderAll(); };
  document.getElementById('vbs').onchange=e=>{ state.bi=+e.target.value; renderAll(); };
  document.getElementById('logVds').onchange=e=>{ state.logVds=e.target.checked; renderIV(); };
  document.getElementById('logVgs').onchange=e=>{
    state.logVgs=e.target.checked;
    renderFig(FIGS.filter(f=>f.id==='fig_idvgs')[0]);
  };
  document.getElementById('find').onclick=()=>{ doFind(); };
  document.getElementById('clear').onclick=()=>{ state.point=null; renderAll(); clearOut(); };
}

/* ---- search / calculator ---- */
function bracket(arr, val, lo, hi){
  for(let i=lo;i<hi;i++){
    const a=arr[i], b=arr[i+1];
    if(a===undefined||b===undefined) continue;
    if((a-val)*(b-val)<=0 && a!==b) return {i:i, t:(val-a)/(b-a)};
  }
  let bi=lo, bd=1e300;
  for(let i=lo;i<=hi;i++){ if(arr[i]===undefined) continue;
    const d=Math.abs(arr[i]-val); if(d<bd){bd=d; bi=i;} }
  return {i:Math.min(bi,hi-1), t:0};
}
function interpRec(rec, i, t){
  const o={};
  QS.forEach(q=>{ const a=rec[q]; if(!a) return;
    const av=a[i], bv=(a[i+1]!==undefined)?a[i+1]:av;
    if(av!==undefined && av!==null) o[q]=av+(bv-av)*t; });
  return o;
}
function findInSeries(ser, li, drv, val){
  const rec=ser[li]; let lo=0, hi=rec.gmid.length-1, arr;
  if(drv==='gmid'){ lo=rec.peak; arr=rec.gmid; }
  else if(drv==='vgs'){ arr=rec.vgs; }
  else if(drv==='vov'){ arr=rec.vov; }
  else { arr=rec.idw; }
  if(hi<=lo) return null;
  const br=bracket(arr, val, lo, hi);
  const o=interpRec(rec, br.i, br.t);
  const peakVal = (drv==='gmid')? (val-rec.gmid[br.i]) : 0;
  return {o:o, err:Math.abs(peakVal) + (drv==='gmid'?0:0), li:li};
}
function doFind(){
  const drv=document.getElementById('drv').value;
  const val=parseFloat(document.getElementById('val').value);
  const lenSel=document.getElementById('len').value;
  const cid=parseFloat(document.getElementById('cid').value);
  const cw=parseFloat(document.getElementById('cw').value);
  if(!isFinite(val)){ clearOut('Введите числовое значение.'); return; }
  const ser=series(), dev=vd();
  let best=null;
  const keys=(lenSel==='auto')?Object.keys(ser):[lenSel];
  keys.forEach(li=>{
    if(!ser[li]) return;
    const cand=findInSeries(ser, li, drv, val);
    if(!cand) return;
    // ошибка = невязка по выбранному драйверу
    const rec=ser[li];
    const target=(drv==='gmid'||drv==='vgs'||drv==='vov')?( drv==='vgs'?Math.abs(val):val ):(val);
    const got = drv==='gmid'?cand.o.gmid : drv==='vgs'?cand.o.vgs : drv==='vov'?cand.o.vov : cand.o.idw;
    cand.err=Math.abs(got-target); cand.li=li;
    if(!best || cand.err<best.err) best=cand;
  });
  if(!best){ clearOut('Не найдено (проверьте диапазон значений).'); return; }
  const o=best.o, L=dev.lengths[best.li];
  const idw=o.idw;
  let ID=o.id, W=null;
  if(isFinite(cid)&&cid>0){ W=Math.abs(cid/idw); ID=cid; }
  else if(isFinite(cw)&&cw>0){ ID=Math.abs(cw*idw); W=cw; }
  state.point=Object.assign({}, o, {id:ID});
  renderAll();
  clearOut();
  out('Устройство : '+state.dev+' ('+vd().kind.toUpperCase()+')   вариант: '+state.var);
  out('L          : '+fmtL(L)+'   VDS = '+fmtEng(Math.abs(vd().vds_values[state.vi]))+'V'
      +'   VBS = '+fmtEng(vd().vbs_values[state.bi])+'V');
  out('Драйвер    : '+drv+' = '+val);
  out('---');
  out('gm/ID      : '+o.gmid.toFixed(3)+' 1/V');
  out('|VGS|      : '+o.vgs.toFixed(4)+' V');
  out('Vov        : '+o.vov.toFixed(4)+' V');
  out('Vth        : '+o.vth.toFixed(4)+' V');
  out('ID/W       : '+fmtEng(o.idw)+'A/m');
  if(W!==null) out('W          : '+fmtEng(W)+'m   (под ID='+fmtEng(ID)+'A)');
  if(ID!==null) out('ID         : '+fmtEng(ID)+'A'+(W===null?'  (эталон W)':''));
  out('gm         : '+fmtEng(o.gm)+'S');
  out('gds        : '+fmtEng(o.gds)+'S');
  out('gm*ro      : '+o.gain.toFixed(2)+'  ('+(20*Math.log10(o.gain)).toFixed(1)+' dB)');
  out('Vdsat      : '+o.vdsat.toFixed(4)+' V');
  out('V*         : '+o.vstar.toFixed(4)+' V');
  if(o.ft!==undefined && o.ft!==null) out('fT         : '+fmtEng(o.ft)+'Hz');
}
function out(s){ const el=document.getElementById('calcOut'); el.textContent+=s+'\n'; }
function clearOut(s){ document.getElementById('calcOut').textContent = s? s : ''; }

/* ---- init ---- */
fillDev(); refresh(); bind(); renderAll();
window.addEventListener('resize', ()=>FIGS.forEach(f=>Plotly.Plots.resize(document.getElementById(f.id))));
"""


def _gather_npz(sources, recursive: bool = True) -> list[Path]:
    """Собрать .npz из файлов/каталогов (каталоги — рекурсивно по умолчанию)."""
    out: list[Path] = []
    for src in sources:
        p = Path(src)
        if p.is_dir():
            it = p.rglob("*.npz") if recursive else p.glob("*.npz")
            out.extend(sorted(it))
        elif p.suffix == ".npz" and p.exists():
            out.append(p)
    seen: set = set()
    res: list[Path] = []
    for f in out:
        # не лезем в служебные каталоги графиков/отчётов/дашбордов
        if any(part.startswith(("plots_", "report_", "dash_"))
               for part in f.parts[:-1]):
            continue
        key = f.resolve()
        if key in seen:
            continue
        seen.add(key)
        res.append(f)
    return res


def build_dashboard(sources, out_dir=None, out_path=None, recursive: bool = True,
                    **collect_kwargs) -> Path:
    """Собрать интерактивный HTML-дашборд из одного/нескольких .npz или каталогов.

    Все найденные таблицы объединяются: одинаковые имена устройств становятся
    «вариантами» (углами/питаниями) одного устройства в выпадающем списке.
    """
    if isinstance(sources, (str, Path)):
        sources = [sources]
    npz_files = _gather_npz(sources, recursive=recursive)
    print("=" * 72)
    print(f"ИНТЕРАКТИВНЫЙ ДАШБОРД (Plotly) — таблиц: {len(npz_files)}")
    print("=" * 72)
    for f in npz_files:
        print(f"  + {f}")
    if not npz_files:
        print("  ! не найдено ни одного .npz — дашборд пропущен")
        return Path(".")

    data = collect(npz_files, **collect_kwargs)
    if not data["devices"]:
        print("  ! в таблицах нет известных устройств — дашборд пропущен")
        return npz_files[0]

    if out_path:
        html_path = Path(out_path)
    else:
        if out_dir is not None:
            base = Path(out_dir)
        else:
            from os.path import commonpath
            dirs = [Path(s) for s in sources if Path(s).is_dir()]
            if len(sources) == 1 and len(dirs) == 1:
                base = dirs[0]            # подан один каталог — кладём рядом с ним
            else:
                try:
                    base = Path(commonpath([str(f.parent) for f in npz_files]))
                except ValueError:
                    base = npz_files[0].parent
        html_path = base / f"dash_{base.name}" / "index.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)

    title = ", ".join(_npz_label(f) for f in npz_files)
    # прореживание None -> null допустимо; json компактен
    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    app = _APP_JS.replace("__DATA__", data_json)
    html = (_HTML
            .replace("__PLOTLY__", _plotly_js())
            .replace("__TITLE__", title)
            .replace("__APP__", app))
    html_path.write_text(html, encoding="utf-8")

    size_mb = html_path.stat().st_size / 1e6
    devs = [f"{k}×{len(data['devices'][k]['variants'])}" for k in data["order"]]
    print(f"  устройства : {', '.join(devs)}   (имя×число_вариантов)")
    print(f"  HTML       : {html_path}  ({size_mb:.1f} MB)")
    print("  откройте двойным кликом в браузере (интернет не нужен)")
    return html_path


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(
        description="Интерактивный дашборд gm/ID (Plotly) из .npz")
    ap.add_argument("sources", nargs="+",
                    help=".npz-файлы и/или каталоги с ними")
    ap.add_argument("-o", "--out", default=None, help="путь к index.html")
    ap.add_argument("--out-dir", default=None,
                    help="каталог для <out-dir>/dash_<name>/index.html")
    ap.add_argument("--no-recursive", action="store_true",
                    help="не искать .npz во вложенных подкаталогах")
    args = ap.parse_args()
    build_dashboard(args.sources, out_dir=args.out_dir, out_path=args.out,
                    recursive=not args.no_recursive)
