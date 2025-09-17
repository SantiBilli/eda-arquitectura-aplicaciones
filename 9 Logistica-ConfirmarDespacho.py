import os, json, boto3
from datetime import datetime
from botocore.exceptions import ClientError
import random
from decimal import Decimal

d = boto3.resource('dynamodb')
ev = boto3.client('events')

ENVIOS_TABLE = os.environ.get('ENVIOS_TABLE', 'Envios')
ORDERS_TABLE = os.environ.get('ORDERS_TABLE', 'OrdenesCompra')
STOCK_TABLE  = os.environ.get('STOCK_TABLE',  'StockGlobal')
EVENT_BUS    = os.environ.get('EVENT_BUS',    'ventas-bus')
EVENT_SOURCE = os.environ.get('EVENT_SOURCE', 'com.logistica.despacho')

# DEMO: sucursales a elegir (también podés pasarlas por evento/body)
SUCURSALES_DEFAULT = os.environ.get('SUCURSALES_DEFAULT', 'S1,S2,S3,S4,S5').split(',')

envios = d.Table(ENVIOS_TABLE)
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
    return {'statusCode': code, 'headers': {'Content-Type':'text/html; charset=UTF-8'}, 'body': body}

def lambda_handler(event, context):
    order_id = _get_order_id(event)
    if not order_id:
        return _html("<html><body><h3>❗ Falta orderId</h3></body></html>", 400)

    now = datetime.utcnow().isoformat()
    envio_id = order_id

    # 0) Leer orden para obtener items
    try:
        resp = orders.get_item(Key={'orderId': order_id})
        ord_item = resp.get('Item')
        if not ord_item:
            return _html(f"<html><body><h3>❗ Orden {order_id} no encontrada</h3></body></html>", 404)
        items = _parse_items(ord_item.get('items'))
    except ClientError as e:
        return _html(f"<html><body><h3>❗ Error leyendo OrdenesCompra</h3><pre>{str(e)}</pre></body></html>", 500)

    # 1) Elegir 2 o 3 sucursales (demo). Si querés fijo, pasalas por body.
    k = random.choice((2, 3))
    seleccionadas = random.sample(SUCURSALES_DEFAULT, k)

    # 2) Upsert en Envios (PK envioId)
    try:
        try:
            envios.put_item(
                Item={
                    'envioId': envio_id,
                    'orderId': order_id,
                    'status': 'DISPATCH_CONFIRMED',
                    'dispatchedAt': now,
                    'updatedAt': now,
                    'confirmedBy': 'Logistica',
                    'sucursales': seleccionadas
                },
                ConditionExpression='attribute_not_exists(envioId)'
            )
        except ClientError as e:
            if e.response.get('Error',{}).get('Code') != 'ConditionalCheckFailedException':
                raise
            envios.update_item(
                Key={'envioId': envio_id},
                UpdateExpression='SET #st=:st, dispatchedAt=:ts, updatedAt=:ts, confirmedBy=:by, sucursales=:s',
                ExpressionAttributeNames={'#st': 'status'},
                ExpressionAttributeValues={':st':'DISPATCH_CONFIRMED', ':ts': now, ':by':'Logistica', ':s': seleccionadas}
            )
    except ClientError as e:
        return _html(f"<html><body><h3>❗ Error actualizando Envios</h3><pre>{str(e)}</pre></body></html>", 500)

    # 3) Restar stock global por SKU (si no alcanza, setear 0 — no borra filas)
    ajustados = []
    try:
        totales = {}
        for it in _parse_items(ord_item.get('items')):
            if isinstance(it, dict):
                sku = str(it.get('sku') or '').strip()
                qty = _to_decimal(it.get('qty') or 0)
                if sku and qty > 0:
                    totales[sku] = totales.get(sku, Decimal(0)) + qty

        for sku, dec in totales.items():
            try:
                stock.update_item(
                    Key={'sku': sku},
                    UpdateExpression='ADD qty :dec SET updatedAt = :ts, lastOrderId = :oid',
                    ExpressionAttributeValues={
                        ':dec': Decimal(0) - dec,
                        ':ts':  now,
                        ':oid': order_id,
                        ':need': dec
                    },
                    ConditionExpression='attribute_exists(qty) AND qty >= :need'
                )
                ajustados.append(f"{sku} -{dec}")
            except ClientError as e:
                if e.response.get('Error',{}).get('Code') == 'ConditionalCheckFailedException':
                    stock.update_item(
                        Key={'sku': sku},
                        UpdateExpression='SET qty = :zero, updatedAt = :ts, lastOrderId = :oid',
                        ExpressionAttributeValues={':zero': Decimal(0), ':ts': now, ':oid': order_id}
                    )
                    ajustados.append(f"{sku} -> 0")
                else:
                    raise
    except ClientError as e:
        return _html(f"<html><body><h3>❗ Error ajustando StockGlobal</h3><pre>{str(e)}</pre></body></html>", 500)

    # 4) Publicar evento para que otros (Sucursales/Proveedores) notifiquen
    detail = {
        'orderId': order_id,
        'envioId': envio_id,
        'dispatchedAt': now,
        'status': 'DISPATCH_CONFIRMED',
        'sucursales': seleccionadas
    }
    try:
        ev.put_events(Entries=[{
            'Source': EVENT_SOURCE,
            'DetailType': 'DespachoConfirmado',
            'Detail': json.dumps(detail),
            'EventBusName': EVENT_BUS
        }])
    except Exception as _:
        pass

    resumen = " | ".join(ajustados) if ajustados else "(sin SKUs para ajustar)"
    return _html(
        f"<html><body><h3>Despacho de la OC {order_id} CONFIRMADO 🚚✅</h3>"
        f"<p>Sucursales destino: {', '.join(seleccionadas)}</p>"
        f"<p>Ajustes de StockGlobal: {resumen}</p></body></html>"
    )
