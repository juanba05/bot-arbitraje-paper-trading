# Operativa Diaria (Profesional)

## 1) Pre-market (antes de abrir)
1. Ejecutar: `python preflight_operativo.py`
2. Revisar en pantalla que diga `ESTADO GLOBAL: READY`.
3. Si da `NOT_READY`, abrir `datos/preflight_last.json` y corregir solo checks `CRITICO` en `ok=false`.

## 2) Inicio de sesión (simple)
1. Levantar todo con un comando:
   - `python lanzar_sesion.py start --mode both`
2. Ver estado de procesos:
   - `python lanzar_sesion.py status`
3. Para apagar todo:
   - `python lanzar_sesion.py stop`

## 3) Controles manuales tuyos (paso a paso)
1. Dashboard: confirmar `Modo bot` (AUTO o FORZADO) y que sea el que querés usar.
2. Dashboard: confirmar que `Bot ACTIVO` esté en ON.
3. Revisar `cauciones_iol_web` en preflight (debe tener al menos 1 plazo con tasa real).
4. Revisar `saldo_parseado` en preflight (debe parsear saldo ARS).
5. Durante rueda: monitorear `estado_bot.json` y logs del día.

## 4) Recomendación de disciplina operativa
1. No habilitar operación real hasta tener 5 ruedas seguidas en READY sin fallas críticas.
2. En etapa real, empezar con monto mínimo y escalar por tramos.
3. Mantener foco principal en cauciones hasta estabilizar métricas.

## 5) Trabajar con Codex mientras el bot corre
1. Sí, es válido: podés dejar bot/dashboard corriendo y seguir trabajando con Codex en otra terminal.
2. Recomendado: no editar `config.py`, `motor_cauciones.py` o `bot_principal.py` mientras el bot está activo.
3. Para cambios de código: primero `python lanzar_sesion.py stop`, luego editar/probar, y después volver a iniciar.

## 6) Trabajo remoto por WhatsApp (bridge local seguro)
1. Ejecutar bridge local (en la notebook): `python whatsapp_bridge.py serve --port 8787`
2. Exponer solo ese puerto con tunel HTTPS (ejemplo: ngrok) y configurar Twilio webhook a `https://TU_URL/whatsapp`.
3. Seguridad minima obligatoria:
   - filtrar por numero permitido (`WSP_ALLOWED_FROM`)
   - activar PIN (`WSP_REQUIRE_PIN=true` + `WSP_PIN`)
4. Revisar mensajes aceptados:
   - `python whatsapp_bridge.py pending --limit 20`
5. Ver ultimo evento recibido:
   - `python whatsapp_bridge.py status`
6. Enviar respuesta por WhatsApp desde la notebook:
   - `python whatsapp_bridge.py send --to +5493515518319 --text "mensaje"`

Notas:
- El bridge NO lee `.env`; usa variables de entorno del proceso.
- El bridge guarda auditoria local en `datos/wsp_inbox.jsonl`.

## 7) Modo simple recomendado (inicio/cierre + remoto)
Inicio local (1 comando):
1. `python whatsapp_bridge.py agent --interval 5 --max 50`
2. Dejar esa terminal abierta.

Cierre local:
1. `Ctrl + C` en la terminal del agent.

Comandos remotos por WhatsApp (si PIN=1234):
1. `1234 help`
2. `1234 ping`
3. `1234 status` o `1234 estado`
4. `1234 start` (levanta bot + dashboard)
5. `1234 start bot`
6. `1234 start dashboard`
7. `1234 detener` (detiene bot/dashboard)
8. `1234 preflight` (ejecuta preflight y responde resumen)
9. `1234 codex status` (valida login de codex en la notebook)
10. `1234 codex <pedido>` (ejecuta tarea de codigo y responde resumen)
11. `1234 detener bridge` (apaga el agent remoto)

Notas operativas:
1. El sandbox puede responder "You said ..."; ignorarlo (no afecta el modo poll/agent).
2. El bridge responde por WhatsApp solo comandos de lista blanca.
3. No usar la palabra `stop` por WhatsApp al sandbox: Twilio la interpreta y desconecta tu número.
4. Para cambios de codigo remotos, usar prefijo `codex`, por ejemplo:
   `1234 codex cambia el contraste del dashboard y valida con py_compile`.

## 8) Go-live cauciones reales (solo caucion, sin arbitraje)
Objetivo: arrancar con riesgo minimo y trazabilidad completa.

Pre-condiciones obligatorias (T-1):
1. `python preflight_operativo.py` debe dar `READY`.
2. Instalar dependencia base: `python -m pip install python-dotenv` (solo una vez).
3. Dashboard:
   - `Modo bot` = `SOLO CAUCIONES`
   - `EJECUCION` = `PAPER` para prueba final de 30-60 min sin errores.
4. Verificar que existan tablas de auditoria en DB al menos una vez ejecutando:
   - `python -c "from motor_cauciones import crear_tabla_cauciones_simuladas; crear_tabla_cauciones_simuladas(); print('OK')"`

Checklist de arranque (dia D):
1. Iniciar sesion: `python lanzar_sesion.py start --mode both`
2. Confirmar procesos: `python lanzar_sesion.py status`
3. Confirmar en dashboard:
   - `SOLO CAUCIONES`
   - bot `ON`
4. Revisar logs en vivo:
   - Snapshot rapido (recomendado): `Get-Content logs\\sesion_bot.log -Tail 120`
   - Dashboard snapshot: `Get-Content logs\\sesion_dashboard.log -Tail 80`
   - Solo si queres seguimiento continuo: `Get-Content logs\\sesion_bot.log -Wait` (cortar con `Ctrl + C`)
5. Que mirar en el log del bot:
   - errores `TOKEN_INVALIDO`, `HTTP 500`, `timeout`, `Sin tasa real IOL`
   - linea de ciclo con `MODO FORZADO: CAUCION | EJEC: REAL`
   - presencia de `Sin señal` vs eventos de orden real (canario)

Configuracion minima para habilitar REAL (en `datos/dashboard_config.json`):
```json
{
  "modo_forzado_bot": "caucion",
  "execution_mode": "real",
  "real_caucion_enabled": true,
  "real_caucion_backend": "web",
  "real_caucion_canary_mode": true,
  "real_caucion_canary_amount_ars": 1000.0,
  "real_caucion_max_monto_ars": 5000.0,
  "real_caucion_browser": "edge",
  "real_caucion_headless": false
}
```
Notas:
1. Si `execution_mode=real` y `modo_forzado_bot` no es `caucion`, el bot bloquea la operativa.
2. Si `real_caucion_enabled=false`, el bot no envia ordenes reales.
3. Empezar con canario (`real_caucion_canary_mode=true`) y subir monto gradualmente.
4. `CPD/CHPD` no aplica a cauciones; la caucion real de IOL quedo confirmada como flujo web.

Cierre de rueda y comparacion:
1. Ejecutar reporte:
   - `python reporte_cauciones_real_vs_sim.py --fecha YYYY-MM-DD`
2. Si hubo desvio sistematico en comisiones/ganancia, ajustar modelo antes del siguiente dia.

Nota critica:
1. El ejecutor real ya esta integrado con guardas de seguridad e idempotencia, pero el endpoint de colocacion puede variar por cuenta/tenant de IOL. Hacer 1 prueba canario y validar fill antes de escalar.
