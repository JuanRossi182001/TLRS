# ChirpStack Dev Stack on EMQX Cloud

## Objetivo

Esta carpeta levanta ChirpStack real en Docker para desarrollo usando EMQX Cloud como broker MQTT.

No crea Mosquitto.
No expone `1883` local.
No reemplaza la simulacion actual de Fase 1 y Fase 2.

En esta fase:

- ChirpStack corre como servicio independiente.
- ChirpStack usa su propio Postgres.
- ChirpStack usa su propio Redis.
- ChirpStack publica y consume MQTT directamente sobre EMQX Cloud.

## Importante

- No commitear credenciales reales de EMQX Cloud.
- `infra/chirpstack/.env` debe existir solo localmente.
- `EMQX_MQTT_USE_TLS` debe quedar en `true` para esta stack.
- La configuracion de esta carpeta usa `ssl://` hacia EMQX Cloud y no contempla broker sin TLS.

## Estructura

```txt
infra/chirpstack/
  .env.example
  docker-compose.yml
  README.md
  configuration/
    chirpstack/
      chirpstack.toml
      region_au915_0.toml
      region_au915_1.toml
      region_au915_2.toml
      region_us915_0.toml
    postgresql/
      initdb/
        001-chirpstack_extensions.sql
      postgresql.conf
    redis/
      redis.conf
```

## Variables de entorno

Copiar el ejemplo y completar valores reales:

```bash
cp infra/chirpstack/.env.example infra/chirpstack/.env
```

Variables principales:

```txt
CHIRPSTACK_UI_PORT=8080

CHIRPSTACK_POSTGRES_USER=chirpstack
CHIRPSTACK_POSTGRES_PASSWORD=chirpstack
CHIRPSTACK_POSTGRES_DB=chirpstack

CHIRPSTACK_REDIS_HOST=redis
CHIRPSTACK_REDIS_PORT=6379

CHIRPSTACK_API_SECRET=change-me-with-a-random-secret

EMQX_MQTT_HOST=xxxxx.emqxsl.com
EMQX_MQTT_PORT=8883
EMQX_MQTT_USERNAME=chirpstack_server
EMQX_MQTT_PASSWORD=change-me
EMQX_MQTT_USE_TLS=true

LORAWAN_REGION=au915_2
LORAWAN_TOPIC_PREFIX=au915_2
```

Notas:

- `CHIRPSTACK_API_SECRET` debe reemplazarse por un secreto aleatorio.
- `LORAWAN_REGION` define la region habilitada en ChirpStack.
- `LORAWAN_TOPIC_PREFIX` debe coincidir con la region/topico usado por el futuro ChirpStack MQTT Forwarder del gateway.
- Los `.toml` de ChirpStack usan sustitucion nativa de variables de entorno, no hace falta generar archivos intermedios.
- Postgres inicializa `pg_trgm` y `hstore` mediante `docker-entrypoint-initdb.d`, por eso si la base se creo antes de agregar este init hay que recrear el volumen con `down -v`.

## Arranque

Levantar la stack:

```bash
docker compose -f infra/chirpstack/docker-compose.yml --env-file infra/chirpstack/.env up -d
```

Ver logs:

```bash
docker compose -f infra/chirpstack/docker-compose.yml --env-file infra/chirpstack/.env logs -f chirpstack
```

Bajar la stack:

```bash
docker compose -f infra/chirpstack/docker-compose.yml --env-file infra/chirpstack/.env down
```

Reset de desarrollo:

```bash
docker compose -f infra/chirpstack/docker-compose.yml --env-file infra/chirpstack/.env down -v
```

## UI

URL local:

```txt
http://localhost:${CHIRPSTACK_UI_PORT}
```

Credenciales iniciales esperadas de la imagen oficial:

```txt
admin / admin
```

Cambiarlas despues del primer ingreso.

## EMQX Cloud

Usuarios sugeridos:

- `chirpstack_server`
- `chirpstack_gateway`
- `manea_worker`
- `manea_backend`

ACLs conceptuales sugeridas:

`chirpstack_gateway`

```txt
publish:   {topic_prefix}/gateway/+/event/+
subscribe: {topic_prefix}/gateway/+/command/+
```

`chirpstack_server`

```txt
subscribe: {topic_prefix}/gateway/+/event/+
publish:   {topic_prefix}/gateway/+/command/+
publish:   application/+/device/+/event/+
subscribe: application/+/device/+/command/down
```

