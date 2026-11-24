# SDD: Identidad QR operativa del collar

**Estado:** Backend y entrada QR frontend implementados; scanner integrado pendiente.  
**Fecha de inspección:** 2026-10-27  
**Workspace:** `manea-workspace.code-workspace` (`TLRS` + `TLRS-FRONT`)

## 1. Objetivo

Permitir identificar físicamente un collar de Manea escaneando un QR permanente. El QR resuelve el collar a un `Device` existente y abre el detalle de collar existente. La asignación, reasignación y liberación continúan usando exclusivamente la lógica y los controles existentes.

```text
QR -> identificar Device -> detalle de collar existente -> acciones existentes
```

El QR no es credencial de autorización, no provisiona ChirpStack y no participa en la lógica Device → Asset.

## 2. Fuera de alcance

- Cambiar o duplicar assign / reassign / release.
- Cambiar `DeviceAssetAssignment` o su historial.
- Provisioning LoRaWAN, DevEUI, JoinEUI, AppKey, ChirpStack, firmware, MQTT o telemetría.
- QR de fabricación del MCU.
- Implementar un scanner en esta primera entrega.
- Almacenar archivos de imagen QR en la base de datos o en storage.
- Sistema avanzado de diseño/impresión de etiquetas.

## 3. Diagnóstico del código existente

### 3.1 Workspace y repositorios

El workspace multi-root `manea-workspace.code-workspace` contiene:

- `TLRS`: backend FastAPI/SQLAlchemy/Alembic.
- `TLRS-FRONT`: frontend React, TypeScript, Vite, React Router y TanStack Query.

### 3.2 Backend

- `src/models/device.py`: `Device` ahora tiene `qr_token`, generado con `secrets.token_urlsafe(32)`, y un índice único global.
- `src/service/device_provisioning_service.py`: `provision_device()` genera token en backend al crear el Device; el token no entra en el request ni en schemas de provisioning.
- Migración `2026_10_27_1200_9a7c4d2e6f10_add_device_qr_token.py`: añade columna nullable, hace backfill por lotes para todos los Devices, crea índice único global y la hace NOT NULL.
- `GET /devices/by-qr/{qr_token}`: requiere autenticación; usuario normal requiere el permiso existente `device:get my devices` y scope de cliente; admin tiene scope global. Token inexistente, Device eliminado u otro tenant dan el mismo `404`.
- `GET /devices/{id_device}/qr`: admin-only; devuelve sólo `qr_token` para construir/mostrar el QR desde el frontend.
- `DeviceQrResolveResponse`: devuelve identidad Device, estado operativo y `asset` resumido o `null`; omite `client_id`, token y campos LoRaWAN.
- Fallback legacy ownership: si `Device.client_id` es nulo, la resolución de usuario usa el cliente del asset asociado activo. Un Device antiguo sin `client_id` y sin asset no puede atribuirse a un tenant y sólo se resuelve desde flujo admin.
- Tests backend agregados para token al provisioning, backfill, aislamiento de tenant, respuesta mínima y estabilidad tras reasignación/liberación.
- Validación ejecutada: suite completa del backend (184 tests) pasó, incluyendo integración con la base PostGIS.
- `src/service/device_assignment_service.py`: centraliza asignación, reasignación y liberación y mantiene el historial `DeviceAssetAssignment`. El QR no necesita modificar este servicio.
- `src/routers/device.py`: rutas existentes para provisioning, asignación/liberación y devices del usuario. Las operaciones de asignación/liberación actualmente exigen admin.
- `src/service/crud_device.py`: `get_devices_by_client_id()` filtra por `Device.client_id` y hace `JOIN` interno a `Asset`, por lo que excluye devices sin asset.
- `src/service/crud_device.py`: `get_devices()` alimenta el listado admin global.
- `src/schemas/device.py`: el nuevo DTO QR evita reutilizar `DeviceRead`/`DeviceAdminResponse`, que requieren campos no apropiados o contienen datos técnicos.
- Ownership normal: `Device.client_id`; el QR resuelve tenant legacy desde Asset sólo cuando Device no tiene cliente.
- Soft delete: el resolver excluye `Device.deleted != 'N'`. No hay endpoint de borrado de Device.
- Auth: `get_current_user` valida el access JWT. El resolver normal reutiliza `validate_user_service_access`; admin tiene acceso global.
- Provisioning persiste Device y asignación inicial antes de completar operaciones remotas ChirpStack; el token queda asignado al objeto Device desde el comienzo.

