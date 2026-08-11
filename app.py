from pathlib import Path
from datetime import datetime
from hashlib import sha256
from uuid import uuid4
from zoneinfo import ZoneInfo

import gspread
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from google.oauth2.service_account import Credentials


st.set_page_config(page_title="Optimizador Precio–Beca", page_icon="🎓", layout="wide")

COLUMNAS_REQUERIDAS = {
    "Programa académico",
    "Periodo Comercial",
    "Año comercial",
    "Nivel de programa",
    "Unidad de negocio",
}


@st.cache_resource(show_spinner=False)
def cargar_csv(archivo):
    # Leer primero únicamente el encabezado permite descartar más de cien
    # columnas que el optimizador no utiliza y reduce mucho el uso de memoria.
    encabezado = pd.read_csv(archivo, nrows=0, encoding="utf-8-sig").columns.tolist()
    faltantes = COLUMNAS_REQUERIDAS.difference(encabezado)
    if faltantes:
        raise ValueError("Faltan columnas: " + ", ".join(sorted(faltantes)))

    columnas_utiles = list(COLUMNAS_REQUERIDAS)
    for opcional in [
        "Id de oportunidad",
        "Id de lead",
        "% de beca aprobada",
        "Conteo de inscrito",
        "Hora de inscrito",
        "Etapa de venta",
    ]:
        if opcional in encabezado:
            columnas_utiles.append(opcional)

    if hasattr(archivo, "seek"):
        archivo.seek(0)
    tipos_texto = {
        columna: "string"
        for columna in ["Id de oportunidad", "Id de lead"]
        if columna in columnas_utiles
    }
    df = pd.read_csv(
        archivo,
        usecols=columnas_utiles,
        dtype=tipos_texto,
        low_memory=False,
        encoding="utf-8-sig",
    )

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

    if "Id de lead" in df.columns:
        respaldo_lead = pd.Series(df["_unidad"], index=df.index)
        df["_id_lead"] = df["Id de lead"].fillna(respaldo_lead).astype(str)
    else:
        df["_id_lead"] = df["_unidad"]

    # Jerarquía para reconocer inscritos. La bandera explícita tiene prioridad;
    # las demás columnas sirven como respaldo para extractos con otro formato.
    if "Conteo de inscrito" in df.columns:
        df["_es_inscrito"] = (
            pd.to_numeric(df["Conteo de inscrito"], errors="coerce").fillna(0) > 0
        )
        metodo_inscrito = '"Conteo de inscrito" mayor que 0'
    elif "Hora de inscrito" in df.columns:
        hora = df["Hora de inscrito"].fillna("").astype(str).str.strip()
        df["_es_inscrito"] = hora.ne("")
        metodo_inscrito = '"Hora de inscrito" informada'
    elif "Etapa de venta" in df.columns:
        etapa = df["Etapa de venta"].fillna("").astype(str).str.upper().str.strip()
        df["_es_inscrito"] = etapa.isin(["INSCRITO", "ALUMNO"])
        metodo_inscrito = '"Etapa de venta" igual a Inscrito o Alumno'
    else:
        df["_es_inscrito"] = True
        metodo_inscrito = "todos los registros (no se encontró una columna de inscripción)"

    df["_unidad_inscrita"] = df["_unidad"].where(df["_es_inscrito"])
    df["_lead_inscrito"] = df["_id_lead"].where(df["_es_inscrito"])
    df.attrs["metodo_inscrito"] = metodo_inscrito

    # Las columnas repetitivas ocupan mucho menos como categorías.
    for columna in [
        "Programa académico",
        "Periodo Comercial",
        "Nivel de programa",
        "Unidad de negocio",
    ]:
        df[columna] = df[columna].astype("category")
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


def google_sheets_configurado():
    return (
        "gcp_service_account" in st.secrets
        and "google_sheets" in st.secrets
        and bool(st.secrets["google_sheets"].get("spreadsheet_id"))
    )


