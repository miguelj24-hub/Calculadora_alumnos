# Configurar el guardado en Google Sheets

La aplicación guarda tres filas por escenario: Referencia, Actual y Óptimo. El guardado ocurre únicamente al presionar **Guardar escenario en Google Sheets**.

## 1. Crear la hoja

1. En Google Drive, crea una hoja de cálculo vacía.
2. Ponle un nombre, por ejemplo `Comparativas Optimizador`.
3. Copia el identificador que aparece entre `/d/` y `/edit` en la dirección de la hoja.

## 2. Crear la cuenta de servicio

1. Entra a Google Cloud Console y crea o selecciona un proyecto.
2. Activa **Google Sheets API** y **Google Drive API**.
3. Abre **IAM y administración → Cuentas de servicio**.
4. Crea una cuenta de servicio y genera una clave en formato JSON.
5. Copia el correo `client_email` de ese archivo JSON.

No subas el JSON ni una clave privada a GitHub.

## 3. Compartir la hoja

Comparte la hoja de Google Sheets con el `client_email` de la cuenta de servicio y dale permiso de **Editor**.

## 4. Configurar Streamlit Cloud

1. En Streamlit Cloud abre la aplicación.
2. Entra a **Manage app → Settings → Secrets**.
3. Usa `.streamlit/secrets.toml.example` como plantilla.
4. Sustituye `spreadsheet_id` y todos los campos de `gcp_service_account` con los valores del archivo JSON.
5. Guarda los Secrets y reinicia la aplicación.

El bloque `private_key` debe conservar los caracteres `\n` indicados en el JSON.

## Seguridad

- `.streamlit/secrets.toml` está excluido mediante `.gitignore`.
- Nunca publiques el JSON de la cuenta de servicio.
- Si una clave se publica accidentalmente, elimínala desde Google Cloud y genera una nueva.
