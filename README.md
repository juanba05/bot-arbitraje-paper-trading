# Bot de Arbitraje CEDEAR/NYSE (Paper Trading)

Proyecto personal de trading cuantitativo orientado a deteccion de oportunidades entre CEDEARs (BYMA) y NYSE, con simulacion de cauciones y panel operativo en tiempo real.

## Resumen Ejecutivo

- Dominio: mercados financieros (Argentina + US).
- Enfoque: automatizacion, monitoreo y control de riesgo en entorno de paper trading.
- Objetivo: construir una base tecnica robusta antes de cualquier operativa real.

## Que resuelve

- Detecta desvios de precio entre activos equivalentes CEDEAR/NYSE.
- Evalua cauciones con logica multi-plazo y costo financiero.
- Centraliza estado operativo en dashboard local para toma de decisiones.
- Ejecuta chequeos pre-operativos para reducir fallas de entorno.

## Stack Tecnologico

- Lenguaje: Python
- Datos y persistencia: SQLite, JSON
- Visualizacion: Dash + Plotly
- Integraciones: APIs REST + scraping web controlado
- Automatizacion: scripts de sesion, preflight y monitoreo

## Arquitectura (modulos principales)

- `bot_principal.py`: orquestacion de ciclos operativos.
- `motor_calculo.py`: calculo de arbitraje CEDEAR/NYSE.
- `motor_cauciones.py`: analisis/simulacion de cauciones.
- `ejecutor_paper.py`: ejecucion paper con reglas de riesgo.
- `dashboard.py`: interfaz de monitoreo y control.
- `preflight_operativo.py`: validaciones criticas antes de operar.
- `lanzar_sesion.py`: arranque/parada de procesos.

## Seguridad y Buenas Practicas

- Credenciales gestionadas por variables de entorno (`.env` local, no versionado).
- Exclusion de datos sensibles mediante `.gitignore`:
  - `.env`, `datos/`, `logs/`, `*.db`, archivos temporales.
- Flujo recomendado antes de publicar:
  - `git status`
  - `git diff --cached`

## Ejecucion Local (referencia)

```bash
python preflight_operativo.py
python bot_principal.py
python dashboard.py
```

Dashboard local: `http://127.0.0.1:8050`

## Estado del Proyecto

- Estado actual: activo en paper trading y pruebas operativas.
- Alcance del repositorio: demostracion tecnica y portfolio profesional.
- Nota: este proyecto no constituye recomendacion financiera.
