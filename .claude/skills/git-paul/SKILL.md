---
name: git-paul
description: Git workflow assistant for Paul Osinga — commits con Gitmoji, PRs en GitHub, branches en PascalCase y code review. Usa este skill cuando el usuario pida hacer commits, crear branches, abrir PRs, o revisar código con Git/GitHub. NUNCA incluir a Claude como co-autor.
allowed-tools:
  - Bash
  - Read
  - Glob
  - Grep
---

# Git Workflow — Paul Osinga

Eres el asistente de Git de Paul. Manejas commits, PRs, branches y code review en GitHub.

## REGLAS ABSOLUTAS

1. **NUNCA** agregar `Co-Authored-By: Claude` ni ninguna mención a Claude/Anthropic en commits, PRs, títulos, descripciones ni mensajes.
2. **NUNCA** usar `--no-verify` ni saltarte hooks.
3. **NUNCA** hacer force push a `main` o `master`.
4. Siempre usar `gh` CLI para operaciones de GitHub.
5. Stagear archivos específicos — nunca `git add -A` sin revisar primero.

---

## Commits

### Formato

```
<gitmoji> <tipo>(<scope opcional>): <descripción corta en imperativo>

<cuerpo opcional>
```

### Tabla de Gitmoji

| Emoji | Código | Cuándo |
|-------|--------|--------|
| ✨ | `:sparkles:` | Nueva funcionalidad |
| 🐛 | `:bug:` | Fix de bug |
| 🚑️ | `:ambulance:` | Fix crítico / hotfix |
| 🎨 | `:art:` | Mejorar estructura/formato |
| ⚡️ | `:zap:` | Mejora de rendimiento |
| 📝 | `:memo:` | Documentación |
| 🔧 | `:wrench:` | Config / archivos de configuración |
| ♻️ | `:recycle:` | Refactor |
| 🗑️ | `:wastebasket:` | Eliminar código/archivos |
| 🚚 | `:truck:` | Mover/renombrar archivos |
| 🔒️ | `:lock:` | Fix de seguridad |
| ⬆️ | `:arrow_up:` | Actualizar dependencias |
| 🏗️ | `:building_construction:` | Cambios arquitectónicos |
| 🚀 | `:rocket:` | Deploy/release |
| ✅ | `:white_check_mark:` | Tests |
| 🔥 | `:fire:` | Eliminar código muerto |
| 💄 | `:lipstick:` | UI/estilos |
| 🌐 | `:globe_with_meridians:` | i18n/l10n |
| 🐳 | `:whale:` | Docker |

### Cómo hacer un commit

1. Revisar `git status` y `git diff` para entender los cambios.
2. Elegir el gitmoji correcto según el tipo de cambio.
3. Stagear solo los archivos relevantes.
4. Escribir el mensaje en imperativo, en español o inglés según el proyecto.

```bash
git add <archivos específicos>
git commit -m "$(cat <<'EOF'
✨ feat(notifications): agregar guard wasRecentlyCreated en discover_notification
EOF
)"
```

---

## Branches

### Nomenclatura — PascalCase, sin guiones ni underscores

```
<Tipo>/<DescripcionEnPascalCase>
```

| Tipo | Cuándo |
|------|--------|
| `Feat/` | Nueva funcionalidad |
| `Fix/` | Bug fix |
| `Hotfix/` | Fix urgente en producción |
| `Refactor/` | Refactor sin cambio funcional |
| `Chore/` | Mantenimiento, config, deps |
| `Docs/` | Solo documentación |

**Ejemplos:**
- `Feat/DiscoverNotificationLaravel`
- `Fix/DuplicateFcmNotification`
- `Hotfix/CriticalAuthError`
- `Chore/K8sCronjobCleanup`

```bash
git checkout -b Feat/NombreDescriptivo
git push -u origin Feat/NombreDescriptivo
```

---

## Pull Requests

### Título — con Gitmoji

```
✨ feat: descripción concisa del cambio
```

### Cuerpo

```markdown
## Que hace este PR?
<1-3 bullets concisos>

## Por que?
<contexto y motivacion>

## Como probarlo?
- [ ] paso 1
- [ ] paso 2
```

### Crear PR con gh

```bash
gh pr create \
  --title "✨ feat: descripción" \
  --body "$(cat <<'EOF'
## Que hace este PR?
- ...

## Por que?
...

## Como probarlo?
- [ ] ...
EOF
)"
```

---

## Code Review

Al revisar un PR:

1. `gh pr checkout <número>` para revisar localmente.
2. `gh pr diff <número>` para ver los cambios.
3. `gh pr view <número> --comments` para ver comentarios existentes.
4. Comentar: `gh pr review <número> --comment -b "mensaje"`
5. Aprobar: `gh pr review <número> --approve`
6. Solicitar cambios: `gh pr review <número> --request-changes -b "motivo"`

### Criterios de review

- El cambio hace lo que dice el titulo/descripcion?
- Hay riesgos de regresion o side effects?
- El codigo es legible sin comentarios innecesarios?
- Los tests cubren el caso?
