# Guardar en Google Sheets sin clave JSON

Este método funciona con una cuenta personal gratuita. No requiere Google Cloud Shell, facturación ni una cuenta de servicio.

## 1. Crear la hoja

1. En Google Drive crea una hoja de cálculo vacía.
2. Llámala, por ejemplo, `Comparativas Optimizador`.
3. Abre **Extensiones → Apps Script**.

## 2. Pegar el código

1. Borra el contenido de `Código.gs`.
2. Abre `GOOGLE_APPS_SCRIPT.gs`, copia todo y pégalo en `Código.gs`.
3. En `SPREADSHEET_ID`, reemplaza `PEGA_EL_ID_DE_LA_HOJA` por el texto ubicado entre `/d/` y `/edit` en la URL de tu hoja.
4. En `SECRET_TOKEN`, reemplaza `INVENTA_UN_TOKEN_LARGO` por una contraseña larga inventada, idealmente de 40 o más letras y números.
5. Guarda el proyecto.

No compartas el token ni lo subas a GitHub.

## 3. Publicar como aplicación web

1. Presiona **Implementar → Nueva implementación**.
2. En el tipo selecciona **Aplicación web**.
3. En **Ejecutar como** selecciona **Yo**.
4. En **Quién tiene acceso** selecciona **Cualquier usuario**.
5. Presiona **Implementar** y autoriza el acceso solicitado por Google.
6. Copia la URL; debe terminar en `/exec`.

Si Google muestra una advertencia de aplicación no verificada, continúa únicamente si confirmas que el proyecto y todo el código son tuyos.

## 4. Configurar Streamlit

1. En Streamlit abre **Manage app → Settings → Secrets**.
2. Pega:

```toml
[google_sheets_webhook]
url = "URL_QUE_TERMINA_EN_EXEC"
token = "EL_MISMO_TOKEN_DEL_APPS_SCRIPT"
```

3. Sustituye ambos valores, guarda y reinicia la aplicación.

## 5. Probar

En Comparativa presiona **Guardar escenario en Google Sheets**. Apps Script creará una pestaña `Comparativas` y añadirá tres filas: Referencia, Actual y Óptimo.

## Seguridad

- El Apps Script valida el token antes de guardar.
- El token permanece en Streamlit Secrets, no en GitHub.
- Si el token se filtra, cámbialo en Apps Script y Streamlit; después crea una implementación nueva.
