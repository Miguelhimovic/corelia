---
name: project-tool-execution-model-missing
description: SPEC.md seccion 5 declara la entidad ToolExecution (lead_id, tool_name, input, output, status, timestamp) pero no existe modelo/migracion/persistencia -- detectado en cierre de sesion Fase 3, 2026-08-14
metadata:
  type: project
---

Detectado en la revision de cierre de sesion de Fase 3 (tools + handle_message), 2026-08-14,
segunda mirada mas fria (no visto en las dos pasadas anteriores del mismo dia).

**Que falta:** `SPEC.md` seccion 5 (arbol del modelo de datos) lista `ToolExecution (lead_id,
tool_name, input, output, status, timestamp)` como hija de `Lead`, al mismo nivel que
`Appointment` y `HumanHandoff`. `HumanHandoff` SI se construyo en Fase 3 (`app/models/human_handoff.py`
+ migracion `a527a85a6c88`). `Appointment` esta legitimamente diferida a Fase 5 (Calendar, no
construido todavia, sin ambiguedad). `ToolExecution` en cambio es infraestructura generica que
aplicaria a los 4 tools que SI se construyeron hoy (`create_lead`, `update_lead`,
`search_database`, `handoff_human`) -- ninguno de los 4 escribe en una tabla `ToolExecution`, no
existe `app/models/tool_execution.py`, no hay migracion, y SPEC.md no tiene ninguna nota que
declare este diferimiento como decision consciente (a diferencia de como si se documenta el
diferimiento de Calendar/WhatsApp en otras secciones).

**Por que no bloquea las tools individuales:** DoD item 5 (SPEC.md seccion 10, "logs
estructurados... tool, tool_result...") SI esta satisfecho -- cada uno de los 4 tools llama
`logger.info/warning/error(..., extra={"tool": ..., "tool_result": ...})` con los campos
correctos (verificado leyendo `create_lead.py`, `update_lead.py`, `search_database.py`,
`handoff_human.py`). El log estructurado cubre el requisito de auditoria de eventos, aunque no
exista la tabla persistida que SPEC.md seccion 5 declara.

**Por que si es un hallazgo real:** es el mismo patron que
[[feedback-ambiguedades-resueltas-en-codigo-no-vuelven-a-spec]] pero al reves -- en vez de una
resolucion de ambiguedad que no vuelve a SPEC.md, es una entidad de SPEC.md que nunca se resolvio
ni se marco como diferida. Si se deja asi, la proxima fase (RAG/Calendar) puede asumir que
`ToolExecution` ya existe porque SPEC.md lo declara sin salvedad.

**Recomendacion para la proxima sesion:** o bien (a) construir un modelo minimo `ToolExecution`
+ migracion y conectar los 4 tools existentes a el, o (b) agregar una nota explicita en SPEC.md
seccion 5 junto a la entrada de `ToolExecution` diciendo que en MVP la auditoria de tool calls
vive solo en logs estructurados (sin tabla persistida) y que la tabla es Fase 2/3 post-cliente --
igual que se hizo con Appointment/Calendar. Cualquiera de las dos cierra el gap; lo que no es
aceptable es dejarlo como esta (documentado como si existiera, sin existir y sin nota de
diferimiento).

**Estado:** ABIERTO al cierre de la sesion de Fase 3, 2026-08-14. No bloqueo del veredicto global
de hoy (los 4 tools cumplen su propio contrato de SPEC.md seccion 4 y su propio DoD item 5 via
logs), pero senalarlo en la proxima revision que toque `app/tools` o el modelo de datos si sigue
sin resolverse.
