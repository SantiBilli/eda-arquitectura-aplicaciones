import os, json, uuid, datetime
import boto3
from botocore.exceptions import ClientError

dynamodb = boto3.client('dynamodb')
events = boto3.client('events')

def put_event_orden_creada(order):
    detail = {
        "orderId": order["orderId"],
        "items": order["items"],
        "origen": order.get("origen", "CasaCentral")
    }
    events.put_events(Entries=[{
        "Source": "com.casacentral.compras", #OrdenCreada
        "DetailType": "OrdenCreada",
        "Detail": json.dumps(detail),
        "EventBusName": "ventas-bus"
    }])

def lambda_handler(event, context):
    body = event.get("detail") or event.get("body") or event
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except Exception:
            body = {}

    now_iso = datetime.datetime.utcnow().isoformat()
    order_id = body.get("orderId") or f"OC-{uuid.uuid4().hex[:10].upper()}"
    items = body.get("items", [])
    origen = body.get("origen", "CasaCentral")

    if not items:
        return {"ok": False, "message": "items es requerido y no puede ser vacío"}

    # 1) Guardar orden con condición para no pisar si ya existe
    try:
        dynamodb.put_item(
            TableName="OrdenesCompra",
            Item={
                "orderId": {"S": order_id},
                "status": {"S": "CREATED"},
                "items": {"S": json.dumps(items)},
                "origen": {"S": origen},
                "createdAt": {"S": now_iso},
                "updatedAt": {"S": now_iso}
            },
            ConditionExpression="attribute_not_exists(orderId)"
        )
    except ClientError as e:
        # Si ya existía, devolvemos error claro
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return {"ok": False, "message": f"La orden {order_id} ya existe"}
        raise

    # 2) Publicar evento OrdenCreada → lo consumirá CasaCentral-CrearOrden-Deposito
    put_event_orden_creada({
        "orderId": order_id,
        "items": items,
        "origen": origen
    })

    return {"ok": True, "orderId": order_id}
