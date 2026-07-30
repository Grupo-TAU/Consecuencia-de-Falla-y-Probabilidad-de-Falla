"""
App Streamlit — Consecuencia y Probabilidad de Falla (CdeF).

Tres pestañas:
  1. Preparación de datos  — corre los pasos que ESCRIBEN la capa real
     (asignar registros, cota zampeado, cotas/pendiente), vía
     cf_pf_core.preparacion.
  2. Cálculo de CdeF       — LEE la fuente (nunca la modifica) y escribe los
     resultados en una capa aparte 'DatosConsecuenciaDeFalla'. Flujo completo
     o cálculo individual.
  3. Visualización         — mapa por CdeF + distribución + tabla.

Correr con:  streamlit run app/streamlit_app.py
"""
import os
import sys

import geopandas as gpd
import matplotlib.pyplot as plt
import streamlit as st

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from cf_pf_core import flujo, gpkg_io, preparacion, proyecto, visualizador  # noqa: E402
from cf_pf_core.calculos import criticidad as _crit  # noqa: E402

st.set_page_config(page_title="Consecuencia de Falla", layout="wide")

ROLES_AUX = ["vias", "calles", "sitios", "cursos", "construcciones",
             "asentamientos", "padrones", "peatonales", "verde"]


@st.cache_data(show_spinner=False)
def _cargar(path, layer, mtime):
    return gpd.read_file(path, layer=layer) if layer else gpd.read_file(path)


def cargar_gdf(path, layer=None):
    if not path or not os.path.isfile(path):
        return None
    try:
        return _cargar(path, layer, os.path.getmtime(path))
    except Exception as e:  # noqa: BLE001
        st.warning(f"No se pudo leer {os.path.basename(path)}: {e}")
        return None


# ─────────────────────────── Barra lateral: proyecto ────────────────────────
st.sidebar.header("Proyecto")
carpeta = st.sidebar.text_input("Carpeta del proyecto", value="",
                                help="La app busca las capas por nombre dentro de esta carpeta.")

detectadas = {}
if carpeta and os.path.isdir(carpeta):
    detectadas = proyecto.detectar_capas(carpeta)
    st.sidebar.success(f"{len(detectadas)} capas detectadas")
elif carpeta:
    st.sidebar.error("No existe esa carpeta.")

col_path = st.sidebar.text_input("Capa Colectores", value=detectadas.get("colectores", ""))
reg_path = st.sidebar.text_input("Capa Registros", value=detectadas.get("registros", ""))

with st.sidebar.expander("Capas auxiliares", expanded=bool(detectadas)):
    # Sin key= explicito: asi el value= detectado se aplica al cambiar de carpeta
    # (con key, Streamlit conserva el estado previo e ignora la deteccion).
    aux_paths = {rol: st.text_input(rol.capitalize(), value=detectadas.get(rol, ""))
                 for rol in ROLES_AUX}

colectores = cargar_gdf(col_path)
clave = None
if colectores is not None:
    opciones_clave = [c for c in colectores.columns if c != colectores.geometry.name]
    idx = next((i for i, c in enumerate(opciones_clave) if c.lower() in ("elemred", "id")), 0)
    clave = st.sidebar.selectbox("Columna clave (join)", opciones_clave, index=idx)
    st.sidebar.caption(f"Colectores: {len(colectores)} · CRS {colectores.crs}")

# ──────────────────────────────── Pestañas ──────────────────────────────────
st.title("Consecuencia y Probabilidad de Falla")
tab_prep, tab_calc, tab_vis = st.tabs(
    ["🛠️ Preparación de datos", "🧮 Cálculo de CdeF", "🗺️ Visualización"]
)

