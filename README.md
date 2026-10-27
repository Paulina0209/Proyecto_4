# Copiloto clínico para oncología

## Arrancar (cualquier máquina con Docker)

```bash
cp .env.example .env          # pon tu OPENAI_API_KEY
docker compose up -d --build  # https://localhost:8443 · dra.gomez / Demo-Clave-2026
docker compose up -d --scale app=4   # más réplicas (NFR-05)
```

Todo va en la imagen: Python, dependencias con versión fija y navegador. La primera vez descarga la base de
cBioPortal. Detalle en `docs/docker.md`. Sin Docker: `pip install -r requirements.txt` y `python -m frontend.real`.

---

# Archivos para cargar el backlog en GitHub

- `backlog_copiloto_oncologico.md`: documento original sin cambios.
- `backlog_github_projects.csv`: las 39 historias en formato tabular.
- `backlog_github_projects.json`: datos usados por el script.
- `importar_backlog_github.ps1`: crea las 39 historias como Issues y las agrega a un GitHub Project existente.

El script no crea etiquetas, historias adicionales ni contenido clínico nuevo.
