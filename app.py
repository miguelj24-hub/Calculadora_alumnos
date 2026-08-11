from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


st.set_page_config(page_title="Optimizador Precio–Beca", page_icon="🎓", layout="wide")

COLUMNAS_REQUERIDAS = {
    "Programa académico",
    "Periodo Comercial",
    "Año comercial",
    "Nivel de programa",
    "Unidad de negocio",
}


@st.cache_data(show_spinner=False)
def cargar_csv(archivo):
    df = pd.read_csv(archivo, low_memory=False, encoding="utf-8-sig")
    faltantes = COLUMNAS_REQUERIDAS.difference(df.columns)
    if faltantes:
        raise ValueError("Faltan columnas: " + ", ".join(sorted(faltantes)))

    df = df.copy()
    df["Año comercial"] = pd.to_numeric(df["Año comercial"], errors="coerce")
    df = df.dropna(subset=["Año comercial", "Programa académico"])
    df["Año comercial"] = df["Año comercial"].astype(int)

    if "Id de oportunidad" in df.columns:
        respaldo = pd.Series(df.index.astype(str), index=df.index)
        df["_unidad"] = df["Id de oportunidad"].fillna(respaldo).astype(str)
    else:
        df["_unidad"] = df.index.astype(str)

    if "% de beca aprobada" in df.columns:
        df["_beca"] = pd.to_numeric(df["% de beca aprobada"], errors="coerce") / 100
    else:
        df["_beca"] = np.nan
    return df


def determinar_esquema(fila):
    programa = str(fila["Programa académico"]).upper()
    unidad = str(fila["Unidad de negocio"]).upper()
    nivel = str(fila["Nivel de programa"]).upper()
    if programa.strip() == "MÉDICO CIRUJANO":
        return "Médico Cirujano"
    if "ONLINE" in programa or "ONLINE" in unidad:
        return "Cuatrimestral / Online"
    if "MAESTR" in nivel:
        return "Maestría"
    return "Semestral"


def precio_esperado(esquema, pago_completo, precios):
    mensualidad, pagos, completo = precios[esquema]
    return (1 - pago_completo) * mensualidad * pagos + pago_completo * completo


def estimar_inscritos(q_ref, precio, beca, precio_ref, beca_ref, elasticidad, efecto_beca, capacidad):
    razon = max(precio / max(precio_ref, 1), 0.01)
    q = q_ref * razon**elasticidad * np.exp(efecto_beca * (beca - beca_ref))
    return min(max(q, 0), capacidad)


def calcular_kpis(q, precio, beca, costo_pct):
    ingreso_bruto = q * precio
    bolsa = ingreso_bruto * beca
    ingreso_neto = ingreso_bruto - bolsa
    costo = ingreso_bruto * costo_pct
    margen = ingreso_neto - costo
    return ingreso_neto, margen, bolsa


st.title("🎓 Optimizador de Precio y Beca")
st.caption("Prototipo para explorar escenarios con datos históricos y supuestos editables.")

archivo_local = Path("Datos.csv")
archivo = st.sidebar.file_uploader("Cargar Datos.csv", type=["csv"])
fuente = archivo if archivo is not None else (archivo_local if archivo_local.exists() else None)

if fuente is None:
    st.info("Carga el archivo Datos.csv para iniciar. También puedes colocarlo junto a app.py.")
    st.stop()

try:
    datos = cargar_csv(fuente)
except Exception as exc:
    st.error(f"No fue posible leer el archivo: {exc}")
    st.stop()

programas = sorted(datos["Programa académico"].dropna().unique())
if not programas:
    st.error("El archivo no contiene programas válidos.")
    st.stop()

if st.session_state.get("programa") not in programas:
    st.session_state["programa"] = programas[0]
programa = st.sidebar.selectbox("Programa", programas, key="programa")
datos_programa = datos[datos["Programa académico"] == programa].copy()
esquema = determinar_esquema(datos_programa.iloc[0])

st.sidebar.markdown("### Periodos")
anios_disponibles = [int(x) for x in sorted(datos_programa["Año comercial"].unique())]
if not anios_disponibles:
    st.error("El programa seleccionado no contiene años válidos.")
    st.stop()

