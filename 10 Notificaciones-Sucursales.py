import os, json, boto3
from botocore.exceptions import ClientError

sns = boto3.client('sns')

SUCURSALES_TOPIC_ARN = os.environ.get('SUCURSALES_TOPIC_ARN', '').strip()
APP_NAME = os.environ.get('APP_NAME', 'NBA')

def _detail(evt):
    d = evt.get('detail', evt)
    if isinstance(d, str):
        try: d = json.loads(d)
        except Exception: d = {}
    return d

def lambda_handler(event, context):
    if not SUCURSALES_TOPIC_ARN:
        return {'statusCode': 500, 'body': json.dumps({'error':'Falta SUCURSALES_TOPIC_ARN'})}

    det = _detail(event)
    if (event.get('detail-type') or event.get('detailType')) != 'DespachoConfirmado':
        return {'statusCode': 200, 'body': json.dumps({'info':'evento ignorado'})}

    order_id    = det.get('orderId')
    sucursales  = det.get('sucursales') or []
    dispatched  = det.get('dispatchedAt', '')

    enviados = []
    for suc in sucursales:
        subject = f"[{APP_NAME}] {suc}: Despacho confirmado – OC {order_id}"
        msg = (
            f"Hola {suc},\n\n"
            f"Se confirmó el despacho de la Orden de Compra {order_id}.\n"
            f"Fecha/Hora: {dispatched}\n\n"
            f"Este es un aviso automático."
        )
        try:
            res = sns.publish(TopicArn=SUCURSALES_TOPIC_ARN, Subject=subject, Message=msg)
            enviados.append({'sucursal': suc, 'messageId': res.get('MessageId')})
        except ClientError as e:
            enviados.append({'sucursal': suc, 'error': str(e)})

    return {'statusCode': 200, 'body': json.dumps({'sent': enviados})}
