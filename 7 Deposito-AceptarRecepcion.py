import os, json, boto3
from datetime import datetime
from botocore.exceptions import ClientError
from decimal import Decimal

d = boto3.resource('dynamodb')
ev = boto3.client('events')

ORDERS_TABLE = os.environ.get('ORDERS_TABLE', 'OrdenesCompra')
STOCK_TABLE  = os.environ.get('STOCK_TABLE',  'StockGlobal')
EVENT_BUS    = os.environ.get('EVENT_BUS',    'ventas-bus')
EVENT_SOURCE = os.environ.get('EVENT_SOURCE', 'com.deposito.recepcion')

orders = d.Table(ORDERS_TABLE)
stock  = d.Table(STOCK_TABLE)

def _get_order_id(evt):
    pp = (evt.get('pathParameters') or {})
    qp = (evt.get('queryStringParameters') or {})
    if pp.get('orderId'): return pp['orderId']
    if qp and qp.get('orderId'): return qp['orderId']
    body = evt.get('body')
    if isinstance(body, str):
        try: body = json.loads(body)
        except: body = {}
    if isinstance(body, dict) and body.get('orderId'):
        return body['orderId']
    return evt.get('orderId')

def _parse_items(items_field):
    if items_field is None: return []
    if isinstance(items_field, str):
        try: return json.loads(items_field)
        except Exception: return []
    return items_field

def _to_decimal(n):
    try: return Decimal(str(n))
    except Exception: return Decimal(0)

def _html(body, code=200):
    return {'statusCode': code, 'headers': {'Content-Type': 'text/html; charset=UTF-8'}, 'body': body}

def lambda_handler(event, context):
    order_id = _get_order_id(event)
    if not order_id:
        return _html("<html><body><h3>❗ Falta orderId</h3></body></html>", 400)

    now = datetime.utcnow().isoformat()

    # 1) Leer la orden
    try:
        resp = orders.get_item(Key={'orderId': order_id})
        order_item = resp.get('Item')
        if not order_item:
            return _html(f"<html><body><h3>❗ Orden {order_id} no encontrada</h3></body></html>", 404)
    except ClientError as e:
        return _html(f"<html><body><h3>❗ Error DynamoDB (OrdenesCompra)</h3><pre>{str(e)}</pre></body></html>", 500)

    items = _parse_items(order_item.get('items'))
    if not items:
        return _html(f"<html><body><h3>❗ La orden {order_id} no tiene items</h3></body></html>", 422)

    # 2) Cambiar status -> RECEIVED
    try:
        orders.update_item(
            Key={'orderId': order_id},
            UpdateExpression='SET #st = :st, receivedAt = :ts, receivedBy = :by, updatedAt = :ts',
            ExpressionAttributeNames={'#st': 'status'},
            ExpressionAttributeValues={ ':st': 'RECEIVED', ':ts': now, ':by': 'Deposito' },
            ConditionExpression='attribute_exists(orderId)'
        )
    except ClientError as e:
        return _html(f"<html><body><h3>❗ Error actualizando estado de la orden</h3><pre>{str(e)}</pre></body></html>", 500)

    # 3) Sumar stock global por SKU
    try:
        for it in items:
            if not isinstance(it, dict): 
                continue
            sku = str(it.get('sku') or '').strip()
            if not sku: 
                continue
            inc = _to_decimal(it.get('qty', 0))
            if inc <= 0: 
                continue
            stock.update_item(
                Key={'sku': sku},
                UpdateExpression='ADD qty :inc SET updatedAt = :ts, lastOrderId = :oid',
                ExpressionAttributeValues={':inc': inc, ':ts': now, ':oid': order_id}
            )
    except ClientError as e:
        return _html(f"<html><body><h3>❗ Error actualizando StockGlobal</h3><pre>{str(e)}</pre></body></html>", 500)

    # 4) Emitir evento para notificaciones y pasos siguientes
    try:
        ev.put_events(Entries=[{
            'Source': EVENT_SOURCE,                             # com.deposito.recepcion
            'DetailType': 'RecepcionRecibida',
            'Detail': json.dumps({'orderId': order_id, 'receivedAt': now, 'status': 'RECEIVED'}),
            'EventBusName': EVENT_BUS                           # ventas-bus
        }])
    except Exception:
        pass

    return _html(f"<html><body><h3>Recepción de la OC {order_id} CONFIRMADA ✅</h3></body></html>")
