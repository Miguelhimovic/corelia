#!/bin/bash
# PostToolUse hook: corre tests automáticamente cuando se edita el core del agente.
# Exit 2 no deshace el cambio (PostToolUse ya se ejecutó), pero le devuelve el error
# a Claude por stderr para que lo corrija en su siguiente turno.

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if echo "$FILE" | grep -qE 'app/(agent_engine|rag|tools)/.*\.py$'; then
  pytest tests/ -q --tb=short
  if [ $? -ne 0 ]; then
    echo "Tests fallando después de editar $FILE. No reportes la tarea como terminada hasta que pasen." >&2
    exit 2
  fi
fi

exit 0
