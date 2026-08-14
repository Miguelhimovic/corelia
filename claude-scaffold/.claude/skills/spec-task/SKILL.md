---
name: spec-task
description: Ejecuta el flujo de Spec-Driven Development de CorelIA para una tarea de ingeniería, desde verificación de contrato hasta aprobación de QA. Úsalo cuando el usuario pida implementar cualquier funcionalidad descrita en SPEC.md, o invócalo con /spec-task.
---

Flujo obligatorio para implementar cualquier funcionalidad de CorelIA descrita en SPEC.md. No te saltes pasos ni los colapses en uno solo — el punto de este flujo es que ningún agente revise su propio trabajo.

1. **Verificación de contrato** — delega a spec-guardian. Si el contrato está incompleto, detente y repórtalo al usuario; no continúes con supuestos propios.
2. **Descomposición en tareas** — con el contrato confirmado, escribe una lista ordenada de tareas concretas (no más de 5-7) antes de tocar código. Muéstrala al usuario primero si la tarea es grande o ambigua.
3. **Implementación** — delega a engineer, una tarea a la vez. No avances a la siguiente tarea sin que engineer haya corrido sus propios tests básicos primero.
4. **Tests** — delega a test-writer para golden conversations y unit tests. Debe ser una invocación separada de la de engineer, nunca el mismo turno.
5. **QA** — delega a qa-reviewer. Si el veredicto es RECHAZADO, vuelve al paso 3 con la lista específica de lo que falta — no marques la tarea como terminada.
6. **Cierre** — solo cuando qa-reviewer aprueba, actualiza SPEC.md o CLAUDE.md si algún contrato cambió durante la implementación, y reporta al usuario qué se construyó y qué contrato de SPEC.md cubre.

Nunca saltes directo del paso 1 al paso 3.
