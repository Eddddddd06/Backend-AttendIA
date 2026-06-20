import boto3
import json
import uuid
import os
from datetime import datetime, timezone

# Inicializar recursos de AWS
dynamodb = boto3.resource('dynamodb')
sqs = boto3.client('sqs')

# Variables de entorno heredadas de serverless.yml
TABLE_USUARIOS = os.environ.get('DYNAMODB_USUARIOS_TABLE', 't_usuarios')
SQS_QUEUE_URL = os.environ.get('SQS_QUEUE_URL', '')
SERVICE_NAME = os.environ.get('SERVICE_NAME', 'triage-serverless')
STAGE = os.environ.get('STAGE', 'dev')

MAX_TICKETS_POR_CARGA = 100  # Límite de seguridad por request


def lambda_handler(event, context):
    """
    PRIVADO - Requiere token de Admin en los Headers (Authorization).
    El Admin sube un CSV desde el frontend (convertido a un array JSON de objetos).
    Este Lambda encola cada ticket en SQS de forma asíncrona heredando de forma segura 
    el tenant_id desde la sesión validada.

    Body esperado en la petición:
        {
            "tickets": [
                { "descripcion": "Mi producto llegó roto", "nombre_cliente": "Juan Perez", "contacto_cliente": "juan@mail.com" },
                { "descripcion": "No puedo ingresar a la plataforma con mi clave", "nombre_cliente": "Ana Gomez" }
            ]
        }
    """
    try:
        # ── Inicio: Proteger el Lambda (Invocación Lambda-to-Lambda) ─────
        token = event.get('headers', {}).get('Authorization', '')
        lambda_client = boto3.client('lambda')
        payload_string = '{ "token": "' + token + '" }'
        
        invoke_response = lambda_client.invoke(
            FunctionName=f"{SERVICE_NAME}-{STAGE}-ValidarTokenAcceso",
            InvocationType='RequestResponse',
            Payload=payload_string
        )
        auth_response = json.loads(invoke_response['Payload'].read())
        
        # Si el token es inválido o expiró, rebotamos inmediatamente
        if auth_response.get('statusCode') == 403:
            return {
                'statusCode': 403,
                'body': json.dumps({'status': 'Forbidden - Acceso No Autorizado'})
            }
        # ── Fin: Proteger el Lambda ─────────────────────────────────────

        # Parsear el body de la petición HTTP
        body = event.get('body', {})
        if isinstance(body, str) and body:
            body = json.loads(body)
        elif not isinstance(body, dict):
            body = {}

        # 🌟 SEGURIDAD MULTI-TENANT: Extraer datos reales del token validado
        token_data = json.loads(auth_response.get('body', '{}')).get('data', {})
        tenant_id = token_data.get('tenant_id')
        rol_usuario = token_data.get('rol')

        # Control de accesos estricto: Solo los Admins cargan datos masivos
        if rol_usuario != 'admin':
            return {
                'statusCode': 403,
                'body': json.dumps({
                    'status': 'error', 
                    'message': 'Forbidden - Solo los administradores pueden cargar archivos masivos de tickets'
                })
            }

        tickets_raw = body.get('tickets', [])

        # ── Validaciones de la Estructura de Datos ───────────────────────
        if not isinstance(tickets_raw, list) or len(tickets_raw) == 0:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'El campo "tickets" debe ser una lista JSON no vacía'
                })
            }

        if len(tickets_raw) > MAX_TICKETS_POR_CARGA:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': f'Límite excedido: El máximo permitido es de {MAX_TICKETS_POR_CARGA} tickets por carga'
                })
            }

        # Arrays para controlar el estatus del procesamiento masivo
        encolados = []
        errores = []
        creado_en = datetime.now(timezone.utc).isoformat()

        # ── Recorrer y Encolar cada ticket en SQS ────────────────────────
        for i, ticket_data in enumerate(tickets_raw):
            try:
                descripcion = ticket_data.get('descripcion', '').strip()

                # Validación básica por cada registro individual
                if not descripcion or len(descripcion) < 5:
                    errores.append({
                        'fila': i + 1,
                        'error': 'Descripción vacía o demasiado corta (mínimo 5 caracteres)'
                    })
                    continue

                # Generamos un ID único universal para el seguimiento del ticket
                ticket_id = str(uuid.uuid4())

                # Estructura del payload que viajará a través de la cola SQS
                mensaje_cola = {
                    'tenant_id': tenant_id,
                    'ticket_id': ticket_id,
                    'descripcion': descripcion,
                    'nombre_cliente': ticket_data.get('nombre_cliente', 'Sin nombre'),
                    'contacto_cliente': ticket_data.get('contacto_cliente', ''),
                    'creado_en': creado_en,
                    'origen': 'csv_admin'  # Permite identificar auditorías de carga masiva
                }

                # Despachar el mensaje a Amazon SQS
                sqs.send_message(
                    QueueUrl=SQS_QUEUE_URL,
                    MessageBody=json.dumps(mensaje_cola),
                    MessageAttributes={
                        'tenant_id': {
                            'StringValue': tenant_id,
                            'DataType': 'String'
                        }
                    }
                )

                encolados.append(ticket_id)
                print(f"[OK] cargar_csv - Ticket {ticket_id} encolado exitosamente (fila {i + 1})")

            except Exception as e:
                print(f"[ERROR] cargar_csv - Excepción en fila {i + 1}: {e}")
                errores.append({'fila': i + 1, 'error': str(e)})

        # Respuesta consolidada al Frontend
        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'success',
                'message': f'Procesamiento masivo completado. {len(encolados)} tickets encolados para su triaje automático.',
                'resumen': {
                    'total_recibidos': len(tickets_raw),
                    'encolados_ok': len(encolados),
                    'fallidos': len(errores)
                },
                'ticket_ids': encolados,
                'errores': errores
            })
        }

    except json.JSONDecodeError as e:
        print(f"[ERROR] cargar_csv - JSON malformado en el request: {e}")
        return {
            'statusCode': 400,
            'body': json.dumps({'status': 'error', 'message': 'Body inválido, se esperaba una estructura JSON válida'})
        }
    except Exception as e:
        print(f"[ERROR] cargar_csv - Error Crítico en Handler: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'status': 'error', 'message': str(e)})
        }