import os
import json
import boto3
from datetime import datetime
from botocore.exceptions import ClientError

d = boto3.resource('dynamodb')
ev = boto3.client('events')

ORDERS_TABLE = os.environ.get('ORDERS_TABLE', 'OrdenesCompra')
EVENT_BUS    = os.environ.get('EVENT_BUS', 'ventas-bus')
EVENT_SOURCE = os.environ.get('EVENT_SOURCE', 'com.casacentral.aprobaciones') #Notificaciones Proveedor / Notificaciones Deposito

orders = d.Table(ORDERS_TABLE)


def _get_order_id(evt):
    # HTTP API (v2): pathParameters, queryStringParameters
    pp = (evt.get('pathParameters') or {})
    qp = (evt.get('queryStringParameters') or {})
    if pp.get('orderId'):
        return pp['orderId']
    if qp.get('orderId'):
        return qp['orderId']

    # Body opcional
    body = evt.get('body')
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except Exception:
            body = {}
    if isinstance(body, dict) and body.get('orderId'):
        return body['orderId']

    return evt.get('orderId')


def lambda_handler(event, context):
    order_id = _get_order_id(event)
    if not order_id:
        return {'statusCode': 400, 'body': json.dumps({'error': 'orderId requerido'})}

    now = datetime.utcnow().isoformat()

    try:
        orders.update_item(
            Key={'orderId': order_id},
            UpdateExpression='SET #st = :st, approvedAt = :ts, updatedAt = :ts',
            ExpressionAttributeNames={'#st': 'status'},
            ExpressionAttributeValues={
                ':st': 'APPROVED',
                ':ts': now,
                ':expected': 'PENDING_APPROVAL'
            },
            ConditionExpression='#st = :expected'
        )
    except ClientError as e:
        code = e.response.get('Error', {}).get('Code')
        if code == 'ConditionalCheckFailedException':
            html = (
                f"<html><body><h3>❗ No se puede aprobar la orden {order_id}</h3>"
                f"<p>Estado inválido o no existe (se esperaba PENDING_APPROVAL).</p></body></html>"
            )
            return {'statusCode': 409, 'headers': {'Content-Type': 'text/html'}, 'body': html}
        raise

    # Evento para continuar flujo
    ev.put_events(Entries=[{
        'Source': EVENT_SOURCE,
        'DetailType': 'OrdenAprobada',
        'Detail': json.dumps({'orderId': order_id, 'approvedAt': now}),
        'EventBusName': EVENT_BUS
    }])

    html = f"<html><body><h3>Orden {order_id} APROBADA</h3></body></html>"
    return {'statusCode': 200, 'headers': {'Content-Type': 'text/html'}, 'body': html}
