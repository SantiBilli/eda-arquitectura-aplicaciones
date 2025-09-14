# Retail Deportivo – Flujo de Compras, Depósito y Logística (AWS)

> **Stack:** API Gateway (HTTP API v2) · AWS Lambda · EventBridge · DynamoDB · SNS
> **Región:** `us-east-2`  
> **Bus de eventos:** `ventas-bus`

Este repositorio documenta un flujo **event-driven** que orquesta la creación y aprobación de **Órdenes de Compra (OC)**, su **recepción en Depósito**, actualización de **Stock Global**, y **despacho** con notificaciones por **SNS**.

---

## 🗺️ Arquitectura
![Arquitectura del flujo (alto nivel)](Arquitectura.png)

---

## 📦 Componentes

### DynamoDB

| Tabla | PK | Uso | Campos relevantes |
|---|---|---|---|
| **OrdenesCompra** | `orderId` (S) | OC y su ciclo | `status` (`CREATED`, `PROCESSED`, `PENDING_APPROVAL`, `APPROVED`, `REJECTED`, `RECEIVED`), `items` (lista o string JSON), `origen`, timestamps varios |
| **StockGlobal** | `sku` (S) | Stock por SKU | `qty` (Number), `updatedAt`, `lastOrderId` |
| **Envios** | `envioId` (S) = `orderId` | Despachos | `orderId`, `status` (`DISPATCH_CONFIRMED`), `sucursales` (demo), `dispatchedAt`, `confirmedBy` |

### SNS (tópicos)

- `COMPRAS_APROBADORES` – notifica a aprobadores (con links de aprobar/rechazar).
- `PROVEEDORES` – detalle de OC aprobada para el proveedor.
- `DEPOSITO` – aviso para confirmar recepción.
- `LOGISTICA` – aviso para confirmar despacho.
- `SUCURSALES` – **demo**: un solo topic; el correo incluye el nombre de sucursal.

### API Gateway (HTTP API v2)

| Método/Path | Lambda | Propósito |
|---|---|---|
| `POST /ordenes-compra` | `Compras-CrearOrden-CasaCentral` | Crear OC (status `CREATED`) y emitir `OrdenCreada` |
| `GET /approvals/{orderId}/approve` | `CasaCentral-AprobarOrden` | Aprobar OC (`APPROVED`) y emitir `OrdenAprobada` |
| `GET /approvals/{orderId}/reject` | `CasaCentral-RechazarOrden` | Rechazar OC (`REJECTED`) y emitir `OrdenRechazada` |
| `GET /recepciones/{orderId}/accept` | `Deposito-AceptarRecepcion` | Marcar OC `RECEIVED` + sumar stock + `RecepcionRecibida` |
| `GET /despachos/{orderId}/confirm` | `Logistica-ConfirmarDespacho` | Upsert en `Envios`, **restar stock** y `DespachoConfirmado` |

### EventBridge (bus: `ventas-bus`)

| Regla | Filtro (source / detail-type) | Destino |
|---|---|---|
| `OrdenCreada` | `com.casacentral.compras` / `OrdenCreada` | `CasaCentral-ProcesarOrden-Deposito` |
| `OrdenProcesada` | `com.casacentral.procesos` / `OrdenProcesada` | `Notificaciones-OC` (set `PENDING_APPROVAL` + evento) |
| `Notificaciones-OC` | `com.casacentral.procesos` / `OrdenPendienteAprobacion` | Notificador Aprobadores (SNS) |
| `Notificaciones-Proveedor` | `com.casacentral.aprobaciones` / `OrdenAprobada` | `Notificaciones-Proveedor` |
| `Notificacion-Deposito` | `com.casacentral.aprobaciones` / `OrdenAprobada` | `Notificacion-Deposito-A-R` |
| `RecepcionPreparada` | `com.deposito.recepcion` / `RecepcionRecibida` | Notificación/Logística (u otros pasos) |

---

## 🔁 Contratos de eventos

<details>
<summary><strong>OrdenCreada</strong></summary>

```json
{
  "Source": "com.casacentral.compras",
  "DetailType": "OrdenCreada",
  "Detail": {
    "orderId": "OC-1001",
    "items": [{"sku": "ABC-123", "qty": 2}],
    "origen": "CasaCentral"
  }
}
```
</details>

<details>
<summary><strong>OrdenProcesada</strong></summary>

```json
{
  "Source": "com.casacentral.procesos",
  "DetailType": "OrdenProcesada",
  "Detail": {"orderId":"OC-1001","status":"PROCESSED"}
}
```
</details>

<details>
<summary><strong>OrdenPendienteAprobacion</strong></summary>

