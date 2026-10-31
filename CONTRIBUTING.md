# Contribuir

Gracias por el interés. El proyecto es pequeño y las reglas son pocas.

## Antes de abrir un PR

- Abre una issue describiendo el problema o la idea. Cambios grandes sin issue
  previa es probable que se queden sin revisar.
- Un PR = un tema. Si mezclas refactor y funcionalidad, se parte.
- Ejecuta lo que toques: el pipeline se puede probar sin cuenta de correo con una
  base de datos de ejemplo, y `python -m py_compile` sobre los ficheros tocados es
  el mínimo exigible.

## Reglas del proyecto

- **Nada de secretos en el repo.** Ni claves, ni contraseñas, ni chat IDs, ni
  correos personales en ejemplos o documentación. Usa variables de entorno o
  marcadores (`CAMBIAME@c.us`).
- **Nada de datos personales.** `data/` está ignorado por diseño; si necesitas
  ejemplos, sécalos antes de subirlos.
- **Sin dependencia obligatoria de servicios de pago.** Cualquier función nueva
  que use un servicio externo debe tener un camino local o una degradación
  explícita. Los errores de plan o de clave (HTTP 401/402/403) se reportan una
  vez y no se reintentan por bisección: dejar ítems pendientes es correcto;
  inventar categorías no.
- **Estilo**: Python 3.11+, sin frameworks nuevos si la stdlib basta. Los cambios
  de esquema de la base de datos van con migración y copia de seguridad previa.
- Los mensajes de commit, en castellano, en imperativo y con prefijo
  (`feat:`, `fix:`, `docs:`, `chore:`).

## Cómo probar sin datos reales

1. `cp .env.example .env` y deja el perfil `local`.
2. Levanta el dashboard y sube un ticket a mano desde la pestaña **📥 Ingesta**.
3. Para la API: `curl -X POST localhost:8060/ingest/ocr` con una foto en
   `data/raw_photos/`.

## Licencia

Al contribuir aceptas que tu aportación se publique bajo la licencia MIT del
proyecto.