def guardar_comparativa_google_sheets(comparativa, contexto):
    if not google_sheets_configurado():
        raise ValueError("Falta configurar Google Sheets en los Secrets de Streamlit.")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
    ]
    credenciales = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]),
        scopes=scopes,
    )
    cliente = gspread.authorize(credenciales)
    configuracion = st.secrets["google_sheets"]
    libro = cliente.open_by_key(configuracion["spreadsheet_id"])
    nombre_hoja = configuracion.get("worksheet_name", "Comparativas")

    try:
        hoja = libro.worksheet(nombre_hoja)
    except gspread.WorksheetNotFound:
        hoja = libro.add_worksheet(title=nombre_hoja, rows=1000, cols=30)

    encabezados = [
        "Id registro",
        "Fecha de guardado",
        "Programa",
        "Esquema",
        "Periodo referencia",
        "Año referencia",
        "Año objetivo",
        "Escenario",
        "Inscritos",
        "Precio",
        "Beca",
        "Ingreso",
        "Margen",
        "Bolsa",
        "Leads históricos",
        "Conversión histórica",
        "Inscritos base",
        "Capacidad",
        "Meta mínima",
        "Pago completo",
        "Incremento nominal",
        "Inflación",
        "Costo",
        "Elasticidad",
        "Sensibilidad a beca",
        "Paridad real sobre",
    ]

    if not hoja.get_all_values():
        hoja.append_row(encabezados, value_input_option="RAW")

    id_registro = str(uuid4())
    fecha = datetime.now(ZoneInfo("America/Mexico_City")).isoformat(timespec="seconds")
    filas = []
    for _, fila in comparativa.iterrows():
        filas.append([
            id_registro,
            fecha,
            contexto["programa"],
            contexto["esquema"],
            contexto["periodo_ref"],
            contexto["anio_ref"],
            contexto["anio_obj"],
            fila["Escenario"],
            float(fila["Inscritos"]),
            float(fila["Precio"]),
            float(fila["Beca"]),
            float(fila["Ingreso"]),
            float(fila["Margen"]),
            float(fila["Bolsa"]),
            contexto["leads_historicos"],
            contexto["conversion_historica"],
            contexto["q_ref"],
            contexto["capacidad"],
            contexto["meta"],
            contexto["pago_completo"],
            contexto["incremento_nominal"],
            contexto["inflacion"],
            contexto["costo_pct"],
            contexto["elasticidad"],
            contexto["efecto_beca"],
            contexto["paridad_tipo"],
        ])

    hoja.append_rows(filas, value_input_option="USER_ENTERED")
    return libro.url, id_registro


st.title("🎓 Optimizador de Precio y Beca")
st.caption("Prototipo para explorar escenarios con datos históricos y supuestos editables.")

archivo_local = Path("Datos.csv")
archivo = st.sidebar.file_uploader("Cargar Datos.csv", type=["csv"], max_upload_size=500)
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
datos_programa = datos[datos["Programa académico"] == programa]
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
ref_inscritos = ref[ref["_es_inscrito"]]
leads_historicos = int(ref["_id_lead"].nunique())
leads_convertidos = int(ref_inscritos["_id_lead"].nunique())
leads_sin_inscripcion = max(leads_historicos - leads_convertidos, 0)
q_ref_historico = int(ref_inscritos["_unidad"].nunique())
conversion_historica = leads_convertidos / leads_historicos if leads_historicos else 0.0
beca_ref = float(ref_inscritos["_beca"].fillna(0).mean()) if len(ref_inscritos) else 0.0

if q_ref_historico <= 0:
    st.sidebar.warning(
        "No se encontraron inscritos en este periodo. Define manualmente los inscritos base para simular."
    )

clave_q_ref = f"q_ref::{programa}::{anio_ref}::{periodo_ref}"
if clave_q_ref not in st.session_state:
    st.session_state[clave_q_ref] = max(q_ref_historico, 1)
