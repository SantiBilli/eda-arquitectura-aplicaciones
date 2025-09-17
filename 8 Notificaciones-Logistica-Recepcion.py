import os, json, boto3
from botocore.exceptions import ClientError

sns = boto3.client('sns')

LOGISTICA_TOPIC_ARN = os.environ.get('LOGISTICA', '').strip()
API_BASE_URL        = os.environ.get('API_BASE_URL', 'https://1y4g8pdtm1.execute-api.us-east-2.amazonaws.com')
APP_NAME            = os.environ.get('APP_NAME', 'NBA')

def _detail(evt):
    d = evt.get('detail', evt)
    if isinstance(d, str):
        try: d = json.loads(d)
        except Exception: d = {}
    return d

def lambda_handler(event, context):
    print("[EVENT]", json.dumps(event))

    if (event.get('detail-type') or event.get('detailType')) != 'RecepcionRecibida':
        return {'statusCode': 200, 'body': json.dumps({'info': 'evento ignorado'})}

    if not LOGISTICA_TOPIC_ARN:
        return {'statusCode': 500, 'body': json.dumps({'error': 'Falta env LOGISTICA con ARN del topic'})}

    det       = _detail(event)
    order_id  = det.get('orderId')
    received  = det.get('receivedAt', '')

    if not order_id:
        return {'statusCode': 400, 'body': json.dumps({'error': 'orderId ausente en event.detail'})}

    confirm_url = f"{API_BASE_URL}/despachos/{order_id}/confirm"

    subject = f"[{APP_NAME}] Logística: stock disponible para OC {order_id}"
    msg = (
        f"Se confirmó la recepción en Depósito.\n\n"
        f"OC: {order_id}\n"
        f"Fecha recepción: {received}\n\n"
        f"Confirmá el despacho aquí:\n{confirm_url}\n"
    )

    try:
        res = sns.publish(TopicArn=LOGISTICA_TOPIC_ARN, Subject=subject, Message=msg)
        return {'statusCode': 200, 'body': json.dumps({'messageId': res.get('MessageId'), 'topic': LOGISTICA_TOPIC_ARN})}
    except ClientError as e:
        return {'statusCode': 500, 'body': json.dumps({'error': f'SNS: {str(e)}'})}
