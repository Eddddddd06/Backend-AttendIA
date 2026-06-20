import boto3
import json
import hashlib
import uuid
import os
from datetime import datetime, timezone, timedelta

dynamodb = boto3.resource('dynamodb')
TABLE_USUARIOS = os.environ.get('DYNAMODB_USUARIOS_TABLE', 't_usuarios')
TABLE_TOKENS = os.environ.get('DYNAMODB_TOKENS_TABLE', 't_tokens_acceso')

# TTL de 8 horas para el token
TOKEN_TTL_HOURS = 8


def lambda_handler(event, context):
    try:
        # Parsear body
        body = event.get('body', {})
        if isinstance(body, str):
            body = json.loads(body)

        tenant_id = body.get('tenant_id')
        correo = body.get('correo')
        password = body.get('password')

        # Validar campos requeridos
        if not all([tenant_id, correo, password]):
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'Faltan campos requeridos: tenant_id, correo, password'
                })
            }

        # Hash de la contraseña para comparar
        password_hash = hashlib.sha256(password.encode('utf-8')).hexdigest()

        # Buscar usuario en DynamoDB
        tabla_usuarios = dynamodb.Table(TABLE_USUARIOS)
        result = tabla_usuarios.get_item(
            Key={'tenant_id': tenant_id, 'correo': correo}
        )

        usuario = result.get('Item')

        # Verificar existencia y contraseña
        if not usuario:
            return {
                'statusCode': 401,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'Credenciales inválidas'
                })
            }

        if usuario.get('password_hash') != password_hash:
            return {
                'statusCode': 401,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'Credenciales inválidas'
                })
            }

        # Generar token único con UUID
        token = str(uuid.uuid4())

        # Calcular TTL (timestamp Unix para DynamoDB TTL)
        expiration_time = datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS)
        ttl_timestamp = int(expiration_time.timestamp())

        # Guardar token en t_tokens_acceso
        tabla_tokens = dynamodb.Table(TABLE_TOKENS)
        tabla_tokens.put_item(
            Item={
                'token': token,
                'tenant_id': tenant_id,
                'correo': correo,
                'rol': usuario.get('rol', 'empleado'),
                'area': usuario.get('area', ''),
                'nombre_empresa': usuario.get('nombre_empresa', ''),
                'creado_en': datetime.now(timezone.utc).isoformat(),
                'expira_en': expiration_time.isoformat(),
                'ttl': ttl_timestamp  # DynamoDB TTL automático
            }
        )

        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'success',
                'message': 'Login exitoso',
                'data': {
                    'token': token,
                    'tenant_id': tenant_id,
                    'correo': correo,
                    'rol': usuario.get('rol', 'empleado'),
                    'area': usuario.get('area', ''),
                    'nombre_empresa': usuario.get('nombre_empresa', ''),
                    'expira_en': expiration_time.isoformat()
                }
            })
        }

    except json.JSONDecodeError:
        return {
            'statusCode': 400,
            'body': json.dumps({'status': 'error', 'message': 'Body inválido, se esperaba JSON'})
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'status': 'error', 'message': str(e)})
        }
