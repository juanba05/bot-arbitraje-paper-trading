# Bot de Arbitraje CEDEAR/NYSE (Paper Trading)

Proyecto en Python para monitoreo de arbitraje CEDEAR/NYSE, simulacion de cauciones y dashboard operativo.

## Objetivo

- Detectar oportunidades de arbitraje entre CEDEARs (BYMA) y NYSE.
- Simular ejecucion en paper trading con controles de riesgo.
- Monitorear estado operativo desde dashboard local.

## Estructura principal

- `bot_principal.py`: orquestador principal.
- `motor_calculo.py`: logica de calculo de arbitraje.
- `motor_cauciones.py`: analisis/simulacion de cauciones.
- `ejecutor_paper.py`: ejecucion paper y gestion de capital.
- `dashboard.py`: interfaz web local (Dash/Plotly).
- `preflight_operativo.py`: chequeos de readiness.
- `lanzar_sesion.py`: inicio/parada de procesos.

## Variables de entorno requeridas

Definir en un archivo `.env` local (no versionado):

- `IOL_USUARIO`
- `IOL_PASSWORD`
- `POLYGON_API_KEY` (opcional segun flujo)
- `WSP_ALLOWED_FROM` (opcional, bridge WhatsApp)
- `WSP_REQUIRE_PIN` (opcional)
- `WSP_PIN` (opcional)
- `TWILIO_ACCOUNT_SID` (opcional)
- `TWILIO_AUTH_TOKEN` (opcional)
- `TWILIO_WHATSAPP_FROM` (opcional)
- `OPENAI_API_KEY` (opcional)
- `WSP_AI_MODEL` (opcional)

## Ejecucion local

```bash
python preflight_operativo.py
python bot_principal.py
python dashboard.py
```

Luego abrir `http://127.0.0.1:8050`.

## Seguridad para GitHub

- Este repositorio debe publicarse sin `.env`, bases de datos, logs ni carpeta `datos/`.
- Revisar siempre el contenido staged antes de hacer `push`:
  - `git status`
  - `git diff --cached`

## Estado

Uso orientado a paper trading y pruebas operativas. No constituye recomendacion financiera.
