import boto3
import json
import uuid
import os
from datetime import datetime, timezone

dynamodb = boto3.resource('dynamodb')
sqs = boto3.client('sqs')

TABLE_TICKETS = os.environ.get('DYNAMODB_TICKETS_TABLE', 't_tickets')
SQS_QUEUE_URL = os.environ.get('SQS_QUEUE_URL', '')


def lambda_handler(event, context):
    """
    PÚBLICO - Sin autenticación requerida.
    El cliente final (usuario externo) envía su queja/reporte.
    No necesita estar registrado ni tener token.

    Body requerido:
        tenant_id   - ID de la empresa a la que se dirige el ticket
        descripcion - Descripción del problema o queja
        nombre      - (Opcional) Nombre del cliente
        contacto    - (Opcional) Email o teléfono del cliente
    """
    try:
        # Parsear body (llega como string desde API Gateway proxy)
        body = event.get('body', {})
        if isinstance(body, str):
            body = json.loads(body)
        if not isinstance(body, dict):
            body = {}

        tenant_id = body.get('tenant_id')
        descripcion = body.get('descripcion')
        nombre_cliente = body.get('nombre', 'Anónimo')
        contacto_cliente = body.get('contacto', '')

        # Validar campos mínimos requeridos
        if not tenant_id or not descripcion:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'Campos requeridos: tenant_id, descripcion'
                })
            }

        if len(descripcion.strip()) < 10:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'La descripción debe tener al menos 10 caracteres'
                })
            }

        # Generar ID único para el ticket
        ticket_id = str(uuid.uuid4())
        creado_en = datetime.now(timezone.utc).isoformat()

        # Armar mensaje para la cola SQS (ClasificarTicket lo procesará)
        mensaje = {
            'tenant_id': tenant_id,
            'ticket_id': ticket_id,
            'descripcion': descripcion.strip(),
            'nombre_cliente': nombre_cliente,
            'contacto_cliente': contacto_cliente,
            'creado_en': creado_en
        }

        sqs.send_message(
            QueueUrl=SQS_QUEUE_URL,
            MessageBody=json.dumps(mensaje),
            MessageAttributes={
                'tenant_id': {
                    'StringValue': tenant_id,
                    'DataType': 'String'
                }
            }
        )

        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'success',
                'message': 'Tu reporte fue recibido. Lo estamos procesando.',
                'data': {
                    'ticket_id': ticket_id,
                    'tenant_id': tenant_id,
                    'estado': 'pendiente',
                    'creado_en': creado_en
                }
            })
        }

    except json.JSONDecodeError as e:
        print(f"[ERROR] crear_ticket - JSON inválido: {e}")
        return {
            'statusCode': 400,
            'body': json.dumps({'status': 'error', 'message': 'Body inválido, se esperaba JSON'})
        }
    except Exception as e:
        print(f"[ERROR] crear_ticket: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'status': 'error', 'message': str(e)})
        }