# ── Pestaña 1: Preparación (escribe capas reales) ────────────────────────────
with tab_prep:
    st.subheader("Preparación de datos")
    st.warning("⚠️ Estos pasos **escriben la capa real** (Colectores/Registros). "
               "No generan una capa aparte. Asegurate de tener respaldo.")
    st.caption("Corré los pasos en orden. Ninguno pisa datos ya cargados: sólo "
               "completa lo que está vacío, así que se pueden repetir sin riesgo.")

    if not col_path:
        st.info("Indicá la capa de Colectores en la barra lateral.")
    else:
        st.markdown("### Configuración")
        st.caption("Cada campo viene con su nombre por defecto — editalo si en tu capa "
                   "se llama distinto.")
        config_prep = {}

        with st.expander("Columnas comunes", expanded=False):
            for clave_cfg, etiqueta, default in preparacion.CAMPOS_COMUNES:
                config_prep[clave_cfg] = st.text_input(
                    etiqueta, value=default, key=f"prep_cfg_{clave_cfg}")

        for key_paso, campos in preparacion.CONFIG_CAMPOS.items():
            with st.expander(preparacion.ETIQUETAS_PASO[key_paso], expanded=False):
                for clave_cfg, etiqueta, default in campos:
                    if isinstance(default, (int, float)) and not isinstance(default, bool):
                        config_prep[clave_cfg] = st.number_input(
                            etiqueta, value=float(default), step=0.1,
                            key=f"prep_cfg_{clave_cfg}")
                    else:
                        config_prep[clave_cfg] = st.text_input(
                            etiqueta, value=default, key=f"prep_cfg_{clave_cfg}")

        st.markdown("### Pasos")
        for key_paso, label, _fn, _campos in preparacion.PASOS:
            c1, c2 = st.columns([3, 1])
            c1.write(f"**{label}**")
            if not c2.button("Correr", key=f"prep_{key_paso}"):
                continue

            mensajes = []
            with st.spinner(f"Ejecutando {label}…"):
                try:
                    preparacion.correr(
                        key_paso, gpkg_col=col_path, gpkg_reg=reg_path or None,
                        config=config_prep,
                        log=lambda m, n="info": mensajes.append((n, m)))
                    ok = True
                except preparacion.PreparacionError as e:
                    mensajes.append(("error", str(e)))
                    ok = False
                except Exception as e:  # noqa: BLE001
                    mensajes.append(("error", f"{type(e).__name__}: {e}"))
                    ok = False

            if ok:
                # El paso modifico la capa fuente: invalidar lo cacheado.
                _cargar.clear()
            (st.success if ok else st.error)(
                f"{label} — {'listo' if ok else 'no se pudo completar'}")
            for nivel, msg in mensajes:
                {"error": st.error, "warn": st.warning}.get(nivel, st.write)(msg)

# ── Pestaña 2: Cálculo de CdeF (lee fuente, escribe capa aparte) ─────────────
with tab_calc:
    st.subheader("Cálculo de Consecuencia de Falla")
    st.caption("Lee la capa de Colectores (nunca la modifica) y escribe los resultados "
               "en una capa aparte **DatosConsecuenciaDeFalla**.")

    if colectores is None:
        st.info("Indicá la capa de Colectores en la barra lateral para empezar.")
    else:
        registros = cargar_gdf(reg_path)
        aux = {rol: cargar_gdf(p) for rol, p in aux_paths.items() if p}

        st.markdown("### Configuración")
        st.caption("Cada campo viene con su nombre por defecto — editalo si en tu capa se llama distinto.")
        config = {}

        # Campos editables por sección (columnas + rangos/mapeos de cada cálculo).
        for sec_key, campos in flujo.CONFIG_CAMPOS.items():
            titulo = flujo.ETIQUETAS_SECCION.get(sec_key, sec_key)
            with st.expander(f"⚙️ {titulo}"):
                for ckey, label, default in campos:
                    if isinstance(default, (int, float)) and not isinstance(default, bool):
                        config[ckey] = st.number_input(label, value=float(default), step=0.5,
                                                       key=f"cfg_{ckey}")
                    else:
                        config[ckey] = st.text_input(label, value=default, key=f"cfg_{ckey}")

        # Criticidad: pesos y parámetros por grupo, totalmente configurables.
        with st.expander("⚖️ Criticidad — pesos y parámetros"):
            grupos, total_peso = {}, 0.0
            for gname, gdef in _crit.GRUPOS_DEFAULT.items():
                c1, c2 = st.columns([1, 3])
                peso = c1.number_input(f"Peso · {gname}", min_value=0.0, max_value=1.0,
                                       value=float(gdef["peso"]), step=0.05, key=f"peso_{gname}")
                params = c2.multiselect(f"Parámetros · {gname}", options=_crit.PARAMS_DISPONIBLES,
                                        default=gdef["params"], key=f"params_{gname}")
                if params:
                    grupos[gname] = {"peso": peso, "params": params}
                total_peso += peso
            config["criticidad_grupos"] = grupos
            if abs(total_peso - 1.0) > 1e-6:
                st.warning(f"Los pesos suman {total_peso:.2f} (no 1.0): la criticidad no quedará en escala 1–6.")

        # Guardar config para reusar en el visualizador (Pestaña 3).
        st.session_state["config"] = config

        out_default = os.path.join(RAIZ, "AnalisisDeDatos", "salidas",
                                   (os.path.splitext(os.path.basename(col_path))[0] if col_path else "proyecto")
                                   + "_ConsecuenciaDeFalla.gpkg")
        out_path = st.text_input("GeoPackage de salida (local)", value=out_default)

        st.markdown("**Flujo completo**")
        if st.button("▶ Correr todo el flujo", type="primary"):
            registro_log = []
            def _log(msg, nivel):
                registro_log.append((nivel, msg))
            with st.spinner("Corriendo flujo…"):
                res = flujo.correr(colectores, registros=registros, aux=aux,
                                   config=config, clave=clave, log=_log)
                gpkg_io.escribir_resultados(res, out_path, clave=clave, reemplazar=True)
            for nivel, msg in registro_log:
                {"ok": st.success, "warn": st.warning, "error": st.error}.get(nivel, st.write)(msg)
            st.session_state["salida_path"] = out_path
            st.success(f"Listo → {out_path}")

        st.markdown("**Cálculo individual**")
        cols_btn = st.columns(3)
        for i, (key, label, requiere, _fn) in enumerate(flujo.PASOS):
            if cols_btn[i % 3].button(label, key=f"calc_{key}"):
                registro_log = []
                res = flujo.correr(colectores, registros=registros, aux=aux, config=config,
                                   clave=clave, solo=[key],
                                   log=lambda m, n: registro_log.append((n, m)))
                gpkg_io.escribir_resultados(res, out_path, clave=clave)
                for nivel, msg in registro_log:
                    {"ok": st.success, "warn": st.warning, "error": st.error}.get(nivel, st.write)(msg)
                st.session_state["salida_path"] = out_path