if st.session_state.get("anio_ref") not in anios_disponibles:
    st.session_state["anio_ref"] = anios_disponibles[0]
anio_ref = st.sidebar.selectbox("Año de referencia", anios_disponibles, key="anio_ref")

periodos_ref = sorted(
    datos_programa.loc[
        datos_programa["Año comercial"] == anio_ref,
        "Periodo Comercial",
    ].dropna().unique()
)
if not periodos_ref:
    st.error("No existen periodos para el año seleccionado.")
    st.stop()

# La llave cambia con programa y año para que Streamlit no conserve un periodo
# perteneciente a una selección anterior.
clave_periodo = f"periodo_ref::{programa}::{anio_ref}"
if st.session_state.get(clave_periodo) not in periodos_ref:
    st.session_state[clave_periodo] = periodos_ref[0]
periodo_ref = st.sidebar.selectbox(
    "Periodo de referencia",
    periodos_ref,
    key=clave_periodo,
)

if "anio_obj" not in st.session_state or int(st.session_state["anio_obj"]) < anio_ref:
    st.session_state["anio_obj"] = max(2030, anio_ref)
anio_obj = st.sidebar.number_input(
    "Año objetivo",
    min_value=anio_ref,
    max_value=2040,
    step=1,
    key="anio_obj",
)

ref = datos_programa[
    (datos_programa["Año comercial"] == anio_ref)
    & (datos_programa["Periodo Comercial"] == periodo_ref)
]
q_ref = int(ref["_unidad"].nunique())
beca_ref = float(ref["_beca"].fillna(0).mean()) if len(ref) else 0.0

if q_ref <= 0:
    st.error("El periodo seleccionado no contiene inscritos válidos.")
    st.stop()

st.sidebar.markdown("### Precios 2026")
precio_online_mes = st.sidebar.number_input("Online / maestría mensual", 1_000, 100_000, 17_000, 500)
precio_online_completo = st.sidebar.number_input("Online / maestría completo", 1_000, 500_000, 60_000, 1_000)
precio_semestral_mes = st.sidebar.number_input("Semestral mensual", 1_000, 100_000, 23_500, 500)
precio_semestral_completo = st.sidebar.number_input("Semestral completo", 1_000, 500_000, 105_000, 1_000)
recargo_medicina = st.sidebar.slider("Recargo Médico Cirujano", 0.0, 0.50, 0.10, 0.01, format="%.0f%%")

precios = {
    "Cuatrimestral / Online": (precio_online_mes, 4, precio_online_completo),
    "Maestría": (precio_online_mes, 4, precio_online_completo),
    "Semestral": (precio_semestral_mes, 5, precio_semestral_completo),
    "Médico Cirujano": (
        precio_semestral_mes * (1 + recargo_medicina),
        5,
        precio_semestral_completo * (1 + recargo_medicina),
    ),
}

st.sidebar.markdown("### Supuestos")
pago_completo = st.sidebar.slider("Alumnos con pago completo", 0.0, 1.0, 0.20, 0.05, format="%.0f%%")
incremento_nominal = st.sidebar.slider("Aumento nominal anual", 0.0, 0.20, 0.06, 0.005, format="%.1f%%")
inflacion = st.sidebar.slider("Inflación anual", 0.0, 0.20, 0.04, 0.005, format="%.1f%%")
costo_pct = st.sidebar.slider("Costo sobre ingreso bruto", 0.0, 0.80, 0.30, 0.01, format="%.0f%%")
elasticidad = st.sidebar.slider("Elasticidad precio", -5.0, -0.05, -1.20, 0.05)
efecto_beca = st.sidebar.slider("Sensibilidad adicional a beca", 0.0, 6.0, 1.50, 0.10)

st.sidebar.markdown("### Restricciones")
capacidad = st.sidebar.number_input("Capacidad máxima", 1, 20_000, 500, 10)
usar_meta = st.sidebar.checkbox("Exigir meta de inscritos", value=True)
meta_default = min(q_ref, capacidad)
meta = st.sidebar.number_input("Meta mínima", 0, int(capacidad), int(meta_default), 1, disabled=not usar_meta)
usar_bolsa = st.sidebar.checkbox("Aplicar tope de bolsa", value=True)
bolsa_max = st.sidebar.number_input("Bolsa máxima ($)", 0, 1_000_000_000, 25_000_000, 500_000, disabled=not usar_bolsa)
paridad_tipo = st.sidebar.selectbox("Paridad real sobre", ["Precio bruto", "Precio neto después de beca"])