q_ref = st.sidebar.number_input(
    "Inscritos base para simular",
    min_value=1,
    max_value=50_000,
    step=1,
    key=clave_q_ref,
    help=(
        "Parte del conteo de oportunidades únicas inscritas en el programa y periodo "
        "seleccionados. Puedes modificarlo para probar un escenario base distinto."
    ),
)
st.sidebar.caption(
    f"El CSV registra {leads_historicos:,} leads y {q_ref_historico:,} inscritos únicos "
    f"en {periodo_ref}. Este valor histórico no es una meta ni la capacidad."
)

st.sidebar.markdown("### Precios 2026")
precio_online_mes = st.sidebar.number_input("Online / maestría mensual", 1_000, 100_000, 17_000, 500)
precio_online_completo = st.sidebar.number_input("Online / maestría completo", 1_000, 500_000, 60_000, 1_000)
precio_semestral_mes = st.sidebar.number_input("Semestral mensual", 1_000, 100_000, 23_500, 500)
precio_semestral_completo = st.sidebar.number_input("Semestral completo", 1_000, 500_000, 105_000, 1_000)
recargo_medicina_pct = st.sidebar.slider(
    "Recargo Médico Cirujano",
    min_value=0,
    max_value=30,
    value=10,
    step=1,
    format="%d%%",
)
recargo_medicina = recargo_medicina_pct / 100

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

with st.sidebar.expander("⚙️ Configuración avanzada", expanded=False):
    st.markdown("#### Supuestos")
    pago_completo_pct = st.slider(
        "Alumnos con pago completo",
        0,
        100,
        20,
        5,
        format="%d%%",
        help="Porcentaje supuesto de alumnos que paga el programa completo en lugar de mensualidades.",
    )
    incremento_nominal_pct = st.slider(
        "Aumento nominal anual",
        0,
        20,
        6,
        1,
        format="%d%%",
        help="Crecimiento anual supuesto de los precios publicados.",
    )
    inflacion_pct = st.slider(
        "Inflación anual",
        0,
        15,
        4,
        1,
        format="%d%%",
        help="Se utiliza para comparar precios en términos reales.",
    )
    costo_pct_ui = st.slider(
        "Costo sobre ingreso bruto",
        0,
        80,
        30,
        1,
        format="%d%%",
        help="Costo proporcional supuesto antes de descontar la beca.",
    )
    elasticidad = st.slider(
        "Elasticidad precio",
        -3.0,
        -0.1,
        -1.2,
        0.1,
        help="Valor negativo: indica cuánto disminuye la demanda cuando sube el precio real.",
    )
    efecto_beca = st.slider(
        "Sensibilidad adicional a beca",
        0.0,
        4.0,
        1.5,
        0.1,
        help="Aumenta la respuesta estimada de inscritos ante una beca mayor.",
    )

    pago_completo = pago_completo_pct / 100
    incremento_nominal = incremento_nominal_pct / 100
    inflacion = inflacion_pct / 100
    costo_pct = costo_pct_ui / 100

    st.markdown("#### Restricciones")
    capacidad = st.number_input(
        "Capacidad máxima",
        1,
        20_000,
        500,
        10,
        help="Máximo de inscritos permitido en el escenario objetivo; no modifica el histórico.",
    )
    usar_meta = st.checkbox("Exigir meta de inscritos", value=True)
    clave_meta = f"meta::{programa}::{anio_ref}::{periodo_ref}"
    if clave_meta not in st.session_state or st.session_state[clave_meta] > capacidad:
        st.session_state[clave_meta] = min(int(q_ref), int(capacidad))
    meta = st.number_input(
        "Meta mínima",
        0,
        int(capacidad),
        step=1,
        key=clave_meta,
        disabled=not usar_meta,
        help="Cantidad mínima de inscritos que debe alcanzar una combinación para considerarse factible.",
    )
    usar_bolsa = st.checkbox("Aplicar tope de bolsa", value=True)
    bolsa_max = st.number_input(
        "Bolsa máxima ($)",
        0,
        1_000_000_000,
        25_000_000,
        500_000,
        disabled=not usar_bolsa,
        help="Monto nominal máximo destinado a becas en el escenario.",
    )
    paridad_tipo = st.selectbox(
        "Paridad real sobre",
        ["Precio bruto", "Precio neto después de beca"],
        help="Define si la comparación contra inflación se realiza antes o después de beca.",
    )

    st.markdown("#### Grid de búsqueda")
    rango_precio_pct = st.slider(
        "Rango alrededor del precio base",
        5,
        50,
        25,
        5,
        format="%d%%",
        help="Porcentaje hacia abajo y arriba que explorará el optimizador.",
    )
    precio_pasos = st.slider("Puntos de precio", 15, 60, 35, 5)
    beca_min_pct, beca_max_pct = st.slider(
        "Rango de beca",
        0,
        70,
        (0, 50),
        5,
        format="%d%%",
    )
    beca_pasos = st.slider("Puntos de beca", 10, 50, 26, 1)

    rango_precio = rango_precio_pct / 100
    beca_min = beca_min_pct / 100
    beca_max = beca_max_pct / 100

