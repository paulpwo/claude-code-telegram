# Roadmap — paulpwo/claude-code-telegram

Fork de `RichardAtCT/claude-code-telegram` orientado a un workflow **SDD (Spec-Driven Development)** donde el bot actúa como analista técnico remoto.

---

## Contexto y objetivo

Bridge directo Telegram → Claude Code orientado a un workflow SDD donde el bot actúa como analista técnico remoto.

**El workflow objetivo:**
```
GitHub Issue / mensaje Telegram
        ↓
Bot (Claude Code remoto)
  → Analiza el repo
  → Infiere tipo y crea rama {Tipo}/Issue{N}{Slug}
  → Escribe .agent/planning/sdd.md
  → Escribe .agent/context/files.md
  → Escribe .agent/context/approach.md
  → Commitea y pushea
  → Notifica por Telegram: "rama lista"
        ↓
Paul localmente
  → git pull
  → Claude Code local lee los .agent/ docs
  → Ejecuta el fix
```

---

## Features planificadas

### Feature 1 — Comando `/sdd` (PRIORIDAD ALTA)

**Qué hace:**
Comando dedicado que ejecuta el workflow SDD completo en un solo paso.

**Uso esperado:**
```
/sdd https://github.com/paulpwo/portfolio/issues/5
/sdd Agregar dark mode al portfolio
```

**Flujo:**
1. Parsea el input (URL de issue o descripción libre)
2. Si es URL: lee el issue via `gh issue view`
3. Determina el repo a analizar (por thread activo o argumento)
4. Infiere el tipo de rama del issue (`Feat/`, `Fix/`, `Chore/`, etc.) y crea `{Tipo}/Issue{N}{DescripcionEnPascalCase}` (ej: `Feat/Issue5DarkMode`, `Fix/Issue12AuthRedirect`)
5. Explora el repo: estructura, archivos relevantes, contexto del problema
6. Escribe bajo `.agent/`:
   - `planning/sdd.md` — spec: qué hay que hacer, criterios de aceptación
   - `context/files.md` — archivos relevantes y su rol
   - `context/approach.md` — enfoque sugerido con alternativas y tradeoffs
7. `git commit` con Gitmoji (`📝 docs(analysis): agregar pre-análisis issue #N`) + `git push`
8. Responde en Telegram con resumen y nombre de la rama

**Restricciones del comando:**
- NO modifica código existente — solo escribe bajo `.agent/`
- NO abre PRs
- NO ejecuta tests ni builds

**Archivos a crear/modificar:**
- `src/bot/handlers/sdd_handler.py` — handler principal
- `src/bot/orchestrator.py` — registrar el comando
- `src/config/settings.py` — config `SDD_PROTECTED_BRANCHES`
- `src/config/features.py` — feature flag `ENABLE_SDD`

**Prompt base para Claude Code:**
```
Analizá el repo en {working_dir}. 
Contexto de la tarea: {issue_content}

Instrucciones:
1. Inferí el tipo de trabajo del issue (Feat, Fix, Chore, etc.) y creá la rama `{Tipo}/Issue{N}{DescripcionEnPascalCase}`
2. Explorá el repo — entendé la estructura y los archivos relevantes
3. Escribí en .agent/planning/sdd.md el spec completo
4. Escribí en .agent/context/files.md los archivos relevantes y su rol
5. Escribí en .agent/context/approach.md el enfoque sugerido con alternativas
6. Commitea los archivos .agent/ y pusheá la rama
7. NO modifiques código existente
```

---

### Feature 2 — Git Safety (PRIORIDAD ALTA)

**Qué hace:**
Bloquea operaciones git destructivas a nivel de middleware, independientemente de lo que Claude decida hacer.

**Config nueva:**
```env
GIT_PROTECTED_BRANCHES=main,develop,master
GIT_ALLOW_FORCE_PUSH=false
GIT_ALLOW_DELETE_BRANCH=false
```

**Implementación:**
- Interceptar en `ToolMonitor` (`src/claude/tool_monitor.py`) las llamadas Bash que contengan:
  - `git push origin main` / `git push origin develop`
  - `git push --force` / `git push -f`
  - `git branch -D`
  - `git reset --hard` en ramas protegidas
- Lanzar excepción con mensaje claro: "Push a rama protegida bloqueado"

**Archivos a modificar:**
- `src/claude/tool_monitor.py` — agregar validación git
- `src/config/settings.py` — agregar `GIT_PROTECTED_BRANCHES`

---

### Feature 3 — GitHub Issue Polling (PRIORIDAD MEDIA)

**Qué hace:**
Job programado que detecta issues nuevos en repos configurados y dispara el análisis SDD automáticamente, sin que Paul tenga que mandarlo por Telegram.

**Config nueva:**
```env
ENABLE_ISSUE_POLLING=true
GITHUB_POLLING_REPOS=paulpwo/portfolio,paulpwo/otro-repo
GITHUB_POLLING_INTERVAL_MINUTES=15
GITHUB_POLLING_LABEL=sdd-analyze   # solo issues con este label
```

**Flujo:**
1. APScheduler corre cada N minutos
2. Consulta `gh issue list --state open --label sdd-analyze` para cada repo
3. Filtra issues que no hayan sido procesados (tabla nueva en SQLite: `processed_issues`)
4. Para cada issue nuevo: dispara el workflow `/sdd` automáticamente
5. Notifica por Telegram que empezó el análisis

