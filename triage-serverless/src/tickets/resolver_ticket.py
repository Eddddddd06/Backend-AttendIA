import boto3
import json
import os
from datetime import datetime, timezone

# 🛠️ Buenas prácticas: Clientes globales para optimizar recursos
dynamodb = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')

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
        # ── Inicio: Proteger el Lambda (Seguro contra Inyecciones) ──────
        token = event.get('headers', {}).get('Authorization', '')
        
        # Usamos json.dumps para sanitizar el payload
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

        ticket_item = existing['Item']

        # Verificar que no esté ya resuelto
        estado_actual = ticket_item.get('estado', '')
        if estado_actual == 'Resuelto':
            return {
                'statusCode': 409,
                'body': json.dumps({
                    'status': 'error',
                    'message': f'El ticket {ticket_id} ya fue resuelto anteriormente'
                })
            }

        # Extraer el correo del emisor original para notificarle
        correo_emisor = ticket_item.get('Contacto') or ticket_item.get('correo') or ticket_item.get('email')
        nombre_emisor = ticket_item.get('Nombre', 'Usuario')

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

        # ── Inicio: Disparo Asíncrono del Correo ────────────────────────
        if correo_emisor:
            payload_correo = {
                "to_email": correo_emisor,
                "subject": f"Tu ticket #{ticket_id[:8]} ha sido resuelto",
                "body_content": f"Hola {nombre_emisor},\n\nTe informamos que tu ticket de soporte con ID {ticket_id} ha sido resuelto por nuestro equipo de atención.\n\nGracias por tu paciencia.\n\nSaludos cordiales."
            }
            
            try:
                # 🚀 InvocationType='Event' lo hace asíncrono (Fire and Forget)
                lambda_client.invoke(
                    FunctionName=f"{SERVICE_NAME}-{STAGE}-EnviarCorreoNotificacion", 
                    InvocationType='Event',
                    Payload=json.dumps(payload_correo)
                )
                print(f"[INFO] Gatillado asíncrono de correo enviado a {correo_emisor}")
            except Exception as mail_err:
                # Si falla el trigger del correo, no tumbamos la transacción principal del usuario
                print(f"[WARNING] No se pudo gatillar el Lambda de correo: {mail_err}")
        else:
            print("[WARNING] No se encontró un campo de correo válido ('Contacto', 'correo', o 'email') en el ticket para notificar.")
        # ── Fin: Disparo Asíncrono del Correo ───────────────────────────

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