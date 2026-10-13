# SEC-02 — Cifrado en tránsito y en reposo

> Como responsable de seguridad, quiero que los datos viajen y se guarden
> cifrados, para proteger la confidencialidad de la información clínica.

```
Dado cualquier intercambio cliente-servidor
Cuando se transmite información clínica
Entonces viaja exclusivamente sobre una versión vigente de TLS
(sin caer a conexiones sin cifrar)
```

Módulos: `seguridad/tls.py`, `seguridad/servidor_tls.py`, `seguridad/cifrado.py`.

## En tránsito

| Punta | Control | Dónde |
|---|---|---|
| Servidor | TLS 1.2 como mínimo (1.0 y 1.1 están deprecados, RFC 8996). Con TLS 1.2 solo se aceptan suites ECDHE con AES-GCM o ChaCha20. Sin compresión ni renegociación | `contexto_tls_servidor` |
| Servidor | Sin certificado no arranca: no hay modo de respaldo en HTTP | `python -m seguridad.servidor_tls` |
| API | Toda petición que no llega por HTTPS recibe **403** sin procesarse. No redirige, porque con una redirección la primera petición ya habría viajado en claro. Las respuestas HTTPS llevan `Strict-Transport-Security` | `SoloHTTPSMiddleware` en `patients.api` y `administracion.api` |
| Clientes | TLS 1.2 como mínimo, con verificación de certificado y de nombre de host | `contexto_tls_cliente` |
| Integraciones | cBioPortal, PACS (DICOMweb) y visor solo aceptan `https://`. Única excepción: loopback (`localhost`), que no sale de la máquina y es como corre el Orthanc de la demo de HC-03 | `exigir_url_segura` |

Un PACS configurado con `http://` hacia otra máquina se informa en la API
como "integración no disponible" y nunca se consulta en claro.

**Detrás de un proxy** que termina TLS (nginx, un balanceador): uvicorn
con `--proxy-headers --forwarded-allow-ips=<ip del proxy>`. El esquema solo
se toma de `X-Forwarded-Proto` cuando viene de ese proxy, así que un cliente
no puede saltarse el control mandando la cabecera.

```powershell
python -m seguridad.servidor_tls --generar-certificado-local certs/   # autofirmado, solo desarrollo
python -m seguridad.servidor_tls --cert certs/localhost.pem --key certs/localhost-clave.pem
# https://localhost:8443/docs   (--app administracion.api:app para ADM-01)
```

Variables: `COPILOTO_TLS_CERT`, `COPILOTO_TLS_KEY`, `COPILOTO_TLS_KEY_PASSWORD`.

## En reposo

AES-256-GCM (`seguridad.cifrado.Cifrador`): cifrado autenticado con un nonce
aleatorio por operación. Cada cifrado va ligado a un *contexto* como dato
autenticado (p. ej. `documento_clinico:paciente_7`), así que un archivo de un
paciente no se puede hacer pasar por el de otro, y cualquier alteración se
detecta.

| Qué | Cómo |
|---|---|
| Documentos cargados (DOC-01) | `cargar_documento_clinico` escribe el archivo cifrado; `leer_contenido_documento` lo descifra. Los archivos anteriores a SEC-02, que están en claro, se siguen leyendo y el informe de NFR-04 los señala para migrarlos |
| Bases SQLite | `python -m seguridad.cifrado respaldar data/copiloto.db respaldo.cpc` hace una copia consistente (API de backup de SQLite) y cifrada; `restaurar` la descifra a una base nueva |

**Clave.** Se toma, en este orden:

1. de `COPILOTO_CLAVE_CIFRADO` (en producción, inyectada por el gestor de secretos);
2. del archivo indicado en `COPILOTO_ARCHIVO_CLAVE`;
3. de `~/.copiloto_clinico/clave_cifrado`, que se crea la primera vez (para desarrollo).

La clave queda fuera del repositorio y de `data/`. **Si se pierde, lo cifrado
con ella no se recupera.** `python -m seguridad.cifrado generar-clave` genera
una clave nueva.

## Límites conocidos

- Las bases SQLite en uso no van cifradas página a página. Eso requiere
  SQLCipher, que no tiene ruedas para este entorno. En reposo se protegen con
  los respaldos cifrados y con cifrado del volumen (BitLocker/LUKS) en el
  servidor, que es un control de infraestructura.
- Los PDF exportados por DOC-02 no se cifran: son para entregarlos al médico o
  al paciente.
- No hay rotación automática de la clave. El id de clave que va en cada
  archivo permite detectar con qué clave se cifró.

## Pruebas y demo

```powershell
python -m pytest tests/seguridad/test_tls.py tests/seguridad/test_cifrado.py -q
python demo_seguridad_cumplimiento.py --solo sec02
```

`test_tls.py` levanta un uvicorn real con TLS y comprueba que atiende HTTPS
(TLS ≥ 1.2), que rechaza HTTP y que rechaza un cliente con TLS 1.0/1.1.