# ── Pestaña 3: Visualización ─────────────────────────────────────────────────
with tab_vis:
    st.subheader("Visualización")
    vis_path = st.text_input("GeoPackage de resultados",
                             value=st.session_state.get("salida_path", ""))
    if vis_path and os.path.isfile(vis_path):
        gv = cargar_gdf(vis_path, gpkg_io.LAYER_SALIDA_DEFAULT)
        if gv is not None:
            campos = [c for c in gv.columns if c != gv.geometry.name
                      and str(gv[c].dtype) != "object"]
            pref = next((c for c in ("Riesgo", "criticidad", "CF_Diametro") if c in campos), campos[0] if campos else None)
            campo = st.selectbox("Colorear por", campos,
                                 index=campos.index(pref) if pref in campos else 0)
            c1, c2 = st.columns([2, 1])
            with c1:
                fig, ax = plt.subplots(figsize=(9, 9))
                gv.plot(column=campo, cmap="RdYlGn_r", linewidth=0.9, legend=True, ax=ax)
                ax.set_axis_off()
                ax.set_title(f"Colectores por {campo}")
                st.pyplot(fig)
            with c2:
                st.markdown("**Distribución**")
                st.bar_chart(gv[campo].value_counts().sort_index())
                st.metric("Tramos", len(gv))

            st.divider()
            st.markdown("### Visualizador interactivo (Bokeh)")
            st.caption("Genera un HTML autónomo y compartible: mapa + sliders de peso "
                       "que recalculan la criticidad en vivo.")
            if st.button("🌐 Generar visualizador HTML"):
                html_path = os.path.splitext(vis_path)[0] + "_visualizador.html"
                try:
                    grupos = st.session_state.get("config", {}).get("criticidad_grupos") or None
                    visualizador.generar_html(gv, html_path, grupos=grupos,
                                              titulo="Consecuencia de Falla")
                    st.success(f"Generado: {html_path}")
                    with open(html_path, "rb") as fh:
                        st.download_button("⬇ Descargar HTML", fh.read(),
                                           file_name=os.path.basename(html_path),
                                           mime="text/html")
                except Exception as e:  # noqa: BLE001
                    st.exception(e)
    else:
        st.info("Corré un cálculo en la pestaña anterior, o indicá un GeoPackage de resultados.")
