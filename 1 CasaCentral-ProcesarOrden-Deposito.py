import os, json, boto3
from datetime import datetime
from botocore.exceptions import ClientError

dynamo = boto3.resource('dynamodb')
events = boto3.client('events')

ORDERS_TABLE = "OrdenesCompra"
EVENT_BUS    = "ventas-bus"
EVENT_SRC    = "com.casacentral.procesos" #Notificaciones-OC

ROL = "CasaCentral"

table_ordenes = dynamo.Table(ORDERS_TABLE)

def _get_detail(evt):
    d = evt.get('detail', evt)
    if isinstance(d, str):
        try: d = json.loads(d)
        except Exception: d = {}
    return d

def lambda_handler(event, context):
    try:
        detail = _get_detail(event)
        order_id = detail.get('orderId') or detail.get('id_orden')
        if not order_id:
            return {'statusCode': 400, 'body': json.dumps({'error': 'orderId requerido'})}

        now_iso = datetime.utcnow().isoformat()

        # 1) status -> PENDING_APPROVAL
        table_ordenes.update_item(
            Key={'orderId': order_id},
            UpdateExpression='SET #st=:st, updatedAt=:ts',
            ExpressionAttributeNames={'#st': 'status'},
            ExpressionAttributeValues={':st': 'PENDING_APPROVAL', ':ts': now_iso},
            ConditionExpression='attribute_exists(orderId)'
        )

        # 2) Evento con ROL hardcodeado + destinatarios
        events.put_events(Entries=[{
            'Source': EVENT_SRC,
            'DetailType': 'OrdenPendienteAprobacion',
            'Detail': json.dumps({
                'orderId': order_id,
                'ROL': ROL,                                   # <- aquí viaja el rol
                'audienceRoles': ['COMPRAS_APROBADORES']      # destinatarios
            }),
            'EventBusName': EVENT_BUS
        }])

        return {'statusCode': 200, 'body': json.dumps({
            'orderId': order_id, 'status': 'PENDING_APPROVAL', 'ROL': ROL
        })}

    except ClientError as e:
        code = e.response.get('Error', {}).get('Code')
        if code == 'ConditionalCheckFailedException':
            return {'statusCode': 404, 'body': json.dumps({'error': f'Orden {order_id} no existe'})}
        return {'statusCode': 500, 'body': json.dumps({'error': f'AWS: {str(e)}'})}
    except Exception as e:
        return {'statusCode': 500, 'body': json.dumps({'error': f'Interno: {str(e)}'})}
