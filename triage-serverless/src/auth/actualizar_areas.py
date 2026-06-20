import boto3
import json
import os

dynamodb = boto3.resource('dynamodb')
TABLE_USUARIOS = os.environ.get('DYNAMODB_USUARIOS_TABLE', 't_usuarios')
SERVICE_NAME = os.environ.get('SERVICE_NAME', 'triage-serverless')
STAGE = os.environ.get('STAGE', 'dev')


def lambda_handler(event, context):
    """
    PRIVADO - Requiere token válido (Idealmente validado que es Admin en el frontend o aquí).
    Permite al Admin actualizar el catálogo de áreas de su empresa.

    Body requerido:
        tenant_id  - ID de la empresa
        correo     - Correo del admin (PK secundaria para actualizar el registro exacto)
        areas      - Lista de strings, ej: ["Ventas", "Soporte Técnico", "Cobranzas"]
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

        body = event.get('body', {})
        if isinstance(body, str):
            body = json.loads(body)

        tenant_id = body.get('tenant_id')
        correo = body.get('correo')
        areas = body.get('areas', [])

        if not tenant_id or not correo:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'Faltan campos requeridos: tenant_id, correo'
                })
            }

        if not isinstance(areas, list):
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'El campo "areas" debe ser una lista'
                })
            }

        # Actualizar el registro del admin
        tabla = dynamodb.Table(TABLE_USUARIOS)
        
        # Primero validamos que el usuario existe y es admin
        existing = tabla.get_item(Key={'tenant_id': tenant_id, 'correo': correo})
        if 'Item' not in existing or existing['Item'].get('rol') != 'admin':
            return {
                'statusCode': 403,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'Usuario no encontrado o no tiene rol de admin'
                })
            }

        # Actualizar las áreas
        tabla.update_item(
            Key={'tenant_id': tenant_id, 'correo': correo},
            UpdateExpression='SET areas = :areas',
            ExpressionAttributeValues={':areas': areas}
        )

        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'success',
                'message': 'Catálogo de áreas actualizado correctamente',
                'data': {
                    'tenant_id': tenant_id,
                    'areas': areas
                }
            })
        }

    except json.JSONDecodeError:
        return {
            'statusCode': 400,
            'body': json.dumps({'status': 'error', 'message': 'Body inválido, se esperaba JSON'})
        }
    except Exception as e:
        print(f"[ERROR] actualizar_areas: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'status': 'error', 'message': str(e)})
        }
