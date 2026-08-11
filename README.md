# Optimizador de Precio y Beca

Prototipo en Streamlit para explorar combinaciones de precio y beca por programa, estimar inscritos y encontrar el escenario de mayor margen sujeto a paridad real, meta, bolsa y capacidad.

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

En macOS o Linux, la activación es `source .venv/bin/activate`.

## Ejecución

```bash
streamlit run app.py
```

Carga `Datos.csv` desde la barra lateral. También puedes colocarlo en la misma carpeta que `app.py`; el archivo no se incluye en este proyecto porque contiene datos personales.

## Supuestos iniciales

- Precios base correspondientes a 2026.
- Online y maestrías: cuatro mensualidades de $17,000 o pago completo de $60,000.
- Semestral: cinco mensualidades de $23,500 o pago completo de $105,000.
- Médico Cirujano: recargo de 10% sobre el esquema semestral.
- Mezcla de pago: 20% completo y 80% mensualidades.
- Incremento nominal anual: 6%.
- Costo proporcional: 30% del ingreso bruto antes de beca.
- Capacidad inicial: 500 alumnos.
- La elasticidad, inflación, efecto de beca y restricciones son editables.

## Alcance

El archivo histórico disponible contiene inscritos. Por ello, la elasticidad de demanda es un supuesto editable y no una estimación causal. La aplicación distingue visualmente este alcance y permite sustituir los supuestos cuando existan datos completos del embudo, costos, competencia e INPC.

La selección de periodo se reinicia automáticamente cuando cambia el programa o el año de referencia, evitando conservar combinaciones que no existen en los datos.
