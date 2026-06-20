import boto3
import json
import os

dynamodb = boto3.resource('dynamodb')
TABLE_USUARIOS = os.environ.get('DYNAMODB_USUARIOS_TABLE', 't_usuarios')
SERVICE_NAME = os.environ.get('SERVICE_NAME', 'triage-serverless')
STAGE = os.environ.get('STAGE', 'dev')


def lambda_handler(event, context):
    """
    PRIVADO - Requiere token válido de Administrador.
    Permite al Admin actualizar el catálogo de áreas de su empresa.
    Previene la eliminación de áreas que tengan empleados asignados activos.

    Body requerido:
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

        token_data = json.loads(response.get('body', '{}')).get('data', {})

        tenant_id = token_data.get('tenant_id')
        correo = token_data.get('correo')
        rol_usuario = token_data.get('rol')
        areas = body.get('areas', [])

        if not tenant_id or not correo:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'El token de acceso no contiene información de identidad válida'
                })
            }
        
        if rol_usuario != 'admin':
            return {
                'statusCode': 403,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'Forbidden - Solo los administradores pueden modificar las áreas'
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

        tabla = dynamodb.Table(TABLE_USUARIOS)

        # ── Validación Antifantasma: Bloquear eliminación de áreas activas ──
        
        # 1. Consultar todos los empleados pertenecientes a este tenant_id
        resultado_empleados = tabla.query(
            IndexName='RolIndex',
            KeyConditionExpression='rol = :rol AND tenant_id = :tenant_id',
            ExpressionAttributeValues={
                ':rol': 'empleado',
                ':tenant_id': tenant_id
            },
            ProjectionExpression='area'  # Optimizado: Solo descargamos el nombre del área
        )
        
        empleados = resultado_empleados.get('Items', [])
        
        # 2. Mapear en un set único las áreas que realmente están ocupadas por los trabajadores
        areas_en_uso = set(emp.get('area') for emp in empleados if emp.get('area'))
        
        # 3. Identificar si el Admin omitió (eliminó) algún área que tiene personal asignado
        areas_conflictivas = [area_activa for area_activa in areas_en_uso if area_activa not in areas]
        
        # Si se detectan inconsistencias, se frena el proceso enviando un mensaje claro
        if areas_conflictivas:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': f'No puedes eliminar las siguientes áreas porque tienen empleados asignados: {", ".join(areas_conflictivas)}. Reasigna a tu personal antes de quitarlas del catálogo.'
                })
            }

        # ── Actualizar las áreas en DynamoDB ───────────────────────────
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