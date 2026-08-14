# MARCA.md — Manual de Marca CoreliA

Contrato de identidad visual y tono de voz, extraído de `Manual_de_Marca_CoreliA.docx`. Referenciado desde `CLAUDE.md` — se aplica en `/web` (landing pages, homepage, widget de Web Chat) y en cualquier propuesta comercial o material de marketing.

**Slogan:** "Inteligencia en el core de cada conexión."

---

## 1. Colores (con variables CSS listas para usar)

| Nombre | HEX | Significado / uso |
|---|---|---|
| Cobalt Core | `#00205B` | Estabilidad, confianza institucional, infraestructura crítica. Color que convence a directivos. Uso: H1, texto de marca sobre fondos claros. |
| Electric Cyan | `#00D4FF` | Innovación, IA, velocidad, datos en movimiento. Uso: H2, detalles, ícono/pulso, botones. |
| Pure White | `#FFFFFF` | Claridad y transparencia. Uso: texto sobre fondos oscuros. |
| Gris Carbón | `#333333` | Cuerpo de texto, máxima legibilidad. |

```css
:root {
  --corelia-cobalt: #00205B;
  --corelia-cyan: #00D4FF;
  --corelia-white: #FFFFFF;
  --corelia-carbon: #333333;
  --corelia-gradient: linear-gradient(to right, #00205B, #00D4FF);
}
```

**Degradado:** permitido únicamente en el ícono de la onda (izquierda a derecha, Cobalt Core → Electric Cyan, simula transmisión de datos) y como fondo de botones/UI (ver jerarquía). No usarlo libremente en otros elementos.

---

## 2. Tipografía

- **Principal (titulares, logo):** Montserrat — fallback Gilroy. Sans-serif geométrica, trazos limpios; evoca confiabilidad Telco manteniendo accesibilidad de CX.
- **Secundaria (cuerpo, contratos, sitio web):** Inter — fallback Open Sans. Optimizada para pantalla y lectura rápida de datos complejos.

## 3. Sistema de jerarquía (web y propuestas comerciales)

| Elemento | Fuente | Color |
|---|---|---|
| H1 / Titulares | Montserrat/Gilroy ExtraBold | Cobalt Core `#00205B` |
| H2 / Subtítulos | Montserrat SemiBold | Electric Cyan `#00D4FF` o gris oscuro |
| Cuerpo de texto | Inter Regular | Gris Carbón `#333333` |
| Botones / UI | Montserrat Medium | Texto blanco sobre degradado Cobalt → Cyan |

## 4. Modo oscuro

Fondo: Cobalt Core (`#00205B`) o negro.
- Texto "CoreliA" → Blanco Puro (`#FFFFFF`).
- Ícono y pulso de la "A" → Electric Cyan (`#00D4FF`) con efecto de brillo/luminancia (glow), como neón.

## 5. Restricciones (usos incorrectos — no negociable)

1. **Nunca deformar** el logo (sin estirar/comprimir desproporcionadamente).
2. **El pulso de la "A" nunca en rojo** (parece emergencia médica) **ni en verde** (parece marca ecológica) — siempre Cian.
3. **No usar fondos rojo, naranja o verde** detrás del logo (compiten con la identidad).
4. **No eliminar el slogan arbitrariamente** — solo se omite en redes sociales o espacios menores a 3cm.

## 6. Tono de voz

CoreliA habla como un **Arquitecto Visionario**:
- **Técnicos:** usa los términos correctos (latencia, NPS, API) — no los evita ni los simplifica de más.
- **Humanos:** siempre explica el beneficio para la persona detrás del dato, no se queda en lo abstracto.
- **Seguros:** no dice "creemos que", dice "la data nos indica".

**Manifiesto breve:** "En un mundo hiperconectado, la diferencia entre una señal y una relación es la inteligencia. En CoreliA, no solo gestionamos infraestructura; inyectamos vida al sistema nervioso de tu empresa."

Este tono aplica al revisar/ajustar el copy ya escrito en `Plan_Operativo_14_Dias.md` (landing pages `/legal-ai` y `/real-estate-ai`) antes de que Claude Code las construya — verificar que el lenguaje sea técnico-humano-seguro, no genérico de agencia.