precio_2026 = precio_esperado(esquema, pago_completo, precios)
precio_ref_nominal = precio_2026 * (1 + incremento_nominal) ** (anio_ref - 2026)
precio_obj_base = precio_2026 * (1 + incremento_nominal) ** (anio_obj - 2026)
factor_inflacion = (1 + inflacion) ** (anio_obj - anio_ref)

st.sidebar.markdown("### Grid de búsqueda")
rango_precio = st.sidebar.slider("Rango alrededor del precio base", 0.05, 0.50, 0.25, 0.05, format="%.0f%%")
precio_pasos = st.sidebar.slider("Puntos de precio", 10, 80, 35, 5)
beca_min, beca_max = st.sidebar.slider("Rango de beca", 0.0, 0.70, (0.0, 0.50), 0.01, format="%.0f%%")
beca_pasos = st.sidebar.slider("Puntos de beca", 10, 71, 26, 1)

precios_grid = np.linspace(precio_obj_base * (1 - rango_precio), precio_obj_base * (1 + rango_precio), precio_pasos)
becas_grid = np.linspace(beca_min, beca_max, beca_pasos)

filas = []
for precio in precios_grid:
    for beca in becas_grid:
        precio_real_relativo = (precio / factor_inflacion) / max(precio_ref_nominal, 1)
        q = estimar_inscritos(
            q_ref, precio_real_relativo, beca, 1.0, beca_ref,
            elasticidad, efecto_beca, capacidad,
        )
        ingreso, margen, bolsa = calcular_kpis(q, precio, beca, costo_pct)
        paridad_actual = precio / factor_inflacion
        paridad_ref = precio_ref_nominal
        if paridad_tipo == "Precio neto después de beca":
            paridad_actual *= 1 - beca
            paridad_ref *= 1 - beca_ref
        cumple = paridad_actual >= paridad_ref
        if usar_meta:
            cumple = cumple and q >= meta
        if usar_bolsa:
            cumple = cumple and bolsa <= bolsa_max
        filas.append({
            "Precio": precio, "Beca": beca, "Inscritos": q,
            "Ingreso": ingreso, "Margen": margen, "Bolsa": bolsa,
            "Factible": cumple,
        })

grid = pd.DataFrame(filas)
factibles = grid[grid["Factible"]]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Programa", programa)
col2.metric("Esquema", esquema)
col3.metric("Inscritos de referencia", f"{q_ref:,.0f}")
col4.metric("Beca histórica registrada", f"{beca_ref:.1%}")

st.warning(
    "Prototipo con datos mixtos: los inscritos y becas disponibles vienen del CSV; "
    "precios históricos, elasticidad, costos, inflación y restricciones son supuestos editables."
)

if factibles.empty:
    st.error("No existe una combinación que cumpla todas las restricciones. Amplía el rango o relaja alguna condición.")
    optimo = grid.loc[grid["Margen"].idxmax()]
    etiqueta_optimo = "Mejor escenario sin restricciones"
else:
    optimo = factibles.loc[factibles["Margen"].idxmax()]
    etiqueta_optimo = "Óptimo factible"

st.subheader(etiqueta_optimo)
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Precio promedio", f"${optimo['Precio']:,.0f}")
c2.metric("Beca", f"{optimo['Beca']:.1%}")
c3.metric("Inscritos", f"{optimo['Inscritos']:,.0f}")
c4.metric("Ingreso nominal", f"${optimo['Ingreso']:,.0f}")
c5.metric("Margen nominal", f"${optimo['Margen']:,.0f}")

tab1, tab2, tab3, tab4 = st.tabs(["Heatmap", "Frontera", "Comparativa", "Datos y metodología"])

