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

Para funcionar dentro de los límites de memoria de Streamlit Community Cloud, la aplicación lee únicamente las siete columnas necesarias del CSV, convierte campos repetitivos a categorías y reutiliza el mismo DataFrame entre ejecuciones.

Los inscritos base del modelo se obtienen contando oportunidades únicas del programa y periodo seleccionados, pero pueden modificarse desde la barra lateral. Los porcentajes se muestran en escala 0–100 y los supuestos, restricciones y controles del grid se encuentran dentro de Configuración avanzada.

La aplicación diferencia leads e inscritos. Prioriza `Conteo de inscrito > 0`; si esa columna no existe, utiliza `Hora de inscrito` y después `Etapa de venta`. Los leads se cuentan con `Id de lead`, los inscritos con `Id de oportunidad` y la conversión con leads únicos que alcanzaron la inscripción.

Los identificadores se cargan como texto para conservar completos sus 19 dígitos y evitar que la notación científica agrupe personas diferentes.

La tabla comparativa puede guardarse en una hoja acumulativa de Google Sheets mediante un botón independiente de la descarga. Consulta `CONFIGURAR_GOOGLE_SHEETS.md`: utiliza un webhook gratuito de Google Apps Script y no requiere cuenta de servicio, Google Cloud Shell, facturación ni clave JSON.

La configuración avanzada explica la resolución del grid. Los puntos de precio indican cuántos precios distintos se prueban y los puntos de beca cuántos niveles se distribuyen en el rango elegido. La interfaz muestra dinámicamente los saltos aproximados y el total de combinaciones.
