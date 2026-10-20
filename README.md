# TLRS Backend

Backend de **Manea**, una plataforma GPS/RTLS para el seguimiento de ganado y
otros activos. Recibe telemetría de dispositivos, guarda ubicaciones, evalúa
geocercas y distribuye actualizaciones en tiempo real.

## Qué incluye

- API HTTP y WebSocket con **FastAPI**.
- Persistencia asíncrona en **PostgreSQL** y operaciones geoespaciales con
  **PostGIS**.
- Ingesta de eventos **ChirpStack** mediante MQTT.
- Provisioning de dispositivos y despacho de downlinks a ChirpStack mediante su
  API gRPC.
- Evaluación de geocercas, registro de transiciones y creación automática de
  comandos para dispositivos.
- **Redis Pub/Sub** para distribuir ubicaciones hacia conexiones WebSocket.
- Autenticación con tokens, sesiones persistidas, permisos RBAC y alcance por
  cliente.

## Arquitectura resumida

```text
Dispositivo LoRaWAN
    -> ChirpStack / broker MQTT
    -> chirpstack_event_worker
    -> PostgreSQL + PostGIS
         -> evaluación de geocercas -> eventos -> comandos pendientes
         -> Redis Pub/Sub -> FastAPI -> WebSocket autorizado

Comandos pendientes
    -> command_dispatcher_worker
    -> ChirpStack gRPC downlink
    -> ACK de red y ACK de aplicación
```

La API, el worker de eventos y el worker de comandos son procesos separados.
Redis y PostgreSQL comparten estado entre procesos; las conexiones WebSocket se
manejan en la instancia de FastAPI que las acepta.

## Requisitos

- Python 3.12 o superior para desarrollo local.
- Docker y Docker Compose v2 para levantar servicios locales y la base de
  integración.
- Una base PostgreSQL accesible; las funciones de geocerca requieren PostGIS.
- Credenciales y configuración del entorno de ChirpStack/EMQX para probar
  dispositivos reales.

La configuración de `docker-compose.yml` es de desarrollo. Postgres y
ChirpStack/EMQX se configuran como dependencias externas; Redis se incluye en el
compose.

## Configuración local

```bash
cp .env.example .env
```

Edita `.env` con los valores de tu entorno. En particular, configura:

- `DATABASE_URL`: conexión PostgreSQL con PostGIS accesible desde el proceso o
  contenedor.
- `REDIS_URL`: dirección de Redis; el valor depende de si ejecutas el backend
  dentro o fuera de Docker.
- `MQTT_HOST`, `MQTT_PORT` y credenciales para el broker utilizado.
- `CHIRPSTACK_MQTT_*` para consumir eventos de dispositivos.
- `CHIRPSTACK_API_*` para provisioning y downlinks.
- `JWT_SECRET_KEY` y `CREDENTIAL_ENCRYPTION_KEY` con valores seguros.
- `CORS_ALLOWED_ORIGINS` con los orígenes del frontend.

`.env.example` contiene placeholders, no credenciales funcionales

## Ejecutar la aplicación

El compose principal levanta FastAPI, los dos workers y Redis:

```bash
docker compose up --build -d
```

El compose espera que exista la red Docker externa configurada por
`MANEA_CHIRPSTACK_SHARED_NETWORK` (por defecto `manea_chirpstack_shared`) para
comunicarse con los servicios de ChirpStack. Si tu entorno usa otra red, define
esa variable en `.env`.

Si esa red todavía no fue creada por el entorno de ChirpStack, puedes crearla
antes de levantar el backend:

```bash
docker network create manea_chirpstack_shared
```

Para ver los logs:

```bash
docker compose logs -f backend chirpstack-event-worker command-dispatcher-worker
```

La API local queda disponible en `http://localhost:8000`; Swagger UI está en
`http://localhost:8000/docs`.

Las migraciones se gestionan con Alembic y deben ejecutarse contra la base
configurada para el entorno:

```bash
.venv/bin/python -m alembic upgrade head
```

## Ejecutar los tests

Instala las dependencias de la aplicación y las de test en el entorno virtual:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-test.txt
```

### Tests rápidos

No requieren Docker ni una conexión a Supabase. Las pruebas de PostgreSQL/PostGIS
se omiten si no se solicita explícitamente la base de integración:

```bash
scripts/run-tests.sh
```

### Tests de integración con PostgreSQL/PostGIS

Este comando crea un contenedor de test local y desechable, ejecuta las
migraciones Alembic desde cero, corre las pruebas de integración y elimina el
contenedor al finalizar:

```bash
scripts/run-integration-tests.sh
```

### Suite completa

Ejecuta los tests rápidos y, después, los tests de integración en Docker:

```bash
scripts/run-all-tests.sh
```

También se puede correr un archivo o test concreto:

```bash
.venv/bin/python -m pytest tests/test_chirpstack_binary_contract.py -q
.venv/bin/python -m pytest 'tests/test_chirpstack_binary_contract.py::test_encode_supported_commands[set-report-interval]' -q
```

La configuración de integración solo acepta la base local `tlrs_test`, el
usuario `tlrs_test` y el puerto `55432`; rechaza otros destinos para prevenir
que los tests operen accidentalmente sobre una base de desarrollo o producción.

## Estructura del proyecto

```text
src/
  application/       Casos de uso y lógica de aplicación
  integrations/      Contratos e integración con ChirpStack
  models/            Modelos SQLAlchemy
  realtime/          Gestión de WebSockets y distribución local
  routers/           Endpoints HTTP y WebSocket
  schemas/           Contratos Pydantic
  service/           Servicios de dominio
  db/                Engine y sesiones asíncronas

chirpstack_event_worker/       Ingesta de eventos MQTT
command_dispatcher_worker/     Despacho de downlinks
alembic/                       Migraciones de base de datos
tests/                         Tests unitarios, de API e integración
```

## CI

GitHub Actions instala las dependencias y ejecuta la suite completa con un
servicio PostgreSQL/PostGIS aislado en cada ejecución.
