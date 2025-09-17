import os, json, boto3
sns = boto3.client('sns')

def _load_role_topic_map():
    raw = os.environ.get('ROLE_TOPIC_MAP', '').strip()
    if raw:
        try:
            m = json.loads(raw)
            if isinstance(m, dict) and m:
                return m
        except Exception:
            pass
    fb = os.environ.get('COMPRAS_APROBADORES', '').strip() or os.environ.get('SNS_TOPIC_COMPRAS_APROBADORES', '').strip()
    return {'COMPRAS_APROBADORES': fb} if fb else {}

ROLE_TOPIC_MAP = _load_role_topic_map()
APPROVAL_BASE_URL = os.environ.get('APPROVAL_BASE_URL', 'https://1y4g8pdtm1.execute-api.us-east-2.amazonaws.com')

def _detail(evt):
    d = evt.get('detail', evt)
    if isinstance(d, str):
        try: d = json.loads(d)
        except Exception: d = {}
    return d

def _publish_to_roles(roles, subject, message):
    if not ROLE_TOPIC_MAP:
        raise RuntimeError("ROLE_TOPIC_MAP vacío o inválido.")
    published = []
    for role in roles if isinstance(roles, list) else [roles]:
        arn = ROLE_TOPIC_MAP.get(role)
        if not arn:
            raise RuntimeError(f"No hay Topic ARN para '{role}' en ROLE_TOPIC_MAP: {ROLE_TOPIC_MAP}")
        res = sns.publish(TopicArn=arn, Subject=subject, Message=message)
        published.append({'role': role, 'topic': arn, 'messageId': res.get('MessageId')})
    return published

def lambda_handler(event, context):
    det = _detail(event)
    detail_type = event.get('detail-type') or event.get('detailType')
    order_id = det.get('orderId')

    if not detail_type and order_id:
        detail_type = "OrdenPendienteAprobacion"  # sólo para tests manuales

    if detail_type == 'OrdenPendienteAprobacion' and order_id:
        creador = det.get('ROL', 'CasaCentral')  # ← DEFINIRLO
        roles = det.get('audienceRoles', ['COMPRAS_APROBADORES'])

        approve_url = f"{APPROVAL_BASE_URL}/approvals/{order_id}/approve?ROL={creador}"
        reject_url  = f"{APPROVAL_BASE_URL}/approvals/{order_id}/reject?ROL={creador}"

        subject = f"OC {order_id} pendiente de aprobación (Rol: {creador})"
        msg = (
            f"Se creó la Orden de Compra {order_id} y requiere aprobación.\n\n"
            f"Aprobar: {approve_url}\n"
            f"Rechazar: {reject_url}\n"
        )

        pubs = _publish_to_roles(roles, subject, msg)
        return {'statusCode': 200, 'body': json.dumps({'sent': pubs, 'ROL': creador})}

    return {'statusCode': 200, 'body': json.dumps({'info': 'evento ignorado', 'detailType': detail_type, 'orderId': order_id})}
