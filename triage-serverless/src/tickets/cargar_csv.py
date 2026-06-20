import boto3
import json
import uuid
import os
from datetime import datetime, timezone

dynamodb = boto3.resource('dynamodb')
sqs = boto3.client('sqs')

TABLE_USUARIOS = os.environ.get('DYNAMODB_USUARIOS_TABLE', 't_usuarios')
SQS_QUEUE_URL = os.environ.get('SQS_QUEUE_URL', '')
SERVICE_NAME = os.environ.get('SERVICE_NAME', 'triage-serverless')
STAGE = os.environ.get('STAGE', 'dev')

MAX_TICKETS_POR_CARGA = 100  # Límite de seguridad por request


def lambda_handler(event, context):
    """
    PRIVADO - Requiere token de Admin.
    El Admin sube un CSV desde el front; el front lo convierte a una lista JSON
    y lo envía aquí. Este Lambda encola cada ticket en SQS para que
    ClasificarTicket los procese uno a uno de forma asíncrona.

    Body requerido:
        tenant_id  - ID de la empresa del admin
        tickets    - Lista de objetos con { descripcion, nombre_cliente?, contacto_cliente? }

    Ejemplo de body:
        {
            "tenant_id": "empresa_acme",
            "tickets": [
                { "descripcion": "Mi producto llegó roto", "nombre_cliente": "Juan" },
                { "descripcion": "No recibí mi pedido", "contacto_cliente": "ana@mail.com" }
            ]
        }
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
        auth_response = json.loads(invoke_response['Payload'].read())
        if auth_response.get('statusCode') == 403:
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

        tenant_id = body.get('tenant_id', '').strip()
        tickets_raw = body.get('tickets', [])

        # ── Validaciones ─────────────────────────────────────────────────
        if not tenant_id:
            return {
                'statusCode': 400,
                'body': json.dumps({'status': 'error', 'message': 'Falta el campo requerido: tenant_id'})
            }

        if not isinstance(tickets_raw, list) or len(tickets_raw) == 0:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'El campo "tickets" debe ser una lista no vacía'
                })
            }

        if len(tickets_raw) > MAX_TICKETS_POR_CARGA:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': f'Límite excedido: máximo {MAX_TICKETS_POR_CARGA} tickets por carga'
                })
            }

        # ── Encolar cada ticket en SQS ────────────────────────────────────
        encolados = []
        errores = []
        creado_en = datetime.now(timezone.utc).isoformat()

        for i, ticket_data in enumerate(tickets_raw):
            try:
                descripcion = ticket_data.get('descripcion', '').strip()

                if not descripcion or len(descripcion) < 5:
                    errores.append({
                        'fila': i + 1,
                        'error': 'Descripción vacía o muy corta (mínimo 5 caracteres)'
                    })
                    continue

                ticket_id = str(uuid.uuid4())

                mensaje = {
                    'tenant_id': tenant_id,
                    'ticket_id': ticket_id,
                    'descripcion': descripcion,
                    'nombre_cliente': ticket_data.get('nombre_cliente', 'Sin nombre'),
                    'contacto_cliente': ticket_data.get('contacto_cliente', ''),
                    'creado_en': creado_en,
                    'origen': 'csv_admin'  # Marca para distinguir el origen
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

                encolados.append(ticket_id)
                print(f"[OK] cargar_csv - Ticket {ticket_id} encolado (fila {i + 1})")

            except Exception as e:
                print(f"[ERROR] cargar_csv - Error en fila {i + 1}: {e}")
                errores.append({'fila': i + 1, 'error': str(e)})

        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'success',
                'message': f'{len(encolados)} tickets encolados para clasificación',
                'resumen': {
                    'total_enviados': len(tickets_raw),
                    'encolados': len(encolados),
                    'errores': len(errores)
                },
                'ticket_ids': encolados,
                'errores': errores
            })
        }

    except json.JSONDecodeError as e:
        print(f"[ERROR] cargar_csv - JSON inválido: {e}")
        return {
            'statusCode': 400,
            'body': json.dumps({'status': 'error', 'message': 'Body inválido, se esperaba JSON'})
        }
    except Exception as e:
        print(f"[ERROR] cargar_csv: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'status': 'error', 'message': str(e)})
        }