### 3.3 Frontend

- Router: `TLRS-FRONT/src/app/router.tsx` usa `createBrowserRouter`.
- Ruta actual de collar: `/app/collars/:deviceId`, bajo `ProtectedRoute`.
- Guard: `src/features/auth/components/ProtectedRoute.tsx` redirige a `/login` con `state.from = location`.
- Login: `src/features/auth/pages/LoginPage.tsx` recupera pathname/search/hash de `location.state.from` y navega allí después del login. `/c/:token` queda preservada tras autenticación.
- Sesión: `AuthProvider` renueva sesión al cargar mediante refresh cookie; el token de acceso vive en `authTokenStore`.
- Detalle existente: `src/features/collars/pages/CollarDetailPage.tsx` obtiene el collar buscando su ID en `useAllMyDevices()`, carga animales/rodeos y presenta asignar, cambiar, retirar y ver animal.
- Lista de collares: `src/features/collars/pages/CollarsPage.tsx` usa el mismo listado de devices; incluye filtros asignado/disponible/offline.
- **Inconsistencia actual para unassigned:** el frontend puede filtrar `assetId === null`, pero el endpoint backend usado por `useAllMyDevices()` excluye devices sin asset mediante inner join. El resolver QR tendrá que proporcionar el collar disponible directamente; el listado general queda como tema separado salvo decisión explícita.
- Acciones actuales: `src/features/collars/hooks/useCollarAssignment.ts` reutiliza `reassignDeviceAsset` y `releaseDeviceAsset` de `src/features/admin/api/admin.api.ts`; el detalle incluye también asignación. No se debe duplicar esas mutations.
- **Inconsistencia de autorización a confirmar:** los endpoints backend de assign/release requieren admin, mientras que CollarDetail está dentro del árbol `ProtectedRoute` de usuario y no de `AdminRoute`. Confirmar si la interfaz es usada por admin, o si existe una discrepancia de autorización previa. El QR no debe cambiar esa política de forma implícita.
- Admin: `src/features/admin/pages/AdminDevicesPage.tsx` tiene un listado y abre `AdminDeviceDetailDialog` al seleccionar un device; esto cumple el patrón de no llenar la tabla de botones.
- `src/features/admin/components/AdminDeviceDetailDialog.tsx` es el lugar natural para mostrar una sección de identificación QR.
- `src/features/admin/api/admin.api.ts` ya contiene operaciones admin de devices.
- Implementado: ruta protegida `/c/:token`, `QrCollarPage`, hook de resolución y uso de `CollarDetailPage` con el Device resuelto. El Device QR se pasa directamente al detalle, de modo que el acceso no depende del listado que excluye devices sin asset.
- Implementado: `useCollarAssignment` invalida también las queries QR para refrescar el animal después de assign/reassign/release.
- Implementado: el diálogo admin consulta `GET /devices/{id_device}/qr` y muestra/descarga el SVG con el enlace público del frontend.
- Se agregó `qrcode.react` para renderizar SVG y `VITE_PUBLIC_APP_URL` para configurar la URL canónica; en desarrollo usa `window.location.origin` como fallback.
- No se implementó scanner.
- No se agregaron tests frontend, según la instrucción de esta etapa. `npm run build` pasó.
- API client: `src/shared/api/httpClient.ts`; API de devices usuario: `src/features/devices/api/devices.api.ts`.
- Config frontend: `.env.example` sólo declara `VITE_API_BASE_URL`; no declara URL pública de la PWA.
- No encontré manifest/service worker ni configuración de instalación PWA en los archivos inspeccionados. Verificar despliegue/hosting y fallback de rutas antes de habilitar impresión/escaneo externo.
- `package.json` sólo incluye scripts `dev`, `build`, `preview`; no declara runner de tests frontend. Debe decidirse estrategia de pruebas antes de la fase frontend, sin instalar dependencias durante esta planificación.
- No existía scanner ni infraestructura PWA/manifest visible al inspeccionar el repo. La ruta QR frontend ahora existe; sigue pendiente confirmar en hosting el fallback SPA para `/c/*`.

## 4. Decisiones recomendadas