**Archivos a crear/modificar:**
- `src/scheduler/github_poller.py` — job nuevo
- `src/storage/` — tabla `processed_issues`
- `src/config/settings.py` — config polling

---

### Feature 4 — Send Voice / TTS (PRIORIDAD MEDIA)

**Qué hace:**
Claude responde con nota de voz además de texto cuando el usuario lo pide o cuando la respuesta es corta.

**Stack elegido:**
- TTS: `edge-tts` (ya instalado en el sistema, voz `es-AR-TomasNeural`)
- Envío: Telegram `sendVoice` API (OGG/Opus)
- Script existente: `~/.claude/scripts/text-to-voice.sh` + `~/.claude/scripts/send-voice-telegram.sh`

**Activación:**
- Comando `/voice on|off` por sesión
- O automático para respuestas < 200 palabras cuando `VOICE_REPLIES=auto`

**Config nueva:**
```env
ENABLE_VOICE_REPLIES=false          # off por defecto
VOICE_REPLY_MAX_WORDS=200           # límite para auto-mode
EDGE_TTS_VOICE=es-AR-TomasNeural
```

**Archivos a crear/modificar:**
- `src/bot/features/voice_handler.py` — agregar clase `VoiceSender`
- `src/bot/orchestrator.py` — comando `/voice`
- `src/config/settings.py` — config TTS

---

## Configuración de voice local (whisper)

El proyecto ya soporta whisper.cpp local. Config para este entorno:

```env
ENABLE_VOICE_MESSAGES=true
VOICE_PROVIDER=local
WHISPER_CPP_BINARY_PATH=/opt/homebrew/bin/whisper-cli
WHISPER_CPP_MODEL_PATH=/Users/developer/.local/share/whisper/ggml-medium.bin
```

---

## Deploy en VM (paso final)

Cuando las features estén estables en local, reemplazar OpenClaw en la VM.

**VM actual:** AWS EC2 t3.small, Ubuntu 22.04, IP 23.20.232.38

**Plan de deploy:**
1. `pm2 stop openclaw` en la VM
2. Clonar el fork: `git clone git@github.com:paulpwo/claude-code-telegram.git`
3. Crear venv Python + instalar dependencias
4. Configurar `.env` con tokens de producción
5. Configurar PM2: `pm2 start .venv/bin/claude-telegram-bot --name claude-telegram`
6. Configurar branch protection en GitHub (main, develop)
7. Verificar con `/sdd` desde Telegram

**Repos a configurar en APPROVED_DIRECTORY:**
- `/home/ubuntu/repos` (igual que la config de OpenClaw anterior)

---

## Orden de implementación sugerido

```
Feature 2 (git safety)   → base de seguridad, rápido de hacer
Feature 1 (/sdd)         → el core del workflow
Feature 3 (issue polling) → automatización
Feature 4 (voice TTS)    → UX mejorada
Deploy VM                → producción
```

---

## Convenciones Git (git-paul)

Aplican tanto para el desarrollo de este repo como para los commits que el bot genera en los repos analizados.

### Branches — PascalCase

```
<Tipo>/<DescripcionEnPascalCase>
```

| Tipo | Cuándo |
|------|--------|
| `Feat/` | Nueva funcionalidad |
| `Fix/` | Bug fix |
| `Refactor/` | Refactor sin cambio funcional |
| `Chore/` | Config, deps, mantenimiento |
| `Docs/` | Solo documentación |
**Ejemplos para este repo:**
- `Feat/SddCommand`
- `Fix/GitSafetyProtectedBranches`
- `Feat/VoiceTtsReplies`

**Ejemplos generados por el bot en repos analizados:**
- `Feat/Issue5DarkMode` — issue de nueva feature
- `Fix/Issue12AuthRedirect` — issue de bug
- `Chore/Issue8UpdateDeps` — mantenimiento

### Commits — Gitmoji + imperativo

```
<emoji> <tipo>(<scope>): <descripción en imperativo>
```

| Emoji | Cuándo |
|-------|--------|
| ✨ | Nueva funcionalidad |
| 🐛 | Fix de bug |
| 🔒️ | Fix de seguridad |
| 📝 | Documentación / archivos `.agent/` |
| ♻️ | Refactor |
| 🔧 | Config |
| ✅ | Tests |

**Ejemplos:**
```bash
✨ feat(sdd): agregar comando /sdd con workflow análisis completo
🔒 security(git): bloquear push a ramas protegidas en ToolMonitor
📝 docs(analysis): agregar pre-análisis issue #5 dark mode
```

### Reglas absolutas

- **NUNCA** `Co-Authored-By: Claude` ni menciones a Claude/Anthropic en commits
- **NUNCA** `--no-verify` ni saltarse hooks
- **NUNCA** force push a `main` o `master`
- Stagear archivos específicos — nunca `git add -A` sin revisar

---

## Sync con upstream

Cuando `RichardAtCT` saque updates:
```bash
git fetch upstream
git merge upstream/main
```

Conflictos esperados en: `src/bot/orchestrator.py`, `src/config/settings.py`
