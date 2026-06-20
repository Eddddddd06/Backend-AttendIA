import boto3
import json
import os
from datetime import datetime, timezone

dynamodb = boto3.resource('dynamodb')
TABLE_TICKETS = os.environ.get('DYNAMODB_TICKETS_TABLE', 't_tickets')
SERVICE_NAME = os.environ.get('SERVICE_NAME', 'triage-serverless')
STAGE = os.environ.get('STAGE', 'dev')


def lambda_handler(event, context):
    """
    PRIVADO - Requiere token válido.
    El Empleado o Admin marca un ticket como 'Resuelto'.

    Body requerido:
        tenant_id  - ID de la empresa
        ticket_id  - ID del ticket a resolver (también acepta path param)
    """
    try:
        # ── Inicio: Proteger el Lambda ──────────────────────────────────
        token = event.get('headers', {}).get('Authorization', '')
        lambda_client = boto3.client('lambda')
        payload_string = '{ "token": "' + token + '" }'
        invoke_response = lambda_client.invoke(
            FunctionName=f"{SERVICE_NAME}-{STAGE}-ValidarTokenAcceso",
            InvocationType='RequestResponse',
            Payload=payload_string
        )
        response = json.loads(invoke_response['Payload'].read())
        if response.get('statusCode') == 403:
            return {
                'statusCode': 403,
                'body': json.dumps({'status': 'Forbidden - Acceso No Autorizado'})
            }
        # ── Fin: Proteger el Lambda ─────────────────────────────────────

        # Parsear body
        body = event.get('body', {})
        if isinstance(body, str) and body:
            body = json.loads(body)
        elif not isinstance(body, dict):
            body = {}

        # ticket_id puede venir del path (/tickets/{ticket_id}/resolver)
        path_params = event.get('pathParameters') or {}
        ticket_id = path_params.get('ticket_id') or body.get('ticket_id')
        tenant_id = body.get('tenant_id')

        if not tenant_id or not ticket_id:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'Campos requeridos: tenant_id, ticket_id'
                })
            }

        tabla_tickets = dynamodb.Table(TABLE_TICKETS)

        # Verificar que el ticket existe antes de actualizar
        existing = tabla_tickets.get_item(
            Key={'tenant_id': tenant_id, 'ticket_id': ticket_id}
        )
        if 'Item' not in existing:
            return {
                'statusCode': 404,
                'body': json.dumps({
                    'status': 'error',
                    'message': f'Ticket {ticket_id} no encontrado para el tenant {tenant_id}'
                })
            }

        # Verificar que no esté ya resuelto
        estado_actual = existing['Item'].get('estado', '')
        if estado_actual == 'Resuelto':
            return {
                'statusCode': 409,
                'body': json.dumps({
                    'status': 'error',
                    'message': f'El ticket {ticket_id} ya fue resuelto anteriormente'
                })
            }

        # Actualizar estado a 'Resuelto'
        resuelto_en = datetime.now(timezone.utc).isoformat()
        tabla_tickets.update_item(
            Key={'tenant_id': tenant_id, 'ticket_id': ticket_id},
            UpdateExpression='SET #estado = :estado, resuelto_en = :resuelto_en',
            ExpressionAttributeNames={'#estado': 'estado'},
            ExpressionAttributeValues={
                ':estado': 'Resuelto',
                ':resuelto_en': resuelto_en
            }
        )

        print(f"[OK] resolver_ticket - Ticket {ticket_id} del tenant {tenant_id} resuelto.")

        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'success',
                'message': f'Ticket {ticket_id} marcado como Resuelto',
                'data': {
                    'tenant_id': tenant_id,
                    'ticket_id': ticket_id,
                    'estado': 'Resuelto',
                    'resuelto_en': resuelto_en
                }
            })
        }

    except json.JSONDecodeError as e:
        print(f"[ERROR] resolver_ticket - JSON inválido: {e}")
        return {
            'statusCode': 400,
            'body': json.dumps({'status': 'error', 'message': 'Body inválido, se esperaba JSON'})
        }
    except Exception as e:
        print(f"[ERROR] resolver_ticket: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'status': 'error', 'message': str(e)})
        }
