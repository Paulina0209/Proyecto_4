# NFR-05 — Escalabilidad horizontal

> Como administrador, quiero que la arquitectura escale horizontalmente, para
> soportar el crecimiento en número de pacientes e instituciones sin degradar
> el rendimiento.

El backlog la marcaba como *Won't Have (por ahora)*. Se implementó lo que se
necesita para que el sistema escale agregando procesos, y se documenta el
límite siguiente. Criterios de aceptación definidos:

```
AC1  Varios procesos atienden la misma API detrás del mismo puerto (o de un balanceador)
AC2  La capacidad crece al agregar procesos, sin errores y dentro de los objetivos de NFR-01
AC3  Las réplicas no guardan estado propio: cualquier réplica atiende a cualquier usuario
```

## Cómo se escala

```powershell
python -m seguridad.servidor_tls --app frontend.servidor:app --workers 4 --cert ... --key ...
```

- `--workers N` levanta N procesos que comparten el puerto, cada uno con el
  mismo contexto TLS (`FabricaContextoTLS` se puede pasar a los procesos
  hijos, cosa que una lambda no permite en Windows).
- **Sesiones compartidas.** Con más de un proceso, las sesiones de la interfaz
  pasan a `data/sesiones.db` (`AlmacenSesionesSQLite`, o la ruta de
  `COPILOTO_SESIONES_DB`). Así cualquier réplica reconoce la sesión que abrió
  otra, cerrar sesión en una la cierra en todas y reiniciar no saca a nadie.
  Se guarda el hash del token, igual que en memoria.
- **Varias máquinas.** Un balanceador reparte el tráfico y usa
  `/salud/listo` (NFR-02) para sacar a una réplica que no está lista. Las
  bases y las sesiones deben estar en un almacenamiento que vean todas.

## Medido (`python -m operacion.carga --usuarios 50 --workers 1` / `--workers 2`)

| 50 médicos a la vez | 1 proceso | 2 procesos |
|---|---|---|
| Peticiones por segundo | ≈ 440 | ≈ 625 (+42 %) |
| p95 | ≈ 150 ms | ≈ 115 ms |
| Errores | 0 | 0 |

No es el doble porque todos los procesos leen el mismo archivo SQLite en el
mismo disco, y porque el cliente de la prueba corre en la misma máquina.

## El límite siguiente

SQLite admite muchos lectores pero **un solo escritor a la vez**. WAL y la
espera por bloqueo hacen que eso no falle, pero las escrituras se encolan. Y
todas las réplicas necesitan ver el mismo archivo. Para varias instituciones o
varias máquinas, el paso siguiente es:

1. Mover las bases a un motor cliente-servidor (PostgreSQL). Las consultas son
   SQL estándar en su mayoría; los triggers de solo inserción tienen
   equivalente.
2. Mover las sesiones a Redis (la interfaz `AlmacenSesiones` es de cuatro métodos).
3. Separar los datos por institución (esquema o base por institución).

## Pruebas y demo

```powershell
python -m pytest tests/operacion/test_escalabilidad.py tests/frontend/test_replicas.py -q
python demo_operacion.py --solo nfr05
```
