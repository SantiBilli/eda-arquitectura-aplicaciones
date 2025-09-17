import os, json, boto3
from datetime import datetime
from botocore.exceptions import ClientError

sns    = boto3.client('sns')
dynamo = boto3.resource('dynamodb')

ORDERS_TABLE = os.environ.get('ORDERS_TABLE', 'OrdenesCompra')
PROVEEDORES_TOPIC_ARN = os.environ.get('PROVEEDORES', '').strip()   # <-- usa tu env var

table = dynamo.Table(ORDERS_TABLE)

def _detail(evt):
    d = evt.get('detail', evt)
    if isinstance(d, str):
        try: d = json.loads(d)
        except Exception: d = {}
    return d

def _parse_items(items_field):
    if items_field is None:
        return []
    if isinstance(items_field, str):
        try:
            return json.loads(items_field)
        except Exception:
            return []
    return items_field

def _format_message(order, approved_at=None):
    order_id = order.get('orderId', 'N/A')
    origen   = order.get('origen') or order.get('ROL') or 'CasaCentral'
    items    = _parse_items(order.get('items'))

    lines = [
        "Orden de Compra APROBADA",
        f"OC: {order_id}",
        f"Fecha aprobación: {approved_at or datetime.utcnow().isoformat()}",
        "",
        "Productos:"
    ]
    if isinstance(items, list) and items:
        for it in items:
            if isinstance(it, dict):
                sku  = it.get('sku', 'N/A')
                qty  = it.get('qty', 'N/A')
                desc = it.get('desc') or it.get('descripcion') or ''
                lines.append(f" - SKU: {sku}  Qty: {qty}  {desc}")
            else:
                lines.append(f" - {str(it)}")
    else:
        lines.append(" (sin items)")
    return "\n".join(lines)

def lambda_handler(event, context):
    if not PROVEEDORES_TOPIC_ARN:
        return {'statusCode': 500, 'body': json.dumps({'error': "Falta env PROVEEDORES con el ARN del topic SNS de proveedores"})}

    print("[EVENT]", json.dumps(event))
    det = _detail(event)
    dt  = event.get('detail-type') or event.get('detailType')
    if dt != 'OrdenAprobada':
        return {'statusCode': 200, 'body': json.dumps({'info': 'evento ignorado'})}

    order_id    = det.get('orderId')
    approved_at = det.get('approvedAt')
    if not order_id:
        return {'statusCode': 400, 'body': json.dumps({'error': 'orderId faltante en event.detail'})}

    # 1) Leer la orden
    try:
        resp  = table.get_item(Key={'orderId': order_id})
        order = resp.get('Item')
        if not order:
            return {'statusCode': 404, 'body': json.dumps({'error': f'Orden {order_id} no encontrada'})}
    except ClientError as e:
        return {'statusCode': 500, 'body': json.dumps({'error': f'DynamoDB: {str(e)}'})}

    # 2) Armar asunto y cuerpo
    subject = f"OC {order_id} Aprobada – Detalle para proveedor (Rol: PROVEEDOR)"
    message = _format_message(order, approved_at)

    # 3) Publicar en SNS (topic de proveedores)
    try:
        res = sns.publish(TopicArn=PROVEEDORES_TOPIC_ARN, Subject=subject, Message=message)
        print("[SNS] MessageId:", res.get('MessageId'))
    except ClientError as e:
        return {'statusCode': 500, 'body': json.dumps({'error': f'SNS: {str(e)}'})}

    return {'statusCode': 200, 'body': json.dumps({'sentToTopic': PROVEEDORES_TOPIC_ARN})}
