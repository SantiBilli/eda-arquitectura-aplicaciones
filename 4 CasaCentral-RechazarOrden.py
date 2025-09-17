import os, json, boto3
from datetime import datetime
from botocore.exceptions import ClientError

d = boto3.resource('dynamodb')
ev = boto3.client('events')

ORDERS_TABLE = os.environ.get('ORDERS_TABLE','OrdenesCompra')
EVENT_BUS    = os.environ.get('EVENT_BUS','ventas-bus')
EVENT_SOURCE = os.environ.get('EVENT_SOURCE','com.casacentral.aprobaciones')

orders = d.Table(ORDERS_TABLE)

def _get_order_id_and_reason(evt):
    pp = (evt.get('pathParameters') or {})
    qp = (evt.get('queryStringParameters') or {})
    body = evt.get('body')
    if isinstance(body, str):
        try: body = json.loads(body)
        except: body = {}
    body = body if isinstance(body, dict) else {}
    order_id = pp.get('orderId') or qp.get('orderId') or body.get('orderId') or evt.get('orderId')
    reason = qp.get('reason') if qp else None
    if not reason:
        reason = body.get('reason')
    return order_id, reason

def lambda_handler(event, context):
    order_id, reason = _get_order_id_and_reason(event)
    if not order_id:
        return {'statusCode':400,'body':json.dumps({'error':'orderId requerido'})}

    now = datetime.utcnow().isoformat()

    try:
        orders.update_item(
            Key={'orderId': order_id},
            UpdateExpression='SET #st=:st, rejectedAt=:ts, updatedAt=:ts' + (', rejectionReason=:rr' if reason else ''),
            ExpressionAttributeNames={'#st':'status'},
            ExpressionAttributeValues={
                ':st':'REJECTED',
                ':ts': now,
                ':expected':'PENDING_APPROVAL',
                **({':rr': reason} if reason else {})
            },
            ConditionExpression='#st = :expected'
        )
    except ClientError as e:
        code = e.response.get('Error',{}).get('Code')
        if code == 'ConditionalCheckFailedException':
            html = f"<html><body><h3>❗ No se puede rechazar la orden {order_id}</h3><p>Estado inválido o no existe (se esperaba PENDING_APPROVAL).</p></body></html>"
            return {'statusCode':409,'headers':{'Content-Type':'text/html'},'body':html}
        raise


    html = f"<html><body><h3>Orden {order_id} RECHAZADA</h3>" + (f"<p>Motivo: {reason}</p>" if reason else "") + "</body></html>"
    return {'statusCode':200,'headers':{'Content-Type':'text/html'},'body':html}