1. **Formato del token:** `secrets.token_urlsafe(32)`, 32 bytes aleatorios (256 bits), 43 caracteres URL-safe sin padding. No usar ID interno ni serial como token.
2. **Campo DB:** `devices.qr_token`, `String(43)` o un límite holgado documentado (por ejemplo `String(64)`), con índice único global. No parcial por `deleted`: un device eliminado mantiene su identidad histórica.
3. **Generación:** backend al construir `Device` en `DeviceProvisioningService.provision_device()`. No recibirlo en `ChirpStackDeviceCreate` ni permitir editarlo desde UI. El token no se regenera al asignar, reasignar o liberar.
4. **Backfill/despliegue:** implementación actual agrega columna nullable, hace backfill por lotes para todos los devices (también soft-deleted), crea índice único y aplica `NOT NULL` en una revisión. Coordinar despliegue para que instancias antiguas no escriban después de migrar; separar `NOT NULL` si se requiere rollout sin detener writers. No depender de `pgcrypto` ni de una extensión DB.
5. **Resolver:** `GET /devices/by-qr/{qr_token}`, siempre autenticado. Normal debe tener el permiso de lectura de devices existente y su `client_id` debe coincidir; admin puede resolver cualquier cliente según flujo global explícito.
6. **Response resolver:** el DTO implementado devuelve `id_device`, `serial`, `name`, `type`, `state`, `active` y `asset: null | {id_asset, serial, asset_type, status}`. No envía `client_id`, DevEUI, JoinEUI, Application/Profile IDs, credenciales ni `qr_token` en el resolver.
7. **No encontrado/no autorizado:** mismo `404` para token inexistente, eliminado o de otro tenant. No filtrar la existencia del collar. Inactividad y offline no bloquean identificación.
8. **Ruta frontend:** implementada `/c/:token` protegida. Se mantiene la URL QR como wrapper que consulta el resolver y pasa su Device a `CollarDetailPage`; refresh vuelve a resolver y soporta devices sin asset.
9. **Login/return:** implementado con `ProtectedRoute` y `LoginPage`; se conserva pathname/search/hash en el retorno local y no se permite destino que empiece por `//`.
10. **Admin QR:** implementado dentro de `AdminDeviceDetailDialog`, no en la tabla. Consulta `GET /devices/{id_device}/qr` y genera el link/QR en el cliente.
11. **URL QR:** `<PUBLIC_FRONTEND_URL>/c/<qr_token>`. Introducir configuración de URL pública canónica por entorno (no asumir `VITE_API_BASE_URL` ni que origin de preview sea el dominio imprimible). Fallback a `window.location.origin` sólo para desarrollo/si así se decide.
12. **Imagen QR:** implementado SVG generado en cliente con `qrcode.react`, descargable, sin almacenar imagen. Para scanner futuro, evaluar `@zxing/browser` o `html5-qrcode`; no instalar ni elegir librería de scanner ahora.
13. **Scanner futuro:** componente encapsulado `QrScanner` obtiene URL/token, para cámara al cerrar/unmount y navega a `/c/:token`. Así QR externo e interno comparten resolución.

## 4.1 Estado de implementación backend

- La identidad QR, el backfill, el índice único, la generación automática, el resolver autenticado y la lectura admin del token están implementados en `TLRS`.
- El resolver real devuelve:

```json
{
  "id_device": 29,
  "serial": "MANEA-0029",
  "name": "Collar 0029",
  "type": "COLLAR",
  "state": "OFF",
  "active": false,
  "asset": {
    "id_asset": 1842,
    "serial": "1842",
    "asset_type": "CATTLE",
    "status": "ACTIVE"
  }
}
```

- Si no tiene asignación, `asset` es `null`. El `state`/`active` no condicionan la resolución.
- La generación incluye un default ORM de respaldo y asignación explícita durante provisioning.
- Alembic actualiza a NOT NULL en la misma revisión del backfill; en despliegues rolling, ejecutar la migración coordinada para que instancias antiguas no intenten insertar sin token.
- La integración frontend correspondiente se describe en la sección siguiente.

## 4.2 Estado de implementación frontend