with tab1:
    pivote = grid.pivot(index="Beca", columns="Precio", values="Margen")
    fig = px.imshow(
        pivote,
        aspect="auto",
        origin="lower",
        color_continuous_scale="Viridis",
        labels={"x": "Precio promedio nominal", "y": "Beca", "color": "Margen"},
    )
    fig.update_yaxes(tickformat=".0%")
    fig.update_xaxes(tickprefix="$", tickformat=",.0f")
    fig.add_scatter(
        x=[optimo["Precio"]], y=[optimo["Beca"]], mode="markers",
        marker=dict(color="red", size=13, symbol="x"), name="Óptimo",
    )
    st.plotly_chart(fig, width="stretch")

with tab2:
    base_frontera = factibles if not factibles.empty else grid
    idx = base_frontera.groupby("Precio")["Margen"].idxmax()
    frontera = base_frontera.loc[idx].sort_values("Precio")
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=frontera["Precio"], y=frontera["Beca"], mode="lines+markers",
        customdata=np.c_[frontera["Margen"], frontera["Inscritos"]],
        hovertemplate="Precio: $%{x:,.0f}<br>Beca: %{y:.1%}<br>Margen: $%{customdata[0]:,.0f}<br>Inscritos: %{customdata[1]:,.0f}<extra></extra>",
        name="Mejor beca por precio",
    ))
    fig2.update_layout(xaxis_title="Precio promedio nominal", yaxis_title="Beca")
    fig2.update_xaxes(tickprefix="$", tickformat=",.0f")
    fig2.update_yaxes(tickformat=".0%")
    st.plotly_chart(fig2, width="stretch")

with tab3:
    precio_actual = precio_obj_base
    beca_actual = beca_ref
    precio_actual_rel = (precio_actual / factor_inflacion) / max(precio_ref_nominal, 1)
    q_actual = estimar_inscritos(q_ref, precio_actual_rel, beca_actual, 1.0, beca_ref, elasticidad, efecto_beca, capacidad)
    ingreso_ref, margen_ref, bolsa_ref = calcular_kpis(q_ref, precio_ref_nominal, beca_ref, costo_pct)
    ingreso_act, margen_act, bolsa_act = calcular_kpis(q_actual, precio_actual, beca_actual, costo_pct)
    comparativa = pd.DataFrame({
        "Escenario": [f"Referencia {anio_ref}", f"Actual {anio_obj}", "Óptimo"],
        "Inscritos": [q_ref, q_actual, optimo["Inscritos"]],
        "Precio": [precio_ref_nominal, precio_actual, optimo["Precio"]],
        "Beca": [beca_ref, beca_actual, optimo["Beca"]],
        "Ingreso": [ingreso_ref, ingreso_act, optimo["Ingreso"]],
        "Margen": [margen_ref, margen_act, optimo["Margen"]],
        "Bolsa": [bolsa_ref, bolsa_act, optimo["Bolsa"]],
    })
    st.dataframe(
        comparativa.style.format({
            "Inscritos": "{:,.0f}", "Precio": "${:,.0f}", "Beca": "{:.1%}",
            "Ingreso": "${:,.0f}", "Margen": "${:,.0f}", "Bolsa": "${:,.0f}",
        }),
        width="stretch",
        hide_index=True,
    )
    csv_descarga = comparativa.to_csv(index=False).encode("utf-8-sig")
    st.download_button("Descargar comparativa CSV", csv_descarga, "comparativa_optimizador.csv", "text/csv")

with tab4:
    tendencia = (
        datos_programa.groupby(["Año comercial", "Periodo Comercial"], as_index=False)
        .agg(Inscritos=("_unidad", "nunique"), Beca_registrada=("_beca", "mean"))
        .sort_values(["Año comercial", "Periodo Comercial"])
    )
    st.markdown("#### Tendencia histórica del programa")
    fig3 = px.bar(tendencia, x="Periodo Comercial", y="Inscritos", color="Año comercial", barmode="group")
    st.plotly_chart(fig3, width="stretch")
    st.markdown("#### Modelo de demanda")
    st.latex(r"Q=\min\{Capacidad,\ Q_{ref}(P^{real}/P^{real}_{ref})^{\varepsilon}e^{\gamma(B-B_{ref})}\}")
    st.markdown(
        "El precio del grid es el precio bruto promedio por alumno, ponderado por la mezcla entre pago completo "
        "y mensualidades. El costo se calcula antes de beca, mientras que ingreso, bolsa y margen se expresan "
        "en pesos nominales del año objetivo."
    )