`manea_worker`

```txt
subscribe: application/+/device/+/event/+
```

`manea_backend`

```txt
publish: application/+/device/+/command/down
```

Validar los topics exactos contra la configuracion final de ChirpStack y del futuro ChirpStack MQTT Forwarder.

## Configuracion regional

Se dejan preparadas estas regiones:

- `au915_0` (sub-banda 1, canales 0-7 + 64)
- `au915_1` (sub-banda 2, canales 8-15 + 65)
- `au915_2` (sub-banda 3, canales 16-23 + 66)
- `us915_0`

La configuracion activa es `au915_2`, que usa las frecuencias de subida
918.4 a 919.8 MHz (125 kHz) y 919.1 MHz (500 kHz). Antes de reiniciar la
stack, alinear los componentes externos:

- Configurar el gateway o ChirpStack MQTT Forwarder para AU915 canales 16-23 +
  66 y usar `au915_2` como `topic_prefix`.
- Cambiar el `region_config_id` de cada Device Profile de ChirpStack a
  `au915_2`.
- Configurar los dispositivos para AU915 canales 16-23 + 66 y forzar un nuevo join
  OTAA despues del cambio.

No asumir una region definitiva hasta que hardware, firmware, gateway y collares esten alineados.

Regla importante:

```txt
LORAWAN_REGION == region habilitada en ChirpStack
LORAWAN_TOPIC_PREFIX == topic_prefix del backend MQTT regional
topic_prefix del gateway forwarder == el mismo LORAWAN_TOPIC_PREFIX
```

## Health checks basicos

Contenedores arriba:

```bash
docker compose -f infra/chirpstack/docker-compose.yml --env-file infra/chirpstack/.env ps
```

UI disponible:

- abrir `http://localhost:${CHIRPSTACK_UI_PORT}`

ChirpStack conectado a Postgres y Redis:

```bash
docker compose -f infra/chirpstack/docker-compose.yml --env-file infra/chirpstack/.env logs chirpstack
```

Buscar en logs:

- errores de autenticacion MQTT
- errores TLS
- errores de Redis
- errores de Postgres

Nota sobre esta stack de desarrollo:

- los histories de `monitoring` que escriben frame logs, event logs y meta logs en Redis quedan deshabilitados (`*_max_history=0`) para evitar errores de request logging que no afectan el flujo principal de API/UI
- si mas adelante necesitan esos logs en la UI, se pueden reactivar y validar compatibilidad con la version de Redis elegida

Confirmar que no intenta usar Mosquitto o localhost:

```bash
docker compose -f infra/chirpstack/docker-compose.yml --env-file infra/chirpstack/.env logs chirpstack | grep -Ei "mosquitto|localhost:1883|127.0.0.1:1883"
```

Si la configuracion esta bien, ese comando no deberia devolver coincidencias relevantes.

## Script opcional para validar EMQX antes de levantar ChirpStack

```bash
python scripts/check_emqx_connection.py --env-file infra/chirpstack/.env
```

El script:

- conecta con TLS usando las variables `EMQX_*`
- publica en `manea/debug/chirpstack/check`
- intenta suscribirse al mismo topic para validar publish+subscribe si el usuario tiene permisos

Nota:

- ese topic de debug no forma parte de las ACLs productivas sugeridas arriba
- si no hay permiso de subscribe sobre el topic de debug, la publicacion sigue sirviendo para validar credenciales y TLS

## Configuracion manual inicial en la UI

Crear estos objetos de desarrollo:

1. Tenant: `Manea`
2. Application: `Manea Dev`
3. Device Profile: `Collar GPS`
4. Device de prueba:
   `DevEUI: 0102030405060708`
   `Name: CHIRP-001`
5. Gateway de prueba si la UI lo permite:
   `gateway-sim-001`

Sin gateway real o simulador compatible no habra uplinks LoRaWAN reales.

## Relacion con las fases actuales

- Fase 1 sigue usando eventos simulados estilo ChirpStack.
- Fase 2 sigue usando simulacion de downlink, `txack`, `ack` y `event/up` con `fPort=20`.
- Fase 3 solo deja lista la infraestructura base de ChirpStack real conectada a EMQX Cloud.
- La sustitucion de eventos simulados por eventos reales se hara mas adelante con ChirpStack Simulator o con gateway fisico.