precio_2026 = precio_esperado(esquema, pago_completo, precios)
precio_ref_nominal = precio_2026 * (1 + incremento_nominal) ** (anio_ref - 2026)
precio_obj_base = precio_2026 * (1 + incremento_nominal) ** (anio_obj - 2026)
factor_inflacion = (1 + inflacion) ** (anio_obj - anio_ref)

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

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Programa", programa)
col2.metric("Leads históricos", f"{leads_historicos:,.0f}")
col3.metric("Leads sin inscripción", f"{leads_sin_inscripcion:,.0f}")
col4.metric(
    "Inscritos base del modelo",
    f"{q_ref:,.0f}",
    delta=f"Histórico CSV: {q_ref_historico:,.0f}",
    delta_color="off",
    help="Valor editable desde la barra lateral y utilizado como punto de partida de la demanda.",
)
col5.metric("Conversión histórica", f"{conversion_historica:.1%}")
st.caption(
    f"Esquema: **{esquema}** · Beca registrada entre inscritos: **{beca_ref:.1%}** · "
    f"Criterio de inscripción: **{datos.attrs.get('metodo_inscrito', 'no disponible')}**."
)

with st.expander("¿Qué significan los inscritos base?", expanded=False):
    st.markdown(
        f"El archivo contiene **{leads_historicos:,} leads únicos**, de los cuales "
        f"**{leads_convertidos:,} llegaron a inscripción**, para **{programa}** en "
        f"**{periodo_ref}**. Los inscritos históricos se cuentan con oportunidades únicas; "
        "la conversión se calcula con leads únicos para evitar duplicarlos. "
        "El campo **Inscritos base para simular** permite sustituirlo por un supuesto cuando "
        "el CSV esté incompleto o se quiera probar otro punto inicial. No representa la meta ni "
        "la capacidad: la meta es el mínimo deseado y la capacidad es el máximo permitido para "
        "el año objetivo."
    )

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