- `/c/:token` está en `src/app/router.tsx`, envuelta con `ProtectedRoute` y `AppLayout`.
- `QrCollarPage` obtiene token con `useResolveCollarQr`, mapea 404 a un estado no encontrado genérico y reusa `CollarDetailPage` pasando `resolvedDevice`.
- `CollarDetailPage` mantiene su comportamiento existente para `/app/collars/:deviceId`; para entrada QR desactiva la query de listado y usa el dato resuelto.
- Tras mutations, la query key `['devices', 'qr']` se invalida.
- El diálogo admin incluye `AdminDeviceQrSection`, llama el endpoint de token y descarga SVG.
- Variables necesarias: `VITE_API_BASE_URL` y `VITE_PUBLIC_APP_URL` (fallback local a `window.location.origin`). Configurar URL pública estable en cada despliegue antes de imprimir QRs.
- Validación: `npm run build` pasó. No se agregaron tests frontend en esta etapa.

## 5. Plan por fases

### Fase 1 — Identidad y migración

- **Objetivo:** asignar token estable, único y automático a todos los devices existentes y nuevos.
- **Backend afectado:** `src/models/device.py`, `src/service/device_provisioning_service.py`, nueva revisión Alembic encadenada al head real de ese momento.
- **DB:** nullable → backfill → unique → deploy writers nuevos → `NOT NULL` en migración posterior.
- **Contrato API:** ninguno; el frontend no genera token.
- **Reuso:** provisioning existente crea Device; asignación inicial permanece igual.
- **Tests:** provisioning genera token; tokens son no vacíos/únicos; backfill cubre asignados, sin asignar y eliminados; token permanece igual a través de assign/reassign/release.
- **Riesgo:** deployments rolling con instancias antiguas insertando null; gestionar fase `NOT NULL` después de retirar writers viejos.
- **Dependencia:** ninguna.
- **Aceptación:** todo Device utilizable tiene identidad QR opaca y única y provisioning no pide token al admin.

### Fase 2 — Resolver backend con ownership

- **Objetivo:** traducir un token a información de Device disponible para CollarDetail.
- **Backend afectado:** `src/schemas/device.py`, `src/service/crud_device.py` (o application service explícito), `src/routers/device.py`.
- **DB:** búsqueda exacta por índice `qr_token`; filtros por borrado lógico y tenant.
- **Contrato:** `GET /devices/by-qr/{qr_token}`, bearer requerido; response QR mínima. `404` uniforme ante inexistente/eliminado/otro cliente.
- **Reuso:** auth y servicio de acceso actual; no usar `get_devices_by_client_id()` porque excluye unassigned.
- **Tests:** autenticación, válido/inválido, cross-tenant, admin, soft delete, client fallback legacy, inactivo/offline, con/sin asset.
- **Riesgo:** resolver ownership de registros legacy con `client_id` nulo; decidir fallback mediante asset y verificar el cliente activo.
- **Dependencia:** Fase 1.
- **Aceptación:** usuarios autorizados pueden resolver su collar aún si no tiene asset u offline; no aprenden si otro tenant posee el token.

### Fase 3 — `/c/:token` y auth/return

- **Objetivo:** admitir entrada desde cámara normal y tras login volver al QR original.
- **Frontend afectado:** `src/app/router.tsx`, `src/features/auth/components/ProtectedRoute.tsx`, `src/features/auth/pages/LoginPage.tsx`, posiblemente tipos/helpers auth.
- **DB:** ninguna.
- **Contrato:** hook/API para resolver token autenticado.
- **Reuso:** `ProtectedRoute`, `AuthProvider`, refresh existente.
- **Tests:** route autenticada; redirect a login; volver exactamente a `/c/<token>`; refresh; invalid token; error 404 seguro; login ya autenticado no fuerza dashboard.
- **Riesgo:** login actual lee sólo `from.pathname` y el caso `isAuthenticated` navega a `/app/map`; confirmar timing y cubrir ambos caminos para no perder target.
- **Dependencia:** Fase 2.
- **Aceptación:** escanear sin sesión → login → vuelve al resolver, sin dashboard intermedio como destino final.

### Fase 4 — Reutilizar detalle de collar

