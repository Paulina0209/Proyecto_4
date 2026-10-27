# Copiloto oncológico con Docker (NFR-05: escalabilidad horizontal)

Una sola imagen con **todas** las dependencias: Python 3.13, las librerías de `requirements.txt` con versión
fija y Chromium para EV-02 y las pruebas de accesibilidad. Funciona igual en cualquier máquina con Docker:
no hay que instalar Python ni nada más.

## Arrancar

```bash
cp .env.example .env            # y pon tu OPENAI_API_KEY (sin llave, el asistente responde por reglas)
docker compose up -d --build
```

La primera vez, el servicio `preparar` descarga la base de cBioPortal (unos minutos). Se puede seguir con
`docker compose logs -f preparar`. Cuando termina, arrancan las réplicas y el balanceador:

- Interfaz: **https://localhost:8443**. El certificado es autofirmado, así que el navegador muestra un aviso
  la primera vez.
- Usuarios: los del escenario, con la contraseña de demostración `Demo-Clave-2026` (`dra.gomez`, `enf.mora`,
  `adm.lopez`, `admin.copiloto`…). `docker compose logs preparar` los lista.

## Cómo está armado

```
                    ┌────────────── volumen «datos» (bases, documentos, índice, sesiones) ─────────────┐
navegador ─TLS─▶ balanceador (nginx) ─TLS─▶ app (réplica 1) ┐
                                         ─TLS─▶ app (réplica 2) ├─ cada una con COPILOTO_WORKERS procesos
                                         ─TLS─▶ app (réplica N) ┘
                 preparar (una vez): capas de cBioPortal, escenario, certificado, clave e índice
```

| Servicio | Qué hace |
|---|---|
| `preparar` | Corre una vez y termina: `python -m frontend.real --solo-preparar` |
| `app` | Las réplicas que atienden: `python -m frontend.real --sin-preparar`. Comparten datos y **sesiones** (`COPILOTO_SESIONES_DB`), así que cualquier réplica atiende a cualquier usuario y una puede caer sin cerrar sesiones |
| `balanceador` | nginx en modo *stream*: reparte las conexiones sin abrir el TLS, así el cifrado va de punta a punta (SEC-02) y nginx no ve datos clínicos |

Volúmenes: `datos` (todo lo que cambia) y `secretos` (la clave de cifrado en reposo, aparte, para que una
copia de los datos no se lleve la clave).

## Escalar (NFR-05)

```bash
docker compose up -d --scale app=4              # 4 réplicas, sin detener el servicio
COPILOTO_REPLICAS=3 COPILOTO_WORKERS=4 docker compose up -d
```

El balanceador consulta las réplicas cada 10 segundos: las nuevas entran solas al reparto. Para ver qué
réplica atiende cada vez:

```bash
curl -sk https://localhost:8443/salud/vivo      # {"estado": "vivo", "instancia": "<réplica>"}
```

## Variables

| Variable | Por defecto | Para qué |
|---|---|---|
| `COPILOTO_REPLICAS` | 2 | Réplicas de `app` |
| `COPILOTO_WORKERS` | 2 | Procesos por réplica |
| `COPILOTO_PUERTO_PUBLICO` | 8443 | Puerto en la máquina anfitriona |
| `COPILOTO_TLS_CERT` / `COPILOTO_TLS_KEY` | — | Certificado propio de la institución (ruta dentro del contenedor, por ejemplo en el volumen `datos`); sin ellos se genera uno autofirmado |
| `COPILOTO_CLAVE_CIFRADO` | — | Clave de cifrado inyectada por el gestor de secretos; sin ella se crea una en el volumen `secretos` |
| `OPENAI_API_KEY`, `OPENAI_MODEL`… | — | Las de `.env` (ver `.env.example`) |

## Tareas dentro del contenedor

```bash
docker compose run --rm app python -m pytest -q          # la suite completa, con navegador incluido
docker compose run --rm app python -m datos estado       # qué hay en cada capa de datos
docker compose run --rm app python -m asistente indexar  # rehacer el índice del asistente
docker compose run --rm app python -m guidelineUpdate.main   # EV-02: buscar versiones nuevas de las guías
```

## Límites

- **Un solo anfitrión.** Las réplicas comparten bases SQLite en un volumen local: escala dentro de una
  máquina (más réplicas y procesos), no entre varias. Para varias máquinas, las bases tendrían que pasar a un
  servidor (PostgreSQL) y el índice del asistente a Chroma en modo servidor.
- **PACS.** Orthanc no va en el `docker-compose`: el sistema solo acepta PACS por HTTPS fuera de la propia
  máquina (SEC-02). Sin PACS, la interfaz lo dice y muestra los informes del expediente.
- **Ollama** (modelo local) tampoco va incluido: se configura con `COPILOTO_LLM_PROVEEDOR=ollama` y `OLLAMA_URL`.