tab1, tab2, tab3, tab4 = st.tabs(["Heatmap", "Frontera", "Comparativa", "Embudo y metodología"])

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
    contexto_guardado = {
        "programa": programa,
        "esquema": esquema,
        "periodo_ref": periodo_ref,
        "anio_ref": int(anio_ref),
        "anio_obj": int(anio_obj),
        "leads_historicos": int(leads_historicos),
        "conversion_historica": float(conversion_historica),
        "q_ref": int(q_ref),
        "capacidad": int(capacidad),
        "meta": int(meta) if usar_meta else 0,
        "pago_completo": float(pago_completo),
        "incremento_nominal": float(incremento_nominal),
        "inflacion": float(inflacion),
        "costo_pct": float(costo_pct),
        "elasticidad": float(elasticidad),
        "efecto_beca": float(efecto_beca),
        "paridad_tipo": paridad_tipo,
    }
    huella = sha256(
        (comparativa.to_csv(index=False) + repr(sorted(contexto_guardado.items()))).encode("utf-8")
    ).hexdigest()
    ya_guardado = st.session_state.get("ultima_comparativa_guardada") == huella

    col_guardar, col_descargar = st.columns(2)
    with col_guardar:
        if not google_sheets_configurado():
            st.info(
                "Configura las credenciales de Google Sheets en los Secrets de Streamlit "
                "para habilitar el guardado."
            )
        elif st.button(
            "Guardar escenario en Google Sheets",
            type="primary",
            disabled=ya_guardado,
            width="stretch",
        ):
            try:
                with st.spinner("Guardando comparativa..."):
                    url_hoja, id_guardado = guardar_comparativa_google_sheets(
                        comparativa,
                        contexto_guardado,
                    )
                st.session_state["ultima_comparativa_guardada"] = huella
                st.session_state["ultimo_id_guardado"] = id_guardado
                st.session_state["ultima_url_hoja"] = url_hoja
                st.success(f"Escenario guardado. Folio: {id_guardado}")
            except Exception as exc:
                st.error(f"No se pudo guardar en Google Sheets: {exc}")

        if ya_guardado:
            st.success(
                "Este escenario ya fue guardado. Cambia un parámetro para habilitar nuevamente el botón."
            )
        if st.session_state.get("ultima_url_hoja"):
            st.link_button(
                "Abrir Google Sheets",
                st.session_state["ultima_url_hoja"],
                width="stretch",
            )

    with col_descargar:
        st.download_button(
            "Descargar comparativa CSV",
            csv_descarga,
            "comparativa_optimizador.csv",
            "text/csv",
            width="stretch",
        )

with tab4:
    tendencia = (
        datos_programa.groupby(
            ["Año comercial", "Periodo Comercial"],
            as_index=False,
            observed=True,
        )
        .agg(
            Leads=("_id_lead", "nunique"),
            Inscritos=("_unidad_inscrita", "nunique"),
            Leads_convertidos=("_lead_inscrito", "nunique"),
            Beca_registrada=("_beca", "mean"),
        )
        .sort_values(["Año comercial", "Periodo Comercial"])
    )
    tendencia["Conversión"] = np.where(
        tendencia["Leads"] > 0,
        tendencia["Leads_convertidos"] / tendencia["Leads"],
        0,
    )
    tendencia["Periodo"] = (
        tendencia["Año comercial"].astype(str)
        + " · "
        + tendencia["Periodo Comercial"].astype(str)
    )
    st.markdown("#### Leads e inscritos por periodo")
    fig3 = px.bar(
        tendencia,
        x="Periodo",
        y=["Leads", "Inscritos"],
        barmode="group",
        labels={"value": "Personas", "variable": "Etapa"},
    )
    st.plotly_chart(fig3, width="stretch")
    st.dataframe(
        tendencia[["Año comercial", "Periodo Comercial", "Leads", "Inscritos", "Conversión"]]
        .style.format({"Conversión": "{:.1%}"}),
        width="stretch",
        hide_index=True,
    )
    st.markdown(
        "Un inscrito también forma parte de los leads totales: el embudo muestra cuántos leads "
        "se generaron y qué subconjunto llegó a inscripción. Los leads sin inscripción son la "
        "diferencia entre ambos grupos."
    )
    st.markdown("#### Modelo de demanda")
    st.latex(r"Q=\min\{Capacidad,\ Q_{ref}(P^{real}/P^{real}_{ref})^{\varepsilon}e^{\gamma(B-B_{ref})}\}")
    st.markdown(
        "El precio del grid es el precio bruto promedio por alumno, ponderado por la mezcla entre pago completo "
        "y mensualidades. El costo se calcula antes de beca, mientras que ingreso, bolsa y margen se expresan "
        "en pesos nominales del año objetivo."
    )