- **Objetivo:** renderizar el detalle existente tras resolver; no crear acciones de asignación QR.
- **Frontend afectado:** nuevo resolver page/hook/API bajo `src/features/collars/` o `src/features/devices/`; `src/features/collars/pages/CollarDetailPage.tsx`; tipos device (`src/features/devices/types/device.types.ts`).
- **DB:** ninguna.
- **Contrato:** respuesta del resolver adaptada a tipos de collar/device actuales.
- **Reuso:** `CollarDetailPage`, `CollarAssignmentDialog`, `useCollarAssignment`, `useReleaseCollar`, `useAnimals`, `useAnimalRodeos`; collar asignado conserva Ver animal/Cambiar/Retirar y no asignado ofrece Asignar.
- **Tests:** estados assigned/unassigned/offline, assign/reassign/release usando mutaciones existentes, navigation to animal/back collars, refresh directo en `/c/:token`.
- **Riesgo:** el detalle actual busca el collar en `useAllMyDevices`, y el endpoint backend excluye devices sin asset; el wrapper QR debe inyectar/pasar el Device resuelto al detalle, no asumir que la lista lo contiene.
- **Dependencia:** Fase 3.
- **Aceptación:** la misma URL QR muestra el mismo collar antes/después de asignarlo; el detalle y acciones no dependen de LoRaWAN online.

### Fase 5 — QR en detalle Admin

- **Objetivo:** que admin obtenga e imprima el QR desde el detalle del Device sin controles nuevos en tabla.
- **Backend afectado:** `src/routers/device.py`, `src/schemas/device.py`, query/service seguro para admin.
- **Frontend afectado:** `src/features/admin/pages/AdminDevicesPage.tsx`, `src/features/admin/components/AdminDeviceDetailDialog.tsx`, `src/features/admin/api/admin.api.ts`; posible nueva sección/componente `DeviceQrCode`.
- **DB:** ninguna adicional.
- **Contrato:** `GET /devices/{id_device}/qr`, admin-only, devuelve `{qr_token}`; frontend construye URL canónica `/c/:token`.
- **Reuso:** seleccionar device ya abre `AdminDeviceDetailDialog`; agregar sección QR ahí.
- **Tests:** admin puede ver QR; no admin 403; deleted/not found; URL exacta con base pública; descarga/print simple.
- **Riesgo:** la URL pública aún no está configurada en `.env.example` (sólo existe `VITE_API_BASE_URL`).
- **Dependencia:** Fase 1 y selección de configuración de dominio público.
- **Aceptación:** admin selecciona collar y ve/descarga el QR sin botones adicionales en la tabla.

### Fase 6 — Validación integral

- **Objetivo:** validar backfill, APIs, auth, vista y acciones existentes de punta a punta.
- **Backend:** tests provisioning, resolver, autorización, migración.
- **Frontend:** tests de route/login/componentes con runner elegido; hoy `package.json` sólo tiene build/dev/preview y no declara runner frontend.
- **E2E conceptual:** crear/provisionar `MANEA-0029` → token generado → admin muestra QR → teléfono lo abre → login si corresponde → Manea identifica `MANEA-0029` → collar disponible → asignar por flujo actual a Caravana 1842 → escanear mismo QR → muestra Caravana 1842 → reassign/release siguen usando flujo actual.
- **Riesgos:** permiso de asignación backend admin-only frente a pantalla de collares bajo ProtectedRoute; resolverlo/confirmarlo antes de aceptar acciones para usuarios no-admin.
- **Dependencia:** Fases 1–5.
- **Aceptación:** secuencia anterior pasa en ambiente integrado, incluido usuario de tenant incorrecto, token inválido, offline y refresh.

### Fase posterior — Scanner integrado

- **Objetivo:** botón “Escanear collar” en `/app/collars` que abra cámara.
- **Frontend afectado:** `src/features/collars/pages/CollarsPage.tsx` y un componente aislado `QrScanner`.
- **Reuso:** scanner retorna token/URL y navega a `/c/:token`; no implementa otra API de resolución.
- **Librerías a evaluar, sin decisión/instalación ahora:** `@zxing/browser`, `html5-qrcode`; generación QR puede evaluarse separadamente con `qrcode.react`/`react-qr-code`.
- **Compatibilidad:** HTTPS requerido fuera de localhost, permiso de cámara, preferencia por cámara trasera, pruebas Safari/iOS, Chrome/Android, PWA/background y limpieza de stream al desmontar. `BarcodeDetector` no debe ser dependencia única por disponibilidad desigual.
- **Aceptación:** QR externo y scanner interno terminan en el mismo `/c/:token`.

## 6. Contratos propuestos

### Resolver QR

