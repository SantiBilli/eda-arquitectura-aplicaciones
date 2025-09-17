import os, json, boto3
from datetime import datetime
from botocore.exceptions import ClientError

sns    = boto3.client('sns')
dynamo = boto3.resource('dynamodb')

ORDERS_TABLE = os.environ.get('ORDERS_TABLE', 'OrdenesCompra')
DEPOSITO_TOPIC_ARN = os.environ.get('DEPOSITO', '').strip()
API_BASE_URL = os.environ.get('API_BASE_URL', 'https://1y4g8pdtm1.execute-api.us-east-2.amazonaws.com')

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

def _format_message(order, approved_at=None, api_base=None):
    order_id = order.get('orderId', 'N/A')
    items    = _parse_items(order.get('items'))

    accept_url = f"{api_base}/recepciones/{order_id}/accept"

    lines = [
        "Pedido aprobado y en camino a Depósito",
        f"OC: {order_id}",
        f"Fecha aprobación: {approved_at or datetime.utcnow().isoformat()}",
        "Rol: Deposito",
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

    lines += [
        "",
        "Cuando llegue el pedido a Depósito, confirmá la recepción:",
        accept_url,
        "",
        "Este es un aviso automático."
    ]
    return "\n".join(lines)

def lambda_handler(event, context):
    print("[EVENT]", json.dumps(event))
    print("[ENV] DEPOSITO_TOPIC_ARN:", DEPOSITO_TOPIC_ARN)

    if not DEPOSITO_TOPIC_ARN:
        return {'statusCode': 500, 'body': json.dumps({'error': "Falta env DEPOSITO con el ARN del topic SNS de Depósito"})}

    det = _detail(event)
    dt  = event.get('detail-type') or event.get('detailType')
    if dt != 'OrdenAprobada':
        return {'statusCode': 200, 'body': json.dumps({'info': 'evento ignorado', 'dt': dt})}

    order_id    = det.get('orderId')
    approved_at = det.get('approvedAt')
    if not order_id:
        return {'statusCode': 400, 'body': json.dumps({'error': 'orderId faltante en event.detail'})}

    # 1) Obtener la orden
    try:
        resp  = table.get_item(Key={'orderId': order_id})
        order = resp.get('Item')
        if not order:
            return {'statusCode': 404, 'body': json.dumps({'error': f'Orden {order_id} no encontrada'})}
    except ClientError as e:
        return {'statusCode': 500, 'body': json.dumps({'error': f'DynamoDB: {str(e)}'})}

    # 2) Publicar mensaje
    subject = f"Depósito: OC {order_id} aprobada (confirmar recepción al arribo) (Rol: DESPOITO)"
    message = _format_message(order, approved_at, API_BASE_URL)
    print("[SNS] Publishing to:", DEPOSITO_TOPIC_ARN)
    try:
        res = sns.publish(TopicArn=DEPOSITO_TOPIC_ARN, Subject=subject, Message=message)
        print("[SNS] MessageId:", res.get('MessageId'))
    except ClientError as e:
        return {'statusCode': 500, 'body': json.dumps({'error': f'SNS: {str(e)}'})}

    return {'statusCode': 200, 'body': json.dumps({'sentToTopic': DEPOSITO_TOPIC_ARN})}