```json
{
  "Source": "com.casacentral.procesos",
  "DetailType": "OrdenPendienteAprobacion",
  "Detail": {
    "orderId": "OC-1001",
    "ROL": "CasaCentral",
    "audienceRoles": ["COMPRAS_APROBADORES"]
  }
}
```
</details>

<details>
<summary><strong>OrdenAprobada</strong></summary>

```json
{
  "Source": "com.casacentral.aprobaciones",
  "DetailType": "OrdenAprobada",
  "Detail": {"orderId":"OC-1001","approvedAt":"<ISO8601>"}
}
```
</details>

<details>
<summary><strong>RecepcionRecibida</strong></summary>

```json
{
  "Source": "com.deposito.recepcion",
  "DetailType": "RecepcionRecibida",
  "Detail": {"orderId":"OC-1001","receivedAt":"<ISO8601>","status":"RECEIVED"}
}
```
</details>

<details>
<summary><strong>DespachoConfirmado</strong></summary>

```json
{
  "Source": "com.logistica.despacho",
  "DetailType": "DespachoConfirmado",
  "Detail": {"orderId":"OC-1001","envioId":"OC-1001","dispatchedAt":"<ISO8601>","status":"DISPATCH_CONFIRMED"}
}
```
</details>

---

## ⚙️ Variables de entorno

> Configurarlas en cada Lambda según corresponda.

| Variable | Ejemplo / Notas |
|---|---|
| `ORDERS_TABLE` | `OrdenesCompra` |
| `STOCK_TABLE` | `StockGlobal` |
| `ENVIOS_TABLE` | `Envios` |
| `EVENT_BUS` | `ventas-bus` |
| `EVENT_SOURCE` | p.ej. `com.casacentral.aprobaciones`, `com.deposito.recepcion`, `com.logistica.despacho` |
| `APPROVAL_BASE_URL` | Base de API para links de aprobación (notificador) |
| `API_BASE_URL` | Base de API para links de recepción/despacho |
| `ROLE_TOPIC_MAP` | JSON con roles→ARNs, p.ej. `{"COMPRAS_APROBADORES":"arn:...:COMPRAS_APROBADORES"}` |
| `PROVEEDORES` / `DEPOSITO` / `LOGISTICA` / `SUCURSALES` | ARN del topic SNS correspondiente |

---

## 🔐 Permisos (IAM mínimos por Lambda)

- **DynamoDB:** `GetItem`, `PutItem`, `UpdateItem` sobre tablas usadas.
- **EventBridge:** `events:PutEvents` sobre `ventas-bus`.
- **SNS (notificadores):** `sns:Publish` sobre los Topic ARN configurados.
- **Logs:** permisos estándar de CloudWatch Logs.

---

## 🚀 Cómo probar (end-to-end)

1. **Crear una orden**
   ```bash
   curl -X POST https://<api-id>.execute-api.us-east-2.amazonaws.com/ordenes-compra \
     -H 'Content-Type: application/json' \
     -d '{
       "orderId": "OC-1001",
       "items": [{"sku":"ABC-123","qty":2},{"sku":"XYZ-999","qty":1}],
       "origen": "CasaCentral"
     }'
   ```

2. **Aprobación por link de email** (o directo por curl)
   ```bash
   curl "https://<api-id>.execute-api.us-east-2.amazonaws.com/approvals/OC-1001/approve"
   # o para rechazo:
   curl "https://<api-id>.execute-api.us-east-2.amazonaws.com/approvals/OC-1001/reject?reason=Sin%20presupuesto"
   ```

3. **Recepción (Depósito)**
   ```bash
   curl "https://<api-id>.execute-api.us-east-2.amazonaws.com/recepciones/OC-1001/accept"
   ```
   - Actualiza `OrdenesCompra.status = RECEIVED`
   - Suma stock en `StockGlobal` por cada `sku`
   - Emite `RecepcionRecibida`
   - (Notifica a Logística si está configurado)

4. **Confirmar despacho (Logística)**
   ```bash
   curl "https://<api-id>.execute-api.us-east-2.amazonaws.com/despachos/OC-1001/confirm"
   ```
   - Upsert en `Envios` (`envioId = orderId`)
   - **Resta** stock en `StockGlobal` (si no alcanza, deja `qty=0`)
   - Emite `DespachoConfirmado`
   - (Demo) Notifica a `SUCURSALES`

---

## 🧪 Datos de ejemplo

```json
{
  "orderId": "OC-1001",
  "items": [
    {"sku": "ABC-123", "qty": 2},
    {"sku": "XYZ-999", "qty": 1}
  ],
  "origen": "CasaCentral"
}
```