```http
GET /devices/by-qr/{qr_token}
Authorization: Bearer <access_token>
```

DTO conceptual (ajustar nombres a tipos frontend existentes al implementar):

```json
{
  "id_device": 29,
  "serial": "MANEA-0029",
  "name": "Collar 0029",
  "active": true,
  "state": "OFF",
  "asset": null
}
```

Para un collar asignado, `asset` contiene sólo el resumen requerido por el detalle existente. No incluir `client_id`, tokens, provisioning ni campos LoRaWAN.

### Leer token para Admin QR

```http
GET /devices/{id_device}/qr
Authorization: Bearer <admin_access_token>
```

```json
{ "qr_token": "..." }
```

El frontend forma `<PUBLIC_FRONTEND_URL>/c/<qr_token>` y genera la imagen localmente.

## 7. Seguridad y tenancy

- El QR contiene un identificador público opaco, nunca credenciales ni campos LoRaWAN.
- Toda resolución requiere usuario autenticado; el token por sí solo no da acceso.
- Admin global únicamente mediante rol/admin validado por backend.
- Usuario de cliente sólo obtiene devices de su scope.
- Responder `404` indistinguible para token inválido, de otro cliente o soft-deleted.
- No filtrar offline/inactivo: identifican estado del collar, no autorización.
- No registrar token completo en logs de requests/resolver; no es una credencial, pero evitar logging innecesario facilita privacidad y rotación futura.
- Asignación no muta token. Una eventual rotación por pérdida/compromiso es operación administrativa futura, no parte de esta feature.

## 8. Criterios globales de aceptación

- Device existente y nuevo tiene token único, aleatorio y estable.
- QR codifica URL canónica `/c/:token`, no datos internos ni credenciales.
- Resolución autenticada y tenant-safe; otro cliente no puede inferir existencia.
- Login conserva el destino del QR.
- Detalle reutilizado representa collar sin asignar, asignado y offline.
- Assign/reassign/release llaman a los hooks/endpoints actuales y no alteran `qr_token`.
- Admin muestra/descarga QR desde el detalle sin llenar la tabla de botones.
- Refresh de `/c/:token` vuelve a resolver correctamente.
- Scanner futuro converge al mismo resolver.

## 9. Orden de implementación recomendado

1. Confirmar alcance de ownership legacy y el permiso esperado de las acciones actuales de CollarDetail.
2. Aprobar esta spec y registrar la URL frontend canónica por ambiente.
3. Fase 1: columna, backfill, generación en provisioning y pruebas.
4. Fase 2: resolver autenticado, DTO mínimo y pruebas cross-tenant.
5. Fases 3–4: ruta QR, retorno auth e integración al CollarDetail existente.
6. Fase 5: endpoint de token admin y sección QR en el diálogo admin.
7. Fase 6: pruebas integradas/migración/E2E.
8. En otro alcance: scanner de cámara reutilizando `/c/:token`.

## 10. Referencias inspeccionadas

### Backend (`TLRS`)

- `src/models/device.py`
- `src/models/device_asset_assignment.py`
- `src/service/device_provisioning_service.py`
- `src/service/device_assignment_service.py`
- `src/service/crud_device.py`
- `src/routers/device.py`
- `src/schemas/device.py`
- `src/service/crud_user.py` (`get_current_user`)
- `src/utils/validations.py`
- `tests/test_chirpstack_device_provisioning_service.py`
- `tests/test_device_asset_assignment_service.py`
- `tests/test_device_provisioning_contract.py`

### Frontend (`TLRS-FRONT`)

- `src/app/router.tsx`
- `src/features/auth/components/ProtectedRoute.tsx`
- `src/features/auth/components/AdminRoute.tsx`
- `src/features/auth/pages/LoginPage.tsx`
- `src/features/auth/context/AuthProvider.tsx`
- `src/features/auth/api/auth.api.ts`
- `src/features/collars/pages/CollarsPage.tsx`
- `src/features/collars/pages/CollarDetailPage.tsx`
- `src/features/collars/hooks/useCollarAssignment.ts`
- `src/features/devices/api/devices.api.ts`
- `src/features/devices/types/device.types.ts`
- `src/features/admin/pages/AdminDevicesPage.tsx`
- `src/features/admin/components/AdminDeviceDetailDialog.tsx`
- `src/features/admin/api/admin.api.ts`
- `package.json`
