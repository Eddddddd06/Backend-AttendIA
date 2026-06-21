import boto3
import json
import os
from datetime import datetime, timezone

dynamodb = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')
sns_client = boto3.client('sns') 

TABLE_TICKETS = os.environ.get('DYNAMODB_TICKETS_TABLE', 't_tickets')
SERVICE_NAME = os.environ.get('SERVICE_NAME', 'triage-serverless')
STAGE = os.environ.get('STAGE', 'dev')
TICKETS_TOPIC_ARN = os.environ.get('TICKETS_SNS_TOPIC_ARN')


def lambda_handler(event, context):
    """
    PRIVADO - Requiere token válido.
    El Empleado o Admin marca un ticket como 'Resuelto'.

    Body requerido:
        tenant_id  - ID de la empresa
        ticket_id  - ID del ticket a resolver (también acepta path param)
    """
    try:
        token = event.get('headers', {}).get('Authorization', '')
        
        payload_auth = { "token": token }
        
        invoke_response = lambda_client.invoke(
            FunctionName=f"{SERVICE_NAME}-{STAGE}-ValidarTokenAcceso",
            InvocationType='RequestResponse',
            Payload=json.dumps(payload_auth)
        )
        
        response = json.loads(invoke_response['Payload'].read())
        if response.get('statusCode') == 403:
            return {
                'statusCode': 403,
                'body': json.dumps({'status': 'Forbidden - Acceso No Autorizado'})
            }
        body = event.get('body', {})
        if isinstance(body, str) and body:
            body = json.loads(body)
        elif not isinstance(body, dict):
            body = {}

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

        ticket_item = existing['Item']

        estado_actual = ticket_item.get('estado', '')
        if estado_actual == 'Resuelto':
            return {
                'statusCode': 409,
                'body': json.dumps({
                    'status': 'error',
                    'message': f'El ticket {ticket_id} ya fue resuelto anteriormente'
                })
            }

        correo_emisor = ticket_item.get('Contacto') or ticket_item.get('correo') or ticket_item.get('email')
        nombre_emisor = ticket_item.get('Nombre', 'Usuario')

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

        if correo_emisor:
            payload_evento = {
                "to_email": correo_emisor,
                "subject": f"Tu ticket #{ticket_id[:8]} ha sido resuelto",
                "body_content": f"Hola {nombre_emisor},\n\nTe informamos que tu ticket de soporte con ID {ticket_id} ha sido resuelto por nuestro equipo de atención.\n\nGracias por tu paciencia.\n\nSaludos cordiales."
            }
            
            try:
                sns_client.publish(
                    TopicArn=TICKETS_TOPIC_ARN,
                    Message=json.dumps(payload_evento),
                    Subject="TicketResueltoEvento"
                )
                print(f"[INFO] Evento de resolución publicado exitosamente en SNS para: {correo_emisor}")
            except Exception as sns_err:
                print(f"[WARNING] No se pudo publicar el evento en SNS: {sns_err}")
        else:
            print("[WARNING] No se encontró correo para lanzar el evento de notificación.")

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
